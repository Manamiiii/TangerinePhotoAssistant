"""Authenticated, graceful local service control. No process killing or shell execution."""
from __future__ import annotations

import json
import logging
import os
import secrets
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

from . import __version__
from .app_paths import config_identity, resource_root, service_runtime_directory
from .build_info import build_info
from .desktop_lock import FileLease
from .desktop_logs import LogStream, bounded_handler

APP_ID = "tangerine-photo-assistant"
CONTROL_HEADER = "X-Tangerine-Desktop-Control"
TERMINAL_TASK_STATES = frozenset({"idle", "complete", "completed", "failed", "cancelled"})


@dataclass
class ServiceControl:
    config_path: Path
    port: int
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    instance_id: str = field(default_factory=lambda: uuid4().hex)
    draining: bool = False
    shutdown: Callable[[], None] = field(default=lambda: None, repr=False)

    def public_identity(self) -> dict[str, object]:
        return {"app_id": APP_ID, "app_version": __version__,
                "config_identity": config_identity(self.config_path),
                "instance_id": self.instance_id, "desktop_control": True,
                "draining": self.draining, "build": build_info()}

    def authorize(self, token: str) -> bool:
        return bool(token) and secrets.compare_digest(token, self.token)


def run_service(config_path: Path, host: str, port: int, open_browser: bool = False) -> int:
    directory = service_runtime_directory(config_path, port)
    with FileLease(directory / "backend.lock"):
        handler = bounded_handler(directory)
        loggers = [logging.getLogger(name) for name in ("uvicorn", "uvicorn.error", "uvicorn.access")]
        previous = [(logger.handlers[:], logger.level, logger.propagate) for logger in loggers]
        streams = (sys.stdout, sys.stderr)
        try:
            for logger in loggers:
                logger.handlers, logger.propagate = [handler], False
                logger.setLevel(logging.INFO)
            if sys.stdout is None:
                sys.stdout = LogStream(handler)
            if sys.stderr is None:
                sys.stderr = LogStream(handler)
            return _run_service(config_path, host, port, open_browser, directory)
        except Exception:
            loggers[0].exception("startup failed")
            raise
        finally:
            sys.stdout, sys.stderr = streams
            for logger, (handlers, level, propagate) in zip(loggers, previous, strict=True):
                logger.handlers, logger.propagate = handlers, propagate
                logger.setLevel(level)
            handler.close()


def _run_service(config_path: Path, host: str, port: int, open_browser: bool, directory: Path) -> int:
    import webbrowser
    from threading import Timer

    import uvicorn

    from .webapp import create_app

    control = ServiceControl(config_path.resolve(), port)
    directory.mkdir(parents=True, exist_ok=True)
    record = directory / "service.json"
    temporary = directory / f".{control.instance_id}.pending"
    # The token never enters health responses, command-line arguments or logs.
    with temporary.open("x", encoding="utf-8") as output:
        os.chmod(temporary, 0o600)
        json.dump({**control.public_identity(), "pid": os.getpid(), "token": control.token}, output)
    temporary.replace(record)
    timer = None
    try:
        app = create_app(control.config_path, resource_root() / "web" / "dist", control)
        if open_browser:
            timer = Timer(0.8, lambda: webbrowser.open(f"http://{host}:{port}"))
            timer.start()
        server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="info",
                                             log_config=None, access_log=False))
        control.shutdown = lambda: setattr(server, "should_exit", True)
        server.run()
        return 0
    finally:
        if timer is not None:
            timer.cancel()
        try:
            if json.loads(record.read_text(encoding="utf-8")).get("instance_id") == control.instance_id:
                record.unlink()
        except (OSError, ValueError):
            pass
