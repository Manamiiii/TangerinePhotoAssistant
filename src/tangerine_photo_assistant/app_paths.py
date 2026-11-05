from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path


def resource_root() -> Path:
    """Read-only bundled resources or the source checkout; never user data."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parents[2]


def user_app_directory() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / ".local" / "share")))
    return base / "Tangerine" / "Data" / "TangerinePhotoAssistant"


class DataLocationError(RuntimeError):
    """Ambiguous data must be resolved explicitly, never by creating an empty library."""


def legacy_app_directory() -> Path:
    return user_app_directory().parents[2] / "TangerinePhotoAssistant"


def default_config_path() -> Path:
    current = user_app_directory() / "Config" / "config.toml"
    legacy = legacy_app_directory() / "config.toml"
    if current.exists() and legacy.exists():
        raise DataLocationError("发现新旧两份默认配置；请用 --config 明确选择，未移动或覆盖任何资料。")
    if legacy.exists():
        return legacy
    # Old data without its config may be an interrupted restore; don't hide it.
    for name in ("Workspace", "PhotoInbox", "Cache"):
        if (legacy.parent / name).exists():
            raise DataLocationError("旧数据目录存在但配置缺失；请恢复原配置或明确使用 --config，未创建替代库。")
    return current


def config_identity(config_path: Path) -> str:
    value = os.path.normcase(str(config_path.resolve()))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def service_runtime_directory(config_path: Path, port: int) -> Path:
    key = f"{config_identity(config_path)}-{port}"
    legacy = legacy_app_directory() / "Runtime" / key
    current = user_app_directory() / "Runtime" / key
    # A lock-only directory is the cross-version backend guard, not old data.
    old_data = legacy.exists() and (not legacy.is_dir() or any(
        item.name != "backend.lock" for item in legacy.iterdir()))
    if old_data and current.exists():
        raise DataLocationError("此配置的新旧运行目录同时存在；请先核对服务与运行记录，未选择或清理任何一份。")
    # Keep the original lease/token/profile namespace for existing configurations.
    # Moving it would allow an older binary to acquire a different backend lock.
    return legacy if old_data else current


def service_logs_directory(config_path: Path, port: int) -> Path:
    runtime = service_runtime_directory(config_path, port)
    if runtime.parent.parent == legacy_app_directory():
        return runtime
    return user_app_directory() / "Logs" / runtime.name


def webview_directory(config_path: Path, port: int) -> Path:
    runtime = service_runtime_directory(config_path, port)
    if runtime.parent.parent == legacy_app_directory():
        return runtime / "WebView2"
    return user_app_directory() / "Storage" / "WebView2" / runtime.name
