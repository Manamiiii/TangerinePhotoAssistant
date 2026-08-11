from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import base64
import json
import sqlite3
import subprocess
from typing import Callable

from PIL import Image, ImageOps, UnidentifiedImageError

from .database import transaction
from .inventory import utc_now


Progress = Callable[[str, int, int], None]


@dataclass(frozen=True)
class Fingerprint:
    dhash64: str
    mean_r: int
    mean_g: int
    mean_b: int
    width: int
    height: int


def _fingerprint_opened(opened: Image.Image) -> Fingerprint:
        opened.draft("RGB", (256, 256))
        image = ImageOps.exif_transpose(opened).convert("RGB")
        width, height = image.size
        gray = image.resize((9, 8), Image.Resampling.LANCZOS).convert("L")
        get_pixels = getattr(gray, "get_flattened_data", gray.getdata)
        pixels = list(get_pixels())
        bits = 0
        for y in range(8):
            for x in range(8):
                bits = (bits << 1) | int(pixels[y * 9 + x] > pixels[y * 9 + x + 1])
        color = image.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
        return Fingerprint(f"{bits:016x}", color[0], color[1], color[2], width, height)


def fingerprint_image(path: Path) -> Fingerprint:
    """Build a cheap, deterministic scene fingerprint without changing the source."""
    with Image.open(path) as opened:
        return _fingerprint_opened(opened)


def fingerprint_bytes(content: bytes) -> Fingerprint:
    with Image.open(BytesIO(content)) as opened:
        return _fingerprint_opened(opened)


