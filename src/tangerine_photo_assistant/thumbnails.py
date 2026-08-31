from __future__ import annotations

import os
import sqlite3
from hashlib import sha1
from pathlib import Path
from threading import BoundedSemaphore, Lock
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .database import connect_readonly
from .settings import Settings

ALLOWED_EDGES = (320, 640, 1280)


def _resolved_path(path: Path) -> Path:
    resolved = path.resolve()
    # Windows realpath may keep the extended prefix when a file is created
    # between its existence checks. Always use that representation on Windows,
    # including UNC paths, so containment compares canonical paths consistently.
    # Do not strip prefixes or skip symlink resolution/boundary checks.
    if os.name == "nt":
        value = str(resolved)
        if not value.startswith("\\\\?\\"):
            value = "\\\\?\\UNC\\" + value[2:] if value.startswith("\\\\") else "\\\\?\\" + value
        return Path(value)
    return resolved


class ThumbnailCache:
    """Bounded, disposable JPEG cache. Source photos are opened read-only."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = _resolved_path(settings.cache_root / "thumbnails")
        self.max_bytes = settings.thumbnail_max_size_gb * 1024**3
        # Decode a small number of different photos concurrently, without spawning
        # a worker for every image in a large page. Striped locks bound bookkeeping
        # and coalesce concurrent requests for the same cached size/source.
        self._generation_slots = BoundedSemaphore(2)
        self._key_locks = [Lock() for _ in range(64)]
        self._maintenance_lock = Lock()
        self._created_since_prune = 100

    def _source(self, capture_id: int) -> sqlite3.Row:
        connection = connect_readonly(self.settings.database_path)
        try:
            row = connection.execute(
                """
                SELECT f.id AS file_id, f.path, f.size_bytes, f.modified_ns
                FROM capture_files cf
                JOIN files f ON f.id = cf.file_id
                WHERE cf.capture_id = ? AND cf.role = 'jpeg' AND f.present = 1
                ORDER BY f.id LIMIT 1
                """,
                (capture_id,),
            ).fetchone()
            if row is None:
                raise FileNotFoundError("该拍摄单元没有可用的 JPG")
            return row
        finally:
            connection.close()

    def get(self, capture_id: int, max_edge: int) -> Path:
        if max_edge not in ALLOWED_EDGES:
            raise ValueError(f"Thumbnail edge must be one of {ALLOWED_EDGES}")
        row = self._source(capture_id)
        source = _resolved_path(Path(row["path"]))
        originals = _resolved_path(self.settings.originals)
        if not source.is_file() or not source.is_relative_to(originals):
            raise FileNotFoundError("缩略图源文件不在当前原片库中")
        key = sha1(
            f"v1|{row['file_id']}|{row['size_bytes']}|{row['modified_ns']}|{max_edge}".encode()
        ).hexdigest()
        target = (self.root / str(max_edge) / key[:2] / f"{key}.jpg").resolve()
        if not target.is_relative_to(self.root):
            raise RuntimeError("Invalid thumbnail cache path")
        if self._touch(target):
            return target

        with self._key_locks[int(key[:8], 16) % len(self._key_locks)]:
            if self._touch(target):
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            try:
                with self._generation_slots:
                    self._render(source, temporary, max_edge)
                    with self._maintenance_lock:
                        # Prune before publication so this request's new thumbnail
                        # cannot be removed by its own capacity check.
                        self._created_since_prune += 1
                        if self._created_since_prune >= 100:
                            self._prune()
                            self._created_since_prune = 0
                        temporary.replace(target)
            except (OSError, UnidentifiedImageError, ValueError):
                if temporary.is_file() and temporary.is_relative_to(self.root):
                    temporary.unlink(missing_ok=True)
                raise
        return target

    @staticmethod
    def _touch(target: Path) -> bool:
        try:
            os.utime(target, None)
            return True
        except FileNotFoundError:
            return False

    @staticmethod
    def _render(source: Path, temporary: Path, max_edge: int) -> None:
        with Image.open(source) as opened:
            opened.draft("RGB", (max_edge, max_edge))
            with ImageOps.exif_transpose(opened) as oriented, oriented.convert("RGB") as image:
                image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                image.save(temporary, format="JPEG", quality=86, optimize=True)

    def prune(self) -> dict[str, int]:
        """Remove only generated thumbnails, oldest-accessed first."""
        with self._maintenance_lock:
            return self._prune()

    def _prune(self) -> dict[str, int]:
        if not self.root.is_dir():
            return {"files_removed": 0, "bytes_removed": 0, "bytes_remaining": 0}
        files = [
            path for path in self.root.rglob("*.jpg")
            if path.is_file() and path.resolve().is_relative_to(self.root)
        ]
        sizes = [(path, path.stat().st_size, path.stat().st_mtime_ns) for path in files]
        total = sum(size for _, size, _ in sizes)
        if total <= self.max_bytes:
            return {"files_removed": 0, "bytes_removed": 0, "bytes_remaining": total}
        target_size = int(self.max_bytes * 0.90)
        removed = 0
        removed_bytes = 0
        for path, size, _ in sorted(sizes, key=lambda item: item[2]):
            if total - removed_bytes <= target_size:
                break
            resolved = path.resolve()
            if resolved.is_relative_to(self.root):
                resolved.unlink(missing_ok=True)
                removed += 1
                removed_bytes += size
        return {
            "files_removed": removed,
            "bytes_removed": removed_bytes,
            "bytes_remaining": total - removed_bytes,
        }

    def summary(self) -> dict[str, int]:
        if not self.root.is_dir():
            return {"file_count": 0, "size_bytes": 0, "max_size_bytes": self.max_bytes}
        files = [path for path in self.root.rglob("*.jpg") if path.is_file()]
        return {
            "file_count": len(files),
            "size_bytes": sum(path.stat().st_size for path in files),
            "max_size_bytes": self.max_bytes,
        }
