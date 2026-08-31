"""Offline build identity. Git is consulted only in source checkouts, never packages."""
from __future__ import annotations

import json
import subprocess
import sys
from functools import lru_cache

from . import __version__
from .app_paths import resource_root
from .database import SCHEMA_VERSION


@lru_cache(maxsize=1)
def build_info() -> dict:
    if getattr(sys, "frozen", False):
        try:
            data = json.loads((resource_root() / "build-info.json").read_text(encoding="utf-8"))
            return {key: data[key] for key in ("version", "revision", "dirty", "built_at", "schema_version")}
        except (OSError, ValueError, KeyError):
            return {"version": __version__, "revision": "unknown", "schema_version": SCHEMA_VERSION}
    info = {"version": __version__, "revision": "unknown", "schema_version": SCHEMA_VERSION}
    try:
        options = {"cwd": resource_root(), "capture_output": True, "text": True, "encoding": "utf-8", "errors": "replace", "timeout": 3,
                   "creationflags": subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0}
        revision = subprocess.run(["git", "rev-parse", "HEAD"], check=False, **options)
        status = subprocess.run(["git", "status", "--porcelain"], check=False, **options)
        if revision.returncode == 0 and status.returncode == 0:
            info.update(revision=revision.stdout.strip(), dirty=bool(status.stdout.strip()))
    except (OSError, subprocess.SubprocessError):
        pass
    return info


def version_summary(local: dict, remote: dict | None) -> str:
    def label(value):
        return f"{value.get('version', '?')} · {str(value.get('revision', 'unknown'))[:12]}" + (
            "（含未提交改动）" if value.get("dirty") else "")
    lines = ["窗口程序：" + label(local)]
    if remote and remote.get("build"):
        active = remote["build"]
        lines.append("后台服务：" + label(active))
        if any(local.get(key) != active.get(key) for key in ("revision", "dirty", "built_at")):
            lines.append("程序与服务构建不同；保存编辑并确认任务空闲后正常重启。")
    else:
        lines.append("后台服务：旧版或暂不可用，无法比较构建版本。")
    lines.append("不自动联网或下载。检查本地安装包后，运行其中的 Install.cmd 安装。")
    return "\n\n".join(lines)
