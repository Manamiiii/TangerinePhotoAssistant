from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from uuid import uuid4

from .database import transaction
from .inventory import utc_now


class AlbumError(ValueError):
    pass


class AlbumNotFoundError(AlbumError):
    pass


class AlbumConflictError(AlbumError):
    pass


@contextmanager
def _album_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Match the former route helpers, including callers with pending setup writes."""
    if not connection.in_transaction:
        with transaction(connection):
            yield
        return
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        connection.commit()


def _require_album_type(connection: sqlite3.Connection, category: str) -> None:
    if connection.execute(
        "SELECT 1 FROM album_types WHERE name=?", (category,)
    ).fetchone() is None:
        raise AlbumError("相册类型不存在")


def update_album(
    connection: sqlite3.Connection,
    album_id: int,
    name: str,
    category: str,
    status: str,
    accessory_keys: Sequence[str] | None = None,
) -> dict[str, int | str]:
    name = name.strip()
    category = category.strip()
    if not name or len(name) > 180:
        raise AlbumError("相册名称必须为1到180个字符")
    if status not in {"proposed", "confirmed"}:
        raise AlbumError("相册状态不受支持")
    _require_album_type(connection, category)
    clean_accessory_keys = None
    if accessory_keys is not None:
        clean_accessory_keys = sorted({key.strip() for key in accessory_keys if key.strip()})
        if len(clean_accessory_keys) > 100 or any(len(key) > 300 for key in clean_accessory_keys):
            raise AlbumError("相册附件选择无效")
    with _album_transaction(connection):
        cursor = connection.execute(
            """UPDATE events
               SET proposed_name=?, category=?, status=?, updated_at=?
               WHERE id=?""",
            (name, category, status, utc_now(), album_id),
        )
        if cursor.rowcount == 0:
            raise AlbumNotFoundError("相册不存在")
        if clean_accessory_keys is not None:
            connection.execute(
                "DELETE FROM event_equipment WHERE event_id=? AND equipment_kind='accessory'",
                (album_id,),
            )
            connection.executemany(
                """INSERT INTO event_equipment(
                       event_id, equipment_kind, equipment_key, source, created_at
                   ) VALUES (?, 'accessory', ?, 'manual', ?)""",
                ((album_id, key, utc_now()) for key in clean_accessory_keys),
            )
    return {"id": album_id, "status": "saved"}


def create_album(
    connection: sqlite3.Connection, name: str, category: str
) -> dict[str, int | str]:
    name = name.strip()
    category = category.strip()
    if not name:
        raise AlbumError("相册名称不能为空")
    _require_album_type(connection, category)
    now = utc_now()
    with _album_transaction(connection):
        cursor = connection.execute(
            """INSERT INTO events(
                   event_key, proposed_name, category, date_label, start_at,
                   end_at, capture_count, status, confidence, reason_json,
                   created_at, updated_at
               ) VALUES (?, ?, ?, NULL, NULL, NULL, 0, 'confirmed', 1.0, ?, ?, ?)""",
            (
                f"manual-album:{uuid4().hex}",
                name,
                category,
                json.dumps({"method": "manual", "legacy_buckets": []}, ensure_ascii=False),
                now,
                now,
            ),
        )
    return {"id": int(cursor.lastrowid), "name": name, "category": category}


def create_album_type(connection: sqlite3.Connection, name: str) -> dict[str, int | str]:
    name = name.strip()
    if not name:
        raise AlbumError("相册类型名称不能为空")
    try:
        with _album_transaction(connection):
            connection.execute(
                """INSERT INTO album_types(name, sort_order, built_in, created_at)
                   VALUES (?, 100, 0, ?)""",
                (name, utc_now()),
            )
    except sqlite3.IntegrityError as exc:
        raise AlbumConflictError("同名相册类型已经存在") from exc
    return {"name": name, "built_in": 0}


def rename_album_type(
    connection: sqlite3.Connection, name: str, next_name: str
) -> dict[str, int | str]:
    next_name = next_name.strip()
    if not next_name:
        raise AlbumError("相册类型名称不能为空")
    row = connection.execute(
        "SELECT built_in FROM album_types WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise AlbumNotFoundError("相册类型不存在")
    if row["built_in"]:
        raise AlbumConflictError("内置相册类型不能改名")
    if connection.execute(
        "SELECT 1 FROM album_types WHERE name=?", (next_name,)
    ).fetchone():
        raise AlbumConflictError("同名相册类型已经存在")
    now = utc_now()
    with _album_transaction(connection):
        connection.execute(
            "UPDATE events SET category=?, updated_at=? WHERE category=?",
            (next_name, now, name),
        )
        connection.execute("UPDATE album_types SET name=? WHERE name=?", (next_name, name))
    return {"name": next_name, "previous_name": name, "built_in": 0}


def delete_album_type(connection: sqlite3.Connection, name: str) -> dict[str, str]:
    row = connection.execute(
        "SELECT built_in FROM album_types WHERE name=?", (name,)
    ).fetchone()
    if row is None:
        raise AlbumNotFoundError("相册类型不存在")
    if row["built_in"]:
        raise AlbumConflictError("内置相册类型不能删除")
    if connection.execute(
        "SELECT 1 FROM events WHERE category=? LIMIT 1", (name,)
    ).fetchone():
        raise AlbumConflictError("该类型仍被相册使用")
    with _album_transaction(connection):
        connection.execute("DELETE FROM album_types WHERE name=?", (name,))
    return {"name": name, "status": "deleted"}


def assign_captures_to_album(
    connection: sqlite3.Connection, album_id: int, capture_ids: Sequence[int]
) -> int:
    ordered_ids = sorted(set(capture_ids))
    if not ordered_ids:
        return 0
    if connection.execute(
        "SELECT 1 FROM events WHERE id=? AND status!='archived'", (album_id,)
    ).fetchone() is None:
        raise AlbumError("目标相册不存在")
    placeholders = ",".join("?" for _ in ordered_ids)
    existing_ids = {
        row[0]
        for row in connection.execute(
            f"SELECT id FROM captures WHERE id IN ({placeholders})", ordered_ids
        )
    }
    if len(existing_ids) != len(ordered_ids):
        raise AlbumError("选择中包含不存在的照片")
    affected = {
        row[0]
        for row in connection.execute(
            f"SELECT DISTINCT event_id FROM event_captures WHERE capture_id IN ({placeholders})",
            ordered_ids,
        )
    }
    now = utc_now()
    with _album_transaction(connection):
        connection.execute(
            f"DELETE FROM event_captures WHERE capture_id IN ({placeholders})", ordered_ids
        )
        next_sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence_index), -1) + 1 FROM event_captures WHERE event_id=?",
            (album_id,),
        ).fetchone()[0]
        connection.executemany(
            "INSERT INTO event_captures(event_id, capture_id, sequence_index) VALUES (?, ?, ?)",
            (
                (album_id, capture_id, next_sequence + index)
                for index, capture_id in enumerate(ordered_ids)
            ),
        )
        affected.add(album_id)
        for affected_id in affected:
            connection.execute("DELETE FROM event_sources WHERE event_id=?", (affected_id,))
            connection.execute(
                """INSERT INTO event_sources(event_id, parent_relative)
                   SELECT ?, c.parent_relative FROM event_captures ec
                   JOIN captures c ON c.id=ec.capture_id
                   WHERE ec.event_id=? GROUP BY c.parent_relative""",
                (affected_id, affected_id),
            )
            connection.execute(
                """UPDATE events SET
                       capture_count=(SELECT COUNT(*) FROM event_captures WHERE event_id=?),
                       start_at=(SELECT MIN(c.captured_at) FROM event_captures ec JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?),
                       end_at=(SELECT MAX(c.captured_at) FROM event_captures ec JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?),
                       status=CASE WHEN id=? THEN 'confirmed' ELSE status END,
                       updated_at=? WHERE id=?""",
                (affected_id, affected_id, affected_id, album_id, now, affected_id),
            )
    return len(ordered_ids)
