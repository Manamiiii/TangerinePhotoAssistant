"""OS-released local leases: crashes never leave an authoritative stale PID lock."""
from __future__ import annotations

import os
from pathlib import Path


class LeaseBusy(RuntimeError):
    pass


class FileLease:
    def __init__(self, path: Path):
        self.path = path
        self.file = None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("a+b")
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            self.file.close()
            self.file = None
            raise LeaseBusy("本应用已有实例正在处理此操作") from exc
        return self

    def __exit__(self, *_):
        if self.file is not None:
            self.file.close()
            self.file = None
