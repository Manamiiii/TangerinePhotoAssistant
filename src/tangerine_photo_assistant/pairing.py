from __future__ import annotations

import sqlite3
from collections import defaultdict
from uuid import uuid4

from .database import transaction
from .inventory import JPEG_EXTENSIONS


def rebuild_captures(connection: sqlite3.Connection) -> dict[str, int]:
    rows = connection.execute(
        """
        SELECT id, parent_relative, stem, extension, media_kind, captured_at
        FROM files
        WHERE present = 1 AND (media_kind = 'raw' OR extension IN ('.jpg', '.jpeg'))
        ORDER BY parent_relative, stem, id
        """
    ).fetchall()
    groups: dict[tuple[str, str], list[sqlite3.Row]] = defaultdict(list)
    for row in rows:
        groups[(row["parent_relative"].casefold(), row["stem"].casefold())].append(row)

    existing_by_file: dict[int, int] = {
        row["file_id"]: row["capture_id"]
        for row in connection.execute("SELECT capture_id, file_id FROM capture_files")
    }
    protected_ids = {
        row[0]
        for table in ("visual_fingerprints", "quality_metrics", "capture_reviews", "ai_analyses")
        for row in connection.execute(f"SELECT DISTINCT capture_id FROM {table}")
    }
    previous_keys = {row['id']: row['capture_key'] for row in connection.execute(
        'SELECT id,capture_key FROM captures'
    )}
    summary: dict[str, int] = defaultdict(int)
    with transaction(connection):
        # Keep absent-file associations: they are the identity bridge on reappearance.
        connection.execute("DELETE FROM capture_files WHERE file_id IN (SELECT id FROM files WHERE present=1)")
        # Free path-derived keys while retaining capture ids and every dependent result.
        marker = uuid4().hex
        connection.execute(
            "UPDATE captures SET capture_key=? || ':' || id", (f"rebuild:{marker}",)
        )
        used_capture_ids: set[int] = set()

        for (parent_key, stem_key), files in groups.items():
            jpeg_count = sum(file["extension"] in JPEG_EXTENSIONS for file in files)
            raw_count = sum(file["media_kind"] == "raw" for file in files)
            if jpeg_count and raw_count:
                status = "paired"
            elif jpeg_count:
                status = "jpeg_only"
            else:
                status = "raw_only"
            if jpeg_count > 1 or raw_count > 1:
                status += "_duplicate_role"

            capture_key = f"{parent_key}/{stem_key}"
            captured_at = next(
                (file["captured_at"] for file in files if file["captured_at"]), None
            )
            candidates = {
                existing_by_file[file["id"]]
                for file in files
                if file["id"] in existing_by_file
                and existing_by_file[file["id"]] not in used_capture_ids
            }
            if len(candidates) > 1:
                raise ValueError('配对涉及多个已有拍摄单元，请先核对；未合并或删除人工数据')
            capture_id = min(
                candidates,
                key=lambda value: (value not in protected_ids, value),
            ) if candidates else None
            if capture_id is None:
                cursor = connection.execute(
                    """
                    INSERT INTO captures(
                        capture_key, parent_relative, stem, captured_at, pairing_status
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        capture_key, files[0]["parent_relative"], files[0]["stem"],
                        captured_at, status,
                    ),
                )
                capture_id = int(cursor.lastrowid)
            else:
                connection.execute(
                    """
                    UPDATE captures
                    SET capture_key=?, parent_relative=?, stem=?, captured_at=?, pairing_status=?
                    WHERE id=?
                    """,
                    (
                        capture_key, files[0]["parent_relative"], files[0]["stem"],
                        captured_at, status, capture_id,
                    ),
                )
            used_capture_ids.add(capture_id)
            for file in files:
                role = "raw" if file["media_kind"] == "raw" else "jpeg"
                connection.execute(
                    "INSERT INTO capture_files(capture_id, file_id, role) VALUES (?, ?, ?)",
                    (capture_id, file["id"], role),
                )
            summary[status] += 1

        obsolete = [
            row[0]
            for row in connection.execute("SELECT id FROM captures")
            if row[0] not in used_capture_ids
        ]
        # Missing captures are durable records, regardless of which user-data tables
        # happen to reference them. A key collision rolls back instead of losing history.
        connection.executemany(
            'UPDATE captures SET capture_key=? WHERE id=?',
            ((previous_keys[capture_id], capture_id) for capture_id in obsolete),
        )
        summary["preserved_results"] = len(used_capture_ids & protected_ids)
        summary["detached_protected"] = len(set(obsolete) & protected_ids)
    return dict(summary)
