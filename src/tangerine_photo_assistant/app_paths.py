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
    return base / "TangerinePhotoAssistant"


def config_identity(config_path: Path) -> str:
    value = os.path.normcase(str(config_path.resolve()))
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def service_runtime_directory(config_path: Path, port: int) -> Path:
    return user_app_directory() / "Runtime" / f"{config_identity(config_path)}-{port}"
