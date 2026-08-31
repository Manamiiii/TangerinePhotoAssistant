"""Optional Windows window and service supervisor; core browsing stays HTTP-only."""
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import webbrowser
from collections.abc import Callable
from pathlib import Path
from threading import Event, Thread
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from .app_paths import config_identity, resource_root, service_runtime_directory, user_app_directory
from .build_info import build_info
from .desktop_lock import FileLease, LeaseBusy
from .service_runtime import APP_ID, CONTROL_HEADER, TERMINAL_TASK_STATES
from .settings import Settings, write_safe_config


class DesktopError(RuntimeError):
    pass


class ServiceClient:
    def __init__(self, config_path: Path, port: int = 8765):
        if not 1024 <= port <= 65535:
            raise ValueError("本地端口必须在 1024–65535 之间")
        self.config_path = config_path.resolve()
        self.port = port
        self.url = f"http://127.0.0.1:{port}"
        self.runtime = service_runtime_directory(config_path, port)
        self.opener = build_opener(ProxyHandler({}))

    def request(self, path: str, *, headers=None, post: bool = False) -> dict[str, Any]:
        request = Request(self.url + path, data=b"{}" if post else None,
                          headers=headers or {}, method="POST" if post else "GET")
        try:
            with self.opener.open(request, timeout=3) as response:
                payload = response.read(1_048_577)
            if len(payload) > 1_048_576:
                raise DesktopError("本地服务响应过大")
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise DesktopError("本地服务响应格式不正确")
            return result
        except HTTPError as exc:
            # Only expose the known control endpoint's short user-facing reason.
            if path == "/api/system/desktop/shutdown":
                try:
                    detail = json.loads(exc.read(4096)).get("detail", "重启请求被拒绝")
                except (ValueError, AttributeError):
                    detail = "重启请求被拒绝"
                raise DesktopError(str(detail)) from exc
            raise DesktopError("本地端口上的服务不兼容") from exc

    def health(self) -> dict[str, Any] | None:
        try:
            health = self.request("/api/health")
        except (URLError, OSError):
            return None
        if health.get("status") != "ok" or health.get("mode") != "local-only":
            raise DesktopError("端口已被其他服务占用；不会停止该进程")
        if health.get("app_id") is not None:
            if health.get("app_id") != APP_ID or health.get("config_identity") != config_identity(self.config_path):
                raise DesktopError("此端口属于另一份应用配置；不会复用或停止该服务")
        else:
            # One-time compatibility with the pre-desktop service. It can be
            # viewed after checking configured roots, but never controlled/killed.
            settings = Settings.load(self.config_path)
            configured = self.request("/api/settings").get("configured", {})
            roots = (configured.get("library", {}).get("originals"),
                     configured.get("library", {}).get("workspace"),
                     configured.get("cache", {}).get("root"))
            expected = (settings.originals, settings.workspace, settings.cache_root)
            if not all(value and Path(value).resolve() == path.resolve()
                       for value, path in zip(roots, expected, strict=True)):
                raise DesktopError("旧服务的配置与当前应用不一致；请先核对启动配置")
        return health

    def port_open(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.4):
                return True
        except OSError:
            return False

    def backend_command(self) -> list[str]:
        command = [sys.executable] if getattr(sys, "frozen", False) else [
            sys.executable, "-m", "tangerine_photo_assistant.desktop"]
        return [*command, "--backend", "--config", str(self.config_path), "--port", str(self.port)]

    def ensure_running(self, progress: Callable[[str], None], cancelled: Event | None = None,
                       timeout: float = 900) -> dict[str, Any]:
        stop = cancelled or Event()
        self.runtime.mkdir(parents=True, exist_ok=True)
        deadline = time.monotonic() + timeout
        # Other launchers can wait for the same backend rather than start a copy.
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                with FileLease(self.runtime / "launch.lock"):
                    return self._ensure_locked(progress, stop, deadline)
            except LeaseBusy:
                progress("另一个窗口正在启动服务，正在等待…")
                stop.wait(0.5)
        raise DesktopError("窗口已关闭或等待启动超时；未终止后台进程")

    def _ensure_locked(self, progress, stop: Event, deadline: float) -> dict[str, Any]:
        health = self.health()
        if health:
            if health.get("draining"):
                raise DesktopError("服务正在退出，请稍后重新连接")
            return health
        if self.port_open():
            raise DesktopError("端口已占用但健康检查未通过；不会启动第二个服务")
        # The backend lease is held through migrations and for the entire service
        # lifetime. A closed GUI cannot strand a startup in an untracked state.
        backend_active = False
        try:
            with FileLease(self.runtime / "backend.lock"):
                pass
        except LeaseBusy:
            backend_active = True
        process = None
        if not backend_active:
            progress("正在启动本地服务；首次数据库升级可能需要几分钟…")
            environment = os.environ.copy()
            environment["PYTHONUTF8"] = "1"
            environment["PYTHONIOENCODING"] = "utf-8"
            process = subprocess.Popen(
                self.backend_command(), cwd=str(resource_root()), env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
        while not stop.is_set() and time.monotonic() < deadline:
            health = self.health()
            if health:
                return health
            if process is not None and process.poll() is not None:
                raise DesktopError("本地服务启动失败。可通过“打开启动日志目录”排查；未修改照片。")
            progress("正在等待服务就绪；数据库备份和升级期间请勿关闭电脑…")
            stop.wait(1)
        raise DesktopError("启动等待已结束；后台进程未被强制停止，可稍后重新连接")

    def stop(self, progress: Callable[[str], None], cancelled: Event | None = None) -> None:
        health = self.health()
        if not health or not health.get("desktop_control"):
            raise DesktopError("当前是旧版或未运行的服务。旧服务需按原方式重启一次，之后可使用此入口。")
        task = self.request("/api/tasks/current")
        if task.get("status") not in TERMINAL_TASK_STATES:
            raise DesktopError("有运行或暂停的后台任务，不能重启")
        try:
            record = json.loads((self.runtime / "service.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise DesktopError("缺少此服务的本地控制凭据；不会结束任何进程") from exc
        if record.get("instance_id") != health.get("instance_id") or not record.get("token"):
            raise DesktopError("服务实例已变化，请重新连接后再试")
        session = self.request("/api/session")
        self.request("/api/system/desktop/shutdown", post=True,
                     headers={session["header"]: session["token"], CONTROL_HEADER: record["token"]})
        progress("正在等待服务安全退出…")
        deadline = time.monotonic() + 30
        stop = cancelled or Event()
        while time.monotonic() < deadline and not stop.is_set():
            current = self.health()
            if current and current.get("instance_id") != health["instance_id"]:
                raise DesktopError("端口服务已变化；已停止重启操作")
            if current is None and not self.port_open():
                # Wait for final cleanup/lease release before spawning a successor.
                try:
                    with FileLease(self.runtime / "backend.lock"):
                        break
                except LeaseBusy:
                    pass
            stop.wait(0.25)
        else:
            raise DesktopError("服务尚未退出；未强制终止，请稍后重新连接")

    def restart(self, progress: Callable[[str], None], cancelled: Event | None = None) -> None:
        self.stop(progress, cancelled)
        self.ensure_running(progress, cancelled)


def prepare_default_config() -> Path:
    directory = user_app_directory()
    config = directory / "config.toml"
    if not config.exists():
        directory.mkdir(parents=True, exist_ok=True)
        inbox = directory / "PhotoInbox"
        inbox.mkdir(exist_ok=True)
        write_safe_config(config, inbox, directory / "Workspace", directory / "Cache")
    return config


def validate_desktop(config: Path) -> dict[str, object]:
    from . import __version__
    from .database import SCHEMA_VERSION

    errors = Settings.load(config).validate()
    if errors:
        raise DesktopError("配置校验失败，请通过配置文件核对目录与只读安全开关")
    for relative in ("web/dist/index.html", "equipment/profile.toml", "assets/tangerine-photo-assistant.ico"):
        if not (resource_root() / relative).is_file():
            raise DesktopError(f"缺少应用资源：{relative}")
    return {"status": "ok", "version": __version__, "schema_version": SCHEMA_VERSION,
            "packaged": bool(getattr(sys, "frozen", False)), "build": build_info()}


def run_window(config: Path, port: int) -> int:
    import webview
    from webview.menu import Menu, MenuAction, MenuSeparator

    from .desktop_window import DesktopWindow

    client = ServiceClient(config, port)
    controller = DesktopWindow(client)
    webview.settings["ALLOW_FILE_URLS"] = False
    webview.settings["ALLOW_DOWNLOADS"] = True
    webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"] = True
    webview.settings["OPEN_DEVTOOLS_IN_DEBUG"] = False
    menu = [Menu("应用", [MenuAction("重新连接", controller.connect),
                         MenuAction("安全重启服务", controller.restart),
                         MenuAction("安全停止服务", controller.stop),
                         MenuAction("版本与更新", controller.about),
                         MenuAction("检查本地安装包", controller.inspect_package),
                         MenuAction("打开程序维护目录", controller.open_program),
                         MenuAction("在浏览器中打开", lambda: webbrowser.open(client.url)),
                         MenuAction("打开启动日志目录", controller.open_logs),
                         MenuSeparator(), MenuAction("关闭窗口（后台继续运行）", controller.close)])]
    window = webview.create_window("TangerinePhotoAssistant", html=controller.splash(),
                                   width=1440, height=960, min_size=(1024, 700),
                                   background_color="#faf7f1", text_select=True, menu=menu)
    controller.window = window
    window.events.closed += controller.cancelled.set
    lease = FileLease(client.runtime / "window.lock")
    try:
        lease.__enter__()
    except LeaseBusy:
        (client.runtime / "focus.request").touch()
        return 0
    try:
        Thread(target=controller.watch_focus, daemon=True).start()
        webview.start(controller.connect, gui="edgechromium", private_mode=False,
                      storage_path=str(client.runtime / "WebView2"),
                      icon=str(resource_root() / "assets/tangerine-photo-assistant.ico"))
    finally:
        controller.cancelled.set()
        lease.__exit__()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="TangerinePhotoAssistant desktop")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--backend", action="store_true")
    parser.add_argument("--check", action="store_true", help="Validate resources/config without starting a service")
    parser.add_argument("--report", type=Path, help="Write exclusive JSON validation report")
    args = parser.parse_args()
    try:
        if args.config is None and (args.backend or args.check):
            raise DesktopError("此模式必须明确提供 --config，不自动创建配置")
        config = args.config or prepare_default_config()
        if args.backend:
            from .cli import serve
            return serve(config, "127.0.0.1", args.port, False)
        result = validate_desktop(config)
        if args.check:
            if args.report:
                with args.report.open("x", encoding="utf-8") as output:
                    json.dump(result, output)
            elif sys.stdout is not None:
                print(json.dumps(result))
            return 0
        if os.name != "nt":
            raise DesktopError("当前独立窗口仅支持 Windows；其他系统请使用网页入口")
        return run_window(config, args.port)
    except Exception as exc:
        # Never dump arbitrary exception text, tokens or local paths into logs.
        message = str(exc) if isinstance(exc, DesktopError) else f"启动未完成（{type(exc).__name__}）"
        if args.backend or args.check:
            if sys.stderr is not None:
                print(message, file=sys.stderr)
        elif os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, message, "TangerinePhotoAssistant", 0x10)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
