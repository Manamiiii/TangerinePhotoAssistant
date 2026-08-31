from __future__ import annotations

import os
import sqlite3
import stat
from collections.abc import Iterator
from hashlib import sha1
from pathlib import Path
from threading import BoundedSemaphore, Lock
from time import monotonic, time_ns
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .database import connect_readonly
from .settings import Settings

ALLOWED_EDGES = (320, 640, 1280)


class ThumbnailCacheUnavailable(OSError):
    """Stop cache growth if repeated maintenance failures prevent reclamation."""


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
        self._state_lock = Lock()
        self._created_since_prune = 100
        self._next_prune_at = 0.0
        self._maintenance_failed = False

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

    def _target(self, row: sqlite3.Row, max_edge: int) -> Path:
        key = sha1(
            f"v1|{row['file_id']}|{row['size_bytes']}|{row['modified_ns']}|{max_edge}".encode()
        ).hexdigest()
        target = (self.root / str(max_edge) / key[:2] / f"{key}.jpg").resolve()
        if not target.is_relative_to(self.root):
            raise RuntimeError("Invalid thumbnail cache path")
        return target

    def get(self, capture_id: int, max_edge: int) -> Path:
        if max_edge not in ALLOWED_EDGES:
            raise ValueError(f"Thumbnail edge must be one of {ALLOWED_EDGES}")
        row = self._source(capture_id)
        source = _resolved_path(Path(row["path"]))
        originals = _resolved_path(self.settings.originals)
        if not source.is_file() or not source.is_relative_to(originals):
            raise FileNotFoundError("缩略图源文件不在当前原片库中")
        target = self._target(row, max_edge)
        if self._touch(target):
            return target

        with self._state_lock:
            blocked = self._maintenance_failed and self._created_since_prune >= 200
        if blocked:
            # Only the exceptional recovery path can retry maintenance before
            # rendering. Existing cache hits still work during a cleanup fault.
            self.prune_if_due()
            with self._state_lock:
                if self._maintenance_failed:
                    raise ThumbnailCacheUnavailable("缓存维护失败，已暂停生成新缩略图；请稍后重试")

        with self._key_locks[int(target.stem[:8], 16) % len(self._key_locks)]:
            if self._touch(target):
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
            try:
                with self._generation_slots:
                    with self._state_lock:
                        if self._maintenance_failed and self._created_since_prune >= 200:
                            raise ThumbnailCacheUnavailable("缓存维护失败，已暂停生成新缩略图；请稍后重试")
                    self._render_best_source(row, source, temporary, max_edge)
                    temporary.replace(target)
                    with self._state_lock:
                        self._created_since_prune += 1
            except (OSError, UnidentifiedImageError, ValueError):
                if temporary.is_file() and temporary.is_relative_to(self.root):
                    temporary.unlink(missing_ok=True)
                raise
        return target

    def _render_best_source(self, row: sqlite3.Row, source: Path,
                            temporary: Path, max_edge: int) -> None:
        # Only downsample an existing cache entry for this exact source revision.
        # Cached images already have EXIF orientation applied. Never upscale.
        for edge in ALLOWED_EDGES:
            if edge <= max_edge:
                continue
            cached = self._target(row, edge)
            if not self._touch(cached):
                continue
            try:
                self._render(cached, temporary, max_edge)
                return
            except (OSError, ValueError):
                # A corrupt/evicted derivative must not make the original unusable.
                temporary.unlink(missing_ok=True)
        self._render(source, temporary, max_edge)

    def prune_if_due(self) -> None:
        """Post-response maintenance; never enqueue or wait for another sweep."""
        with self._state_lock:
            if self._created_since_prune < 100 or monotonic() < self._next_prune_at:
                return
        if not self._maintenance_lock.acquire(blocking=False):
            return
        try:
            with self._state_lock:
                if self._created_since_prune < 100 or monotonic() < self._next_prune_at:
                    return
                created = self._created_since_prune
            try:
                result = self._prune()
            except OSError:
                # Maintenance failure must not turn a delivered image into an
                # application failure; retry after a bounded cooldown.
                with self._state_lock:
                    self._next_prune_at = monotonic() + 30
                    self._maintenance_failed = True
                return
            with self._state_lock:
                self._maintenance_failed = False
                self._created_since_prune -= created
                if result["bytes_remaining"] > self.max_bytes:
                    self._created_since_prune = max(100, self._created_since_prune)
                self._next_prune_at = monotonic() + 30
        finally:
            self._maintenance_lock.release()

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
        sizes = list(self._cache_entries())
        total = sum(size for _, size, _ in sizes)
        if total <= self.max_bytes:
            return {"files_removed": 0, "bytes_removed": 0, "bytes_remaining": total}
        target_size = int(self.max_bytes * 0.90)
        removed = 0
        removed_bytes = 0
        # Protect recently served derivatives while another response may still
        # be streaming. The cache size target can temporarily exceed its limit
        # by this bounded recent-use window; a later request retries maintenance.
        cutoff = time_ns() - 30 * 1_000_000_000
        for path, size, modified in sorted(sizes, key=lambda item: item[2]):
            if total - removed_bytes <= target_size:
                break
            if modified >= cutoff:
                continue
            try:
                resolved = _resolved_path(path)
                if not resolved.is_relative_to(self.root) or resolved.stat().st_mtime_ns >= cutoff:
                    continue
                resolved.unlink(missing_ok=True)
                removed += 1
                removed_bytes += size
            except FileNotFoundError:
                continue
        return {
            "files_removed": removed,
            "bytes_removed": removed_bytes,
            "bytes_remaining": total - removed_bytes,
        }

    def _cache_entries(self) -> Iterator[tuple[Path, int, int]]:
        # The cache has a fixed size/hash-prefix/file layout. Resolve directories
        # once, reuse scandir metadata, and never follow directory/file links.
        for edge in ALLOWED_EDGES:
            directory = self.root / str(edge)
            if not directory.is_dir() or directory.is_symlink() or directory.is_junction():
                continue
            if not _resolved_path(directory).is_relative_to(self.root):
                continue
            with os.scandir(directory) as buckets:
                for bucket in buckets:
                    if len(bucket.name) != 2 or any(char not in "0123456789abcdef" for char in bucket.name):
                        continue
                    if not bucket.is_dir(follow_symlinks=False):
                        continue
                    folder = Path(bucket.path)
                    if folder.is_junction() or not _resolved_path(folder).is_relative_to(self.root):
                        continue
                    with os.scandir(folder) as files:
                        for item in files:
                            stem = item.name[:-4]
                            if (not item.name.endswith(".jpg") or len(stem) != 40
                                    or not stem.startswith(bucket.name)
                                    or any(char not in "0123456789abcdef" for char in stem)):
                                continue
                            try:
                                info = item.stat(follow_symlinks=False)
                            except FileNotFoundError:
                                continue
                            if stat.S_ISREG(info.st_mode):
                                yield Path(item.path), info.st_size, info.st_mtime_ns

    def summary(self) -> dict[str, int]:
        entries = list(self._cache_entries())
        return {
            "file_count": len(entries),
            "size_bytes": sum(size for _, size, _ in entries),
            "max_size_bytes": self.max_bytes,
        }
