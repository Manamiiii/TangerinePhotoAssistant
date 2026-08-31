from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path
from threading import Event, Lock

from .app_paths import resource_root
from .build_info import build_info, version_summary
from .desktop import DesktopError, ServiceClient


class DesktopWindow:
    """Native menu callbacks only. No Python API is exposed to webpage JavaScript."""
    def __init__(self, client: ServiceClient):
        self.client = client
        self.window = None
        self.cancelled = Event()
        self.operation = Lock()
        self.last_message = ""

    @staticmethod
    def splash(message: str = "正在连接你的本地照片库…") -> str:
        return """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
        <style>body{margin:0;background:#faf7f1;color:#332c25;font:16px 'Segoe UI',sans-serif;
        display:grid;place-items:center;height:100vh}main{max-width:640px;padding:40px}
        b{display:inline-grid;place-items:center;width:56px;height:56px;background:#f58a36;
        border-radius:16px;font-size:32px}h1{font-size:28px}p{line-height:1.7;color:#71665b}
        small{color:#92877b}</style><main><b>T</b><h1>TangerinePhotoAssistant</h1><p>""" + html.escape(message) + """</p>
        <small>照片保留在本机。可从顶部“应用”菜单重新连接或打开浏览器。</small></main></html>"""

    def progress(self, message: str) -> None:
        if not self.cancelled.is_set() and message != self.last_message:
            self.last_message = message
            self.window.load_html(self.splash(message))

    def connect(self) -> None:
        if not self.operation.acquire(blocking=False):
            return
        try:
            self.client.ensure_running(self.progress, self.cancelled)
            if not self.cancelled.is_set():
                self.window.load_url(self.client.url)
        except Exception as exc:
            self.progress(str(exc) if isinstance(exc, DesktopError) else f"连接未完成（{type(exc).__name__}）")
        finally:
            self.operation.release()

    def restart(self) -> None:
        if not self.operation.acquire(blocking=False):
            return
        try:
            if not self.window.create_confirmation_dialog(
                "安全重启服务", "确认已保存页面中的编辑？只在后台任务空闲时重启，照片和已有数据不会移动或删除。"
            ):
                return
            self.client.restart(self.progress, self.cancelled)
            if not self.cancelled.is_set():
                self.window.load_url(self.client.url)
        except Exception as exc:
            # Keep the existing page intact when a busy/legacy service refuses.
            message = str(exc) if isinstance(exc, DesktopError) else f"重启未完成（{type(exc).__name__}）"
            self.window.create_confirmation_dialog("未执行强制停止", message)
        finally:
            self.operation.release()

    def open_logs(self) -> None:
        self.client.runtime.mkdir(parents=True, exist_ok=True)
        os.startfile(self.client.runtime)

    def open_program(self) -> None:
        os.startfile(Path(sys.executable).parent if getattr(sys, "frozen", False) else resource_root())

    def information(self, title: str, message: str) -> None:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)

    def about(self) -> None:
        try:
            health = self.client.health()
        except Exception:
            health = None
        self.information("版本与更新", version_summary(build_info(), health))

    def inspect_package(self) -> None:
        import webview
        chosen = self.window.create_file_dialog(webview.FileDialog.FOLDER)
        if not chosen:
            return
        try:
            path = Path(chosen[0]) / "package-manifest.json"
            if path.stat().st_size > 4 * 1024 * 1024:
                raise ValueError("oversized manifest")
            candidate = json.loads(path.read_text(encoding="utf-8-sig"))
            if not isinstance(candidate, dict) or candidate.get("app_id") != "tangerine-photo-assistant" or candidate.get("format") != 1:
                raise ValueError("unknown package")
            message = version_summary(build_info(), {"build": candidate}).replace("后台服务：", "所选安装包：")
            message = message.replace("程序与服务构建不同；保存编辑并确认任务空闲后正常重启。", "所选安装包与当前程序构建不同；安装后需正常重新启动。")
            message += "\n\n此处只比较版本，不判断提交先后或验证发布者。安装时会逐文件校验；仅使用可信来源。"
        except (OSError, ValueError, TypeError):
            message = "未找到有效的安装包清单。请选择新版本 ZIP 解压后的程序目录。"
        self.information("本地安装包", message)

    def stop(self) -> None:
        if not self.operation.acquire(blocking=False):
            return
        try:
            if not self.window.create_confirmation_dialog("安全停止服务", "已保存编辑？仅在任务空闲时停止后台。其他浏览器页面也会断开；照片和数据库不会删除。"):
                return
            self.client.stop(self.progress, self.cancelled)
            self.progress("服务已安全停止。可关闭窗口进行程序维护，或选择“重新连接”再次启动。")
        except Exception as exc:
            self.information("未强制停止", str(exc) if isinstance(exc, DesktopError) else "停止未完成，请检查日志。")
        finally:
            self.operation.release()

    def close(self) -> None:
        self.window.destroy()

    def watch_focus(self) -> None:
        previous = 0
        marker = self.client.runtime / "focus.request"
        while not self.cancelled.wait(0.5):
            try:
                current = marker.stat().st_mtime_ns
                if current != previous:
                    previous = current
                    self.window.restore()
                    self.window.show()
            except (OSError, RuntimeError):
                pass
