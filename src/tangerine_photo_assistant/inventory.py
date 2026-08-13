from __future__ import annotations

import os
import sqlite3
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .database import transaction
from .metadata import METADATA_PROFILE_VERSION, MetadataReader, database_fields
from .settings import Settings

JPEG_EXTENSIONS = frozenset({".jpg", ".jpeg"})
IMAGE_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".heic",
        ".heif",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".webp",
        ".psd",
    }
)
VIDEO_EXTENSIONS = frozenset(
    {".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".3gp", ".wmv", ".webm"}
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def media_kind(extension: str, raw_extensions: tuple[str, ...]) -> str:
    if extension in raw_extensions:
        return "raw"
    if extension in IMAGE_EXTENSIONS:
        return "image"
    if extension in VIDEO_EXTENSIONS:
        return "video"
    return "other"


def iter_files(
    root: Path, on_error: Callable[[Path, OSError], None]
) -> Iterator[tuple[Path, os.stat_result]]:
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    path = Path(entry.path)
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            pending.append(path)
                        elif entry.is_file(follow_symlinks=False):
                            yield path, entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        on_error(path, exc)
        except OSError as exc:
            on_error(directory, exc)


def start_scan(connection: sqlite3.Connection, root: Path) -> int:
    cursor = connection.execute(
        "INSERT INTO scan_runs(started_at, root_path, status) VALUES (?, ?, 'running')",
        (utc_now(), str(root)),
    )
    connection.commit()
    return int(cursor.lastrowid)


def scan_library(
    connection: sqlite3.Connection,
    settings: Settings,
    metadata_reader: MetadataReader | None = None,
    progress: Callable[[int], None] | None = None,
) -> int:
    errors = settings.validate()
    if errors:
        raise ValueError("; ".join(errors))

    root = settings.originals.resolve()
    run_id = start_scan(connection, root)
    files_seen = 0

    def record_error(path: Path, error: OSError) -> None:
        connection.execute(
            """
            INSERT INTO scan_errors(scan_run_id, path, error_type, message)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, str(path), type(error).__name__, str(error)),
        )

    try:
        with transaction(connection):
            for path, stat in iter_files(root, record_error):
                relative = path.relative_to(root)
                extension = path.suffix.lower()
                kind = media_kind(extension, settings.raw_extensions)
                metadata_status = "not_applicable" if kind == "other" else "pending"
                connection.execute(
                    """
                    INSERT INTO files(
                        path, relative_path, parent_relative, file_name, stem, extension,
                        media_kind, size_bytes, modified_ns, first_seen_run_id, last_seen_run_id,
                        present, metadata_status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
                    ON CONFLICT(path) DO UPDATE SET
                        relative_path = excluded.relative_path,
                        parent_relative = excluded.parent_relative,
                        file_name = excluded.file_name,
                        stem = excluded.stem,
                        extension = excluded.extension,
                        media_kind = excluded.media_kind,
                        metadata_status = CASE
                            WHEN excluded.media_kind = 'other' THEN 'not_applicable'
                            WHEN files.size_bytes != excluded.size_bytes
                              OR files.modified_ns != excluded.modified_ns
                            THEN 'pending' ELSE files.metadata_status END,
                        metadata_error = CASE
                            WHEN files.size_bytes != excluded.size_bytes
                              OR files.modified_ns != excluded.modified_ns
                            THEN NULL ELSE files.metadata_error END,
                        size_bytes = excluded.size_bytes,
                        modified_ns = excluded.modified_ns,
                        last_seen_run_id = excluded.last_seen_run_id,
                        present = 1
                    """,
                    (
                        str(path),
                        str(relative),
                        str(relative.parent) if relative.parent != Path(".") else "",
                        path.name,
                        path.stem,
                        extension,
                        kind,
                        stat.st_size,
                        stat.st_mtime_ns,
                        run_id,
                        run_id,
                        metadata_status,
                    ),
                )
                files_seen += 1
                if progress and files_seen % 1000 == 0:
                    progress(files_seen)

            connection.execute(
                "UPDATE files SET present = 0 WHERE last_seen_run_id != ? AND present = 1",
                (run_id,),
            )

        if metadata_reader is not None:
            enrich_metadata(connection, settings, metadata_reader)

        connection.execute(
            """
            UPDATE scan_runs
            SET finished_at = ?, status = 'complete', files_seen = ?
            WHERE id = ?
            """,
            (utc_now(), files_seen, run_id),
        )
        connection.commit()
    except Exception as exc:
        connection.rollback()
        connection.execute(
            """
            UPDATE scan_runs
            SET finished_at = ?, status = 'failed', files_seen = ?, error_message = ?
            WHERE id = ?
            """,
            (utc_now(), files_seen, str(exc), run_id),
        )
        connection.commit()
        raise
    return run_id


def enrich_metadata(
    connection: sqlite3.Connection,
    settings: Settings,
    reader: MetadataReader,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    rows = connection.execute(
        """
        SELECT id, path FROM files
        WHERE present = 1 AND metadata_status = 'pending'
          AND media_kind IN ('raw', 'image', 'video')
        ORDER BY id
        """
    ).fetchall()
    path_to_id = {str(Path(row["path"]).resolve()).casefold(): row["id"] for row in rows}
    updated = 0
    total = len(rows)
    for result in reader.read(Path(row["path"]) for row in rows):
        file_id = path_to_id.get(str(result.path.resolve()).casefold())
        if file_id is None:
            continue
        if result.values is None:
            connection.execute(
                "UPDATE files SET metadata_status = 'error', metadata_error = ? WHERE id = ?",
                (result.error or "Unknown metadata error", file_id),
            )
        else:
            values: dict[str, Any] = database_fields(result.values)
            connection.execute(
                """
                UPDATE files SET
                    metadata_status = 'complete', metadata_error = NULL,
                    exif_json = :exif_json, captured_at = :captured_at,
                    camera_make = :camera_make, camera_model = :camera_model,
                    lens_model = :lens_model, exposure_time = :exposure_time,
                    f_number = :f_number, iso = :iso,
                    focal_length_mm = :focal_length_mm,
                    focal_length_35mm = :focal_length_35mm,
                    exposure_compensation = :exposure_compensation,
                    width = :width, height = :height,
                    gps_latitude = :gps_latitude, gps_longitude = :gps_longitude,
                    metadata_profile_version = :metadata_profile_version,
                    metadata_refreshed_at = :metadata_refreshed_at
                WHERE id = :file_id
                """,
                {
                    **values, "file_id": file_id,
                    "metadata_profile_version": int(getattr(reader, "profile_version", 0)),
                    "metadata_refreshed_at": utc_now(),
                },
            )
        updated += 1
        if progress and (updated % 100 == 0 or updated == total):
            progress(updated, total)
        if updated % 250 == 0:
            connection.commit()
    connection.commit()
    return updated


def refresh_metadata_profile(
    connection: sqlite3.Connection,
    reader: MetadataReader,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, int]:
    """Read the current safe metadata profile without modifying source files."""
    rows = connection.execute(
        """
        SELECT f.id, f.path FROM files f
        JOIN capture_files cf ON cf.file_id=f.id
        WHERE f.present = 1 AND COALESCE(f.metadata_profile_version, 0) < ?
          AND (
            cf.role='jpeg' OR (
              cf.role='raw' AND NOT EXISTS (
                SELECT 1 FROM capture_files jpeg_cf
                JOIN files jpeg_f ON jpeg_f.id=jpeg_cf.file_id
                WHERE jpeg_cf.capture_id=cf.capture_id AND jpeg_cf.role='jpeg'
                  AND jpeg_f.present=1
              )
            )
          )
        ORDER BY f.id
        """,
        (METADATA_PROFILE_VERSION,),
    ).fetchall()
    path_to_id = {str(Path(row["path"]).resolve()).casefold(): row["id"] for row in rows}
    updated = 0
    errors = 0
    total = len(rows)
    for result in reader.read(Path(row["path"]) for row in rows):
        file_id = path_to_id.get(str(result.path.resolve()).casefold())
        if file_id is None:
            continue
        if result.values is None:
            errors += 1
            connection.execute(
                "UPDATE files SET metadata_error=? WHERE id=?",
                (result.error or "Unknown metadata error", file_id),
            )
        else:
            values: dict[str, Any] = database_fields(result.values)
            connection.execute(
                """
                UPDATE files SET
                    metadata_status='complete', metadata_error=NULL,
                    exif_json=:exif_json, captured_at=:captured_at,
                    camera_make=:camera_make, camera_model=:camera_model,
                    lens_model=:lens_model, exposure_time=:exposure_time,
                    f_number=:f_number, iso=:iso,
                    focal_length_mm=:focal_length_mm,
                    focal_length_35mm=:focal_length_35mm,
                    exposure_compensation=:exposure_compensation,
                    width=:width, height=:height,
                    gps_latitude=:gps_latitude, gps_longitude=:gps_longitude,
                    metadata_profile_version=:metadata_profile_version,
                    metadata_refreshed_at=:metadata_refreshed_at
                WHERE id=:file_id
                """,
                {
                    **values, "file_id": file_id,
                    "metadata_profile_version": METADATA_PROFILE_VERSION,
                    "metadata_refreshed_at": utc_now(),
                },
            )
            updated += 1
        processed = updated + errors
        if processed % 100 == 0 or processed == total:
            connection.commit()
            if progress:
                progress(processed, total)
    connection.commit()
    return {
        "metadata_updated": updated,
        "metadata_errors": errors,
        "metadata_total": total,
    }