def hamming_distance(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        while block := stream.read(4 * 1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def find_exact_duplicates(
    connection: sqlite3.Connection, progress: Progress | None = None
) -> dict[str, int]:
    """Hash conservative same-name/same-size candidates; never mutate source files."""
    rows = connection.execute(
        """
        SELECT f.id, f.path, f.file_name, f.size_bytes, f.modified_ns,
               h.digest AS cached_digest, h.size_bytes AS cached_size,
               h.modified_ns AS cached_modified
        FROM files f
        LEFT JOIN file_hashes h ON h.file_id = f.id AND h.algorithm = 'sha256'
        WHERE f.present = 1 AND (LOWER(f.file_name), f.size_bytes) IN (
            SELECT LOWER(file_name), size_bytes
            FROM files WHERE present = 1
            GROUP BY LOWER(file_name), size_bytes HAVING COUNT(*) > 1
        )
        ORDER BY LOWER(f.file_name), f.size_bytes, f.path
        """
    ).fetchall()
    hashes: dict[tuple[str, int], list[int]] = defaultdict(list)
    computed = 0
    errors = 0
    total = len(rows)
    for index, row in enumerate(rows, 1):
        digest = row["cached_digest"]
        if row["cached_size"] != row["size_bytes"] or row["cached_modified"] != row["modified_ns"]:
            digest = None
        if digest is None:
            try:
                digest = _sha256_file(Path(row["path"]))
                connection.execute(
                    """
                    INSERT INTO file_hashes(
                        file_id, algorithm, digest, size_bytes, modified_ns, computed_at
                    ) VALUES (?, 'sha256', ?, ?, ?, ?)
                    ON CONFLICT(file_id) DO UPDATE SET
                        algorithm=excluded.algorithm, digest=excluded.digest,
                        size_bytes=excluded.size_bytes, modified_ns=excluded.modified_ns,
                        computed_at=excluded.computed_at
                    """,
                    (row["id"], digest, row["size_bytes"], row["modified_ns"], utc_now()),
                )
                computed += 1
            except OSError:
                errors += 1
                continue
        hashes[(digest, row["size_bytes"])].append(row["id"])
        if progress and (index == total or index % 25 == 0):
            progress("duplicates", index, total)

    duplicate_sets = [(key, ids) for key, ids in hashes.items() if len(ids) > 1]
    connection.commit()
    with transaction(connection):
        connection.execute("DELETE FROM duplicate_group_files")
        connection.execute("DELETE FROM duplicate_groups")
        for (digest, size), file_ids in duplicate_sets:
            cursor = connection.execute(
                """
                INSERT INTO duplicate_groups(
                    group_key, algorithm, digest, file_count, total_bytes
                ) VALUES (?, 'sha256', ?, ?, ?)
                """,
                (f"sha256:{digest}:{size}", digest, len(file_ids), size * len(file_ids)),
            )
            connection.executemany(
                "INSERT INTO duplicate_group_files(group_id, file_id) VALUES (?, ?)",
                [(cursor.lastrowid, file_id) for file_id in file_ids],
            )
    return {
        "duplicate_candidates_hashed": total,
        "new_hashes": computed,
        "hash_errors": errors,
        "duplicate_groups": len(duplicate_sets),
        "duplicate_files": sum(len(ids) for _, ids in duplicate_sets),
    }


def build_visual_fingerprints(
    connection: sqlite3.Connection,
    progress: Progress | None = None,
    limit: int | None = None,
    exiftool: Path | None = None,
    metadata_batch_size: int = 64,
) -> dict[str, int]:
    params: list[int] = []
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(limit)
    rows = connection.execute(
        """
        SELECT DISTINCT c.id AS capture_id, f.id AS file_id, f.path, f.size_bytes,
               f.modified_ns, vf.source_file_id, vf.size_bytes AS cached_size,
               vf.modified_ns AS cached_modified, vf.dhash64, vf.error
        FROM captures c
        JOIN burst_captures bc ON bc.capture_id = c.id
        JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
            AND cf.file_id = (
                SELECT MIN(cf2.file_id) FROM capture_files cf2
                JOIN files f2 ON f2.id = cf2.file_id
                WHERE cf2.capture_id = c.id AND cf2.role = 'jpeg' AND f2.present = 1
            )
        JOIN files f ON f.id = cf.file_id AND f.present = 1
        LEFT JOIN visual_fingerprints vf ON vf.capture_id = c.id
        ORDER BY c.id
        """ + limit_sql,
        params,
    ).fetchall()
    extracted: dict[int, tuple[Fingerprint | None, str | None]] = {}
    stale_rows = [
        row for row in rows
        if not (
            row["source_file_id"] == row["file_id"]
            and row["cached_size"] == row["size_bytes"]
            and row["cached_modified"] == row["modified_ns"]
            and row["dhash64"] is not None
        )
    ]
    if exiftool is not None:
        batch_size = max(1, min(metadata_batch_size, 96))
        for start in range(0, len(stale_rows), batch_size):
            batch = stale_rows[start : start + batch_size]
            completed = subprocess.run(
                [str(exiftool), "-j", "-b", "-ThumbnailImage", *[row["path"] for row in batch]],
                capture_output=True,
                check=False,
            )
            try:
                records = json.loads(completed.stdout) if completed.returncode == 0 else []
            except (json.JSONDecodeError, UnicodeDecodeError):
                records = []
            for position, row in enumerate(batch):
                thumbnail = records[position].get("ThumbnailImage") if position < len(records) else None
                try:
                    if not isinstance(thumbnail, str) or not thumbnail.startswith("base64:"):
                        raise ValueError("JPEG has no embedded EXIF thumbnail")
                    extracted[row["capture_id"]] = (
                        fingerprint_bytes(base64.b64decode(thumbnail[7:])), None
                    )
                except (OSError, UnidentifiedImageError, ValueError) as exc:
                    extracted[row["capture_id"]] = (None, str(exc))
            if progress:
                progress("thumbnails", min(start + len(batch), len(stale_rows)), len(stale_rows))

    updated = 0
    cached = 0
    errors = 0
    total = len(rows)
    for index, row in enumerate(rows, 1):
        fresh = (
            row["source_file_id"] == row["file_id"]
            and row["cached_size"] == row["size_bytes"]
            and row["cached_modified"] == row["modified_ns"]
            and row["dhash64"] is not None
        )
        if fresh:
            cached += 1
        else:
            try:
                result, _ = extracted.get(row["capture_id"], (None, None))
                if result is None:
                    result = fingerprint_image(Path(row["path"]))
                values = (
                    result.dhash64, result.mean_r, result.mean_g, result.mean_b,
                    result.width, result.height,
                )
                error = None
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                values = (None, None, None, None, None, None)
                error = str(exc)
                errors += 1
            connection.execute(
                """
                INSERT INTO visual_fingerprints(
                    capture_id, source_file_id, dhash64, mean_r, mean_g, mean_b,
                    width, height, size_bytes, modified_ns, computed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    source_file_id=excluded.source_file_id, dhash64=excluded.dhash64,
                    mean_r=excluded.mean_r, mean_g=excluded.mean_g, mean_b=excluded.mean_b,
                    width=excluded.width, height=excluded.height,
                    size_bytes=excluded.size_bytes, modified_ns=excluded.modified_ns,
                    computed_at=excluded.computed_at, error=excluded.error
                """,
                (row["capture_id"], row["file_id"], *values, row["size_bytes"],
                 row["modified_ns"], utc_now(), error),
            )
            updated += 1
        if index % 50 == 0:
            connection.commit()
        if progress and (index == total or index % 25 == 0):
            progress("fingerprints", index, total)
    connection.commit()
    return {"fingerprints_considered": total, "fingerprints_updated": updated,
            "fingerprints_cached": cached, "fingerprint_errors": errors}


def rebuild_similarity_groups(
    connection: sqlite3.Connection,
    max_hamming: int = 14,
    max_color_distance: int = 60,
) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT bc.burst_id, bc.capture_id, bc.sequence_index, vf.dhash64,
               vf.mean_r, vf.mean_g, vf.mean_b
        FROM burst_captures bc
        LEFT JOIN visual_fingerprints vf ON vf.capture_id = bc.capture_id
        ORDER BY bc.burst_id, bc.sequence_index
        """
    ).fetchall()
    by_burst: dict[int, list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        by_burst[row["burst_id"]].append(row)

    overrides = {
        row["capture_id"]: row["action"]
        for row in connection.execute(
            "SELECT capture_id, action FROM similarity_group_overrides"
        )
    }

    groups: list[tuple[int, list[tuple[sqlite3.Row, int | None]], int]] = []
    for burst_id, captures in by_burst.items():
        segment: list[tuple[sqlite3.Row, int | None]] = []
        max_seen = 0
        def finish_segment() -> None:
            nonlocal segment, max_seen
            if len(segment) >= 2:
                groups.append((burst_id, segment, max_seen))
            segment, max_seen = [], 0

        for row in captures:
            override = overrides.get(row["capture_id"])
            if override == "exclude":
                finish_segment()
                continue
            if override == "split_before" and segment:
                finish_segment()
            if row["dhash64"] is None:
                finish_segment()
                continue
            distance = None
            similar = True
            if segment:
                previous = segment[-1][0]
                distance = hamming_distance(previous["dhash64"], row["dhash64"])
                color_distance = sum(
                    abs(previous[channel] - row[channel])
                    for channel in ("mean_r", "mean_g", "mean_b")
                )
                similar = distance <= max_hamming and color_distance <= max_color_distance
            if not similar:
                finish_segment()
                distance = None
            segment.append((row, distance))
            if distance is not None:
                max_seen = max(max_seen, distance)
        finish_segment()

    with transaction(connection):
        connection.execute("DELETE FROM similarity_group_captures")
        connection.execute("DELETE FROM similarity_groups")
        for ordinal, (burst_id, segment, max_seen) in enumerate(groups):
            key = f"burst:{burst_id}:visual:{ordinal}"
            cursor = connection.execute(
                """
                INSERT INTO similarity_groups(
                    burst_id, group_key, capture_count, max_adjacent_hamming
                ) VALUES (?, ?, ?, ?)
                """,
                (burst_id, key, len(segment), max_seen),
            )
            connection.executemany(
                """
                INSERT INTO similarity_group_captures(
                    group_id, capture_id, sequence_index, distance_from_previous
                ) VALUES (?, ?, ?, ?)
                """,
                [(cursor.lastrowid, row["capture_id"], index, distance)
                 for index, (row, distance) in enumerate(segment)],
            )
    return {
        "similarity_groups": len(groups),
        "captures_in_similarity_groups": sum(len(group) for _, group, _ in groups),
        "largest_similarity_group": max((len(group) for _, group, _ in groups), default=0),
    }


def analyze_visuals(
    connection: sqlite3.Connection,
    progress: Progress | None = None,
    limit: int | None = None,
    exiftool: Path | None = None,
    metadata_batch_size: int = 64,
) -> dict[str, int]:
    result = find_exact_duplicates(connection, progress)
    result.update(build_visual_fingerprints(
        connection, progress, limit, exiftool=exiftool,
        metadata_batch_size=metadata_batch_size,
    ))
    if limit is None:
        result.update(rebuild_similarity_groups(connection))
    return result
