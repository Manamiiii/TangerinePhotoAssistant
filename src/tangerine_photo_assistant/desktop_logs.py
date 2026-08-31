"""Bounded desktop logs, scoped to one configuration/port under the backend lease."""
from __future__ import annotations

import io
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

MAX_BYTES = 2 * 1024 * 1024
BACKUPS = 4


class PrivateFormatter(logging.Formatter):
    def format(self, record):
        # No URLs, arguments, absolute paths or traceback bodies in persisted logs.
        category = record.exc_info[0].__name__ if record.exc_info else "event"
        event = {"Started server process [%d]": "server_started", "Shutting down": "shutdown_started",
                 "Waiting for application startup.": "startup_wait", "Application startup complete.": "startup_complete",
                 "Waiting for application shutdown.": "shutdown_wait", "Application shutdown complete.": "shutdown_complete",
                 "Finished server process [%d]": "server_finished", "startup failed": "startup_failed"}.get(str(record.msg), "event")
        return f"{self.formatTime(record)} {record.levelname} {record.name} {event} {category}"


class LogStream(io.TextIOBase):
    def __init__(self, handler):
        self.handler = handler

    def write(self, text):
        if text.strip():
            self.handler.handle(logging.LogRecord("desktop.stdout", logging.INFO, "", 0,
                                                  "output", (), None))
        return len(text)

    def flush(self):
        self.handler.flush()


def bounded_handler(directory: Path, *, max_bytes=MAX_BYTES, backups=BACKUPS):
    directory.mkdir(parents=True, exist_ok=True)
    # Do not follow a replaced log or a rollover target outside this runtime.
    for path in [directory / "service.log", *[directory / f"service.log.{n}" for n in range(1, backups + 1)]]:
        if path.is_symlink() or (path.exists() and (path.resolve().parent != directory.resolve() or path.stat().st_nlink > 1)):
            raise ValueError("Unsafe desktop log path")
    handler = RotatingFileHandler(directory / "service.log", maxBytes=max_bytes,
                                  backupCount=backups, encoding="utf-8")
    handler.setFormatter(PrivateFormatter())
    return handler
