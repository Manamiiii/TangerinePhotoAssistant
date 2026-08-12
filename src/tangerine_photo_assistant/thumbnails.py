from __future__ import annotations

import os
import sqlite3
from hashlib import sha1
from pathlib import Path
from threading import Lock
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .database import connect_readonly
from .settings import Settings

ALLOWED_EDGES = (320, 640, 1280)


class ThumbnailCache:
    """Bounded, disposable JPEG cache. Source photos are opened read-only."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.root = (settings.cache_root / "thumbnails").resolve()
        self.max_bytes = settings.thumbnail_max_size_gb * 1024**3
        self._lock = Lock()
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
        source = Path(row["path"]).resolve()
        originals = self.settings.originals.resolve()
        if not source.is_file() or not source.is_relative_to(originals):
            raise FileNotFoundError("缩略图源文件不在当前原片库中")
        key = sha1(
            f"v1|{row['file_id']}|{row['size_bytes']}|{row['modified_ns']}|{max_edge}".encode()
        ).hexdigest()
        target = (self.root / str(max_edge) / key[:2] / f"{key}.jpg").resolve()
        if not target.is_relative_to(self.root):
            raise RuntimeError("Invalid thumbnail cache path")
        if target.is_file():
            os.utime(target, None)
            return target

        with self._lock:
            if target.is_file():
                os.utime(target, None)
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            try:
                with Image.open(source) as opened:
                    opened.draft("RGB", (max_edge, max_edge))
                    image = ImageOps.exif_transpose(opened).convert("RGB")
                    image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                    image.save(temporary, format="JPEG", quality=86, optimize=True)
                temporary.replace(target)
            except (OSError, UnidentifiedImageError, ValueError):
                if temporary.is_file() and temporary.is_relative_to(self.root):
                    temporary.unlink(missing_ok=True)
                raise
            self._created_since_prune += 1
            if self._created_since_prune >= 100:
                self.prune()
                self._created_since_prune = 0
        return target

    def prune(self) -> dict[str, int]:
        """Remove only generated thumbnails, oldest-accessed first."""
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
