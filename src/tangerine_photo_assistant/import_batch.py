"""Durable scan intent, retained until new captures have an album assignment."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .albums import assign_captures_to_album
from .database import transaction
from .inventory import utc_now


def pending_import(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute("""SELECT i.*, e.proposed_name AS album_name
        FROM import_batch i JOIN events e ON e.id=i.album_id WHERE i.id=1""").fetchone()
    return dict(row) if row else None


def validate_target(batch: dict[str, Any] | None, album_id: int, root: Path) -> None:
    if batch is None:
        return
    if batch['album_id'] != album_id:
        raise ValueError(f"上次导入尚未完成，请先在相册“{batch['album_name']}”中继续扫描")
    if Path(batch['root_path']).resolve() != root.resolve():
        raise ValueError("上次导入尚未完成，活动图库根目录已变化；请恢复原目录后继续扫描")


def begin_import(connection: sqlite3.Connection, album_id: int, root: Path) -> dict[str, Any]:
    batch = pending_import(connection)
    validate_target(batch, album_id, root)
    if batch is not None:
        return batch
    with transaction(connection):
        connection.execute("""INSERT INTO import_batch(
            id,album_id,root_path,after_scan_run_id,existing_capture_ids_json,created_at)
            VALUES(1,?,?,?,?,?)""", (
                album_id, str(root.resolve()),
                connection.execute("SELECT COALESCE(MAX(id),0) FROM scan_runs").fetchone()[0],
                json.dumps([row[0] for row in connection.execute("SELECT id FROM captures")]),
                utc_now(),
            ))
    return pending_import(connection)  # type: ignore[return-value]


def finish_import(connection: sqlite3.Connection, batch: dict[str, Any]) -> int:
    existing_ids = set(json.loads(batch['existing_capture_ids_json']))
    capture_ids = [row[0] for row in connection.execute("""
        SELECT DISTINCT cf.capture_id FROM capture_files cf JOIN files f ON f.id=cf.file_id
        WHERE f.first_seen_run_id>? AND f.present=1""", (batch['after_scan_run_id'],))
        if row[0] not in existing_ids]
    try:
        # Album assignment commits an existing transaction, so remove the intent
        # first and let both changes commit or roll back together.
        connection.execute("DELETE FROM import_batch WHERE id=1")
        assigned = assign_captures_to_album(connection, batch['album_id'], capture_ids)
        connection.commit()
        return assigned
    except BaseException:
        connection.rollback()
        raise
