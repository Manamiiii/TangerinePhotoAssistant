from __future__ import annotations

import json
import sqlite3
from collections.abc import Sequence
from uuid import uuid4

from .database import transaction
from .inventory import utc_now
from .quality import rebuild_group_recommendations
from .visual import rebuild_similarity_groups


class SimilarityGroupingError(ValueError):
    pass


class SimilarityCaptureNotFoundError(SimilarityGroupingError):
    pass


def set_similarity_override(
    connection: sqlite3.Connection, capture_id: int, action: str
) -> dict[str, int]:
    """Persist one legacy per-photo override and rebuild affected groups."""
    if action not in {"exclude", "split_before"}:
        raise SimilarityGroupingError("相似分组操作不受支持")
    if connection.execute(
        "SELECT 1 FROM captures WHERE id=?", (capture_id,)
    ).fetchone() is None:
        raise SimilarityCaptureNotFoundError("照片不存在")
    if connection.execute(
        "SELECT 1 FROM burst_captures WHERE capture_id=? LIMIT 1", (capture_id,)
    ).fetchone() is None:
        raise SimilarityGroupingError("这张照片不属于连拍候选")
    now = utc_now()
    with transaction(connection):
        connection.execute(
            """INSERT INTO similarity_group_overrides(
                   capture_id, action, created_at, updated_at
               ) VALUES (?, ?, ?, ?)
               ON CONFLICT(capture_id) DO UPDATE SET
                   action=excluded.action, updated_at=excluded.updated_at""",
            (capture_id, action, now, now),
        )
    return _rebuild(connection)


def _snapshot_overrides(
    connection: sqlite3.Connection, capture_ids: Sequence[int]
) -> list[dict[str, int | str | None]]:
    if not capture_ids:
        return []
    placeholders = ",".join("?" for _ in capture_ids)
    return [
        dict(row)
        for row in connection.execute(
            f"""SELECT capture_id, action, created_at, updated_at,
                       manual_batch_key, manual_group_key
                  FROM similarity_group_overrides
                 WHERE capture_id IN ({placeholders})
                 ORDER BY capture_id""",
            tuple(capture_ids),
        )
    ]


def _snapshot_state(snapshot: Sequence[dict[str, object]]) -> list[tuple[object, ...]]:
    return sorted(
        (
            int(item["capture_id"]),
            item.get("action"),
            item.get("manual_batch_key"),
            item.get("manual_group_key"),
        )
        for item in snapshot
    )


def _record_revision(
    connection: sqlite3.Connection,
    operation: str,
    capture_ids: Sequence[int],
    before: Sequence[dict[str, object]],
    after: Sequence[dict[str, object]],
) -> int:
    ordered_ids = sorted(set(capture_ids))
    cursor = connection.execute(
        """INSERT INTO similarity_group_revisions(
               operation, capture_ids_json, before_json, after_json, created_at
           ) VALUES (?, ?, ?, ?, ?)""",
        (
            operation,
            json.dumps(ordered_ids, ensure_ascii=False),
            json.dumps(list(before), ensure_ascii=False),
            json.dumps(list(after), ensure_ascii=False),
            utc_now(),
        ),
    )
    revision_id = int(cursor.lastrowid)
    connection.executemany(
        """INSERT INTO similarity_group_revision_captures(revision_id, capture_id)
           VALUES (?, ?)""",
        [(revision_id, capture_id) for capture_id in ordered_ids],
    )
    return revision_id


def _apply_snapshot(
    connection: sqlite3.Connection,
    capture_ids: Sequence[int],
    snapshot: Sequence[dict[str, object]],
) -> None:
    placeholders = ",".join("?" for _ in capture_ids)
    connection.execute(
        f"DELETE FROM similarity_group_overrides WHERE capture_id IN ({placeholders})",
        tuple(capture_ids),
    )
    connection.executemany(
        """INSERT INTO similarity_group_overrides(
               capture_id, action, created_at, updated_at,
               manual_batch_key, manual_group_key
           ) VALUES (?, ?, ?, ?, ?, ?)""",
        [
            (
                int(item["capture_id"]), item["action"], item["created_at"],
                item["updated_at"], item.get("manual_batch_key"),
                item.get("manual_group_key"),
            )
            for item in snapshot
        ],
    )


def list_similarity_group_revisions(
    connection: sqlite3.Connection,
    capture_id: int | None = None,
    limit: int = 10,
    album_id: int | None = None,
) -> list[dict[str, object]]:
    filters: list[str] = []
    parameters: list[int] = []
    if capture_id is not None:
        filters.append("rc.capture_id=?")
        parameters.append(capture_id)
    if album_id is not None:
        filters.append(
            "EXISTS (SELECT 1 FROM similarity_group_revision_captures arc "
            "JOIN event_captures aec ON aec.capture_id=arc.capture_id "
            "WHERE arc.revision_id=r.id AND aec.event_id=?)"
        )
        parameters.append(album_id)
    where_sql = f"WHERE {' AND '.join(filters)}" if filters else ""
    rows = connection.execute(
        f"""SELECT r.id, r.operation, r.after_json, r.created_at,
                   MIN(rc.capture_id) AS representative_capture_id,
                   GROUP_CONCAT(DISTINCT e.proposed_name) AS album_names
              FROM similarity_group_revisions r
              JOIN similarity_group_revision_captures rc ON rc.revision_id=r.id
              LEFT JOIN event_captures ec ON ec.capture_id=rc.capture_id
              LEFT JOIN events e ON e.id=ec.event_id
              {where_sql}
             GROUP BY r.id
             ORDER BY r.id DESC LIMIT ?""",
        (*parameters, limit),
    )
    result: list[dict[str, object]] = []
    labels = {
        "manual_edit": "人工调整",
        "restore_auto": "恢复自动识别",
        "restore_revision": "恢复历史版本",
        "undo_revision": "撤销调整",
    }
    for row in rows:
        snapshot = json.loads(row["after_json"])
        revision_capture_ids = [
            item["capture_id"]
            for item in connection.execute(
                """SELECT capture_id FROM similarity_group_revision_captures
                   WHERE revision_id=? ORDER BY capture_id""",
                (row["id"],),
            )
        ]
        current = _snapshot_overrides(connection, revision_capture_ids)
        group_keys = {
            item.get("manual_group_key") for item in snapshot
            if item.get("manual_group_key")
        }
        excluded = sum(1 for item in snapshot if item.get("action") == "exclude")
        result.append({
            "id": row["id"],
            "operation": row["operation"],
            "label": labels.get(row["operation"], "分组调整"),
            "created_at": row["created_at"],
            "group_count": len(group_keys),
            "excluded_count": excluded,
            "automatic": not snapshot,
            "representative_capture_id": row["representative_capture_id"],
            "album_names": row["album_names"].split(",") if row["album_names"] else [],
            "can_undo": row["operation"] == "manual_edit"
            and _snapshot_state(current) == _snapshot_state(snapshot),
        })
    return result


def restore_similarity_group_revision(
    connection: sqlite3.Connection, revision_id: int, *, use_before: bool = False
) -> dict[str, int]:
    row = connection.execute(
        """SELECT before_json, after_json FROM similarity_group_revisions WHERE id=?""",
        (revision_id,),
    ).fetchone()
    if row is None:
        raise SimilarityGroupingError("分组历史版本不存在")
    capture_ids = [
        item["capture_id"]
        for item in connection.execute(
            """SELECT capture_id FROM similarity_group_revision_captures
               WHERE revision_id=? ORDER BY capture_id""",
            (revision_id,),
        )
    ]
    existing = connection.execute(
        f"SELECT COUNT(*) FROM captures WHERE id IN ({','.join('?' for _ in capture_ids)})",
        tuple(capture_ids),
    ).fetchone()[0]
    if existing != len(capture_ids):
        raise SimilarityGroupingError("历史版本中的部分照片已经不存在")
    target = json.loads(row["before_json"] if use_before else row["after_json"])
    before = _snapshot_overrides(connection, capture_ids)
    with transaction(connection):
        _apply_snapshot(connection, capture_ids, target)
        after = _snapshot_overrides(connection, capture_ids)
        new_revision_id = _record_revision(
            connection,
            "undo_revision" if use_before else "restore_revision",
            capture_ids,
            before,
            after,
        )
    return {"revision_id": new_revision_id, **_rebuild(connection)}


def _rebuild(connection: sqlite3.Connection) -> dict[str, int]:
    result = rebuild_similarity_groups(connection)
    result.update(rebuild_group_recommendations(connection))
    return result


def restore_similarity_grouping(
    connection: sqlite3.Connection, capture_id: int
) -> dict[str, int]:
    """Remove one legacy override or the complete manual editing batch."""
    if connection.execute(
        "SELECT 1 FROM captures WHERE id=?", (capture_id,)
    ).fetchone() is None:
        raise SimilarityCaptureNotFoundError("照片不存在")
    override = connection.execute(
        "SELECT manual_batch_key FROM similarity_group_overrides WHERE capture_id=?",
        (capture_id,),
    ).fetchone()
    if override is not None and override["manual_batch_key"]:
        capture_ids = [
            row["capture_id"] for row in connection.execute(
                "SELECT capture_id FROM similarity_group_overrides WHERE manual_batch_key=?",
                (override["manual_batch_key"],),
            )
        ]
    else:
        capture_ids = [capture_id]
    before = _snapshot_overrides(connection, capture_ids)
    with transaction(connection):
        if override is not None and override["manual_batch_key"]:
            cursor = connection.execute(
                "DELETE FROM similarity_group_overrides WHERE manual_batch_key=?",
                (override["manual_batch_key"],),
            )
        else:
            cursor = connection.execute(
                "DELETE FROM similarity_group_overrides WHERE capture_id=?",
                (capture_id,),
            )
        after = _snapshot_overrides(connection, capture_ids)
        revision_id = _record_revision(
            connection, "restore_auto", capture_ids, before, after
        )
    return {
        "restored_overrides": cursor.rowcount,
        "revision_id": revision_id,
        **_rebuild(connection),
    }


def save_manual_similarity_grouping(
    connection: sqlite3.Connection,
    source_group_id: int,
    groups: Sequence[Sequence[int]],
    excluded_ids: Sequence[int],
) -> dict[str, int | str | list[int]]:
    """Persist one confirmed drag-and-drop edit using stable capture IDs."""
    source_ids = {
        row["capture_id"]
        for row in connection.execute(
            "SELECT capture_id FROM similarity_group_captures WHERE group_id=?",
            (source_group_id,),
        )
    }
    if not source_ids:
        raise SimilarityGroupingError("相似组不存在或已经更新")
    if any(len(group) < 2 for group in groups):
        raise SimilarityGroupingError("相似分组至少需要两张照片；单张照片请放入移出区")
    submitted = [capture_id for group in groups for capture_id in group]
    submitted.extend(excluded_ids)
    if len(submitted) != len(set(submitted)) or set(submitted) != source_ids:
        raise SimilarityGroupingError("每张照片必须且只能放入一个组或移出区")

    existing_batch_keys = {
        row["manual_batch_key"]
        for row in connection.execute(
            f"""SELECT DISTINCT manual_batch_key FROM similarity_group_overrides
                WHERE capture_id IN ({','.join('?' for _ in source_ids)})
                  AND manual_batch_key IS NOT NULL""",
            tuple(source_ids),
        )
    }
    batch_key = (
        next(iter(existing_batch_keys))
        if len(existing_batch_keys) == 1
        else f"manual:{uuid4().hex}"
    )
    now = utc_now()
    placeholders = ",".join("?" for _ in source_ids)
    ordered_ids = sorted(source_ids)
    before = _snapshot_overrides(connection, ordered_ids)
    with transaction(connection):
        connection.execute(
            f"DELETE FROM similarity_group_overrides WHERE capture_id IN ({placeholders})",
            tuple(source_ids),
        )
        for index, group in enumerate(groups):
            group_key = f"{batch_key}:{index}"
            connection.executemany(
                """INSERT INTO similarity_group_overrides(
                       capture_id, action, created_at, updated_at,
                       manual_batch_key, manual_group_key
                   ) VALUES (?, 'split_before', ?, ?, ?, ?)""",
                [(capture_id, now, now, batch_key, group_key) for capture_id in group],
            )
        connection.executemany(
            """INSERT INTO similarity_group_overrides(
                   capture_id, action, created_at, updated_at, manual_batch_key
               ) VALUES (?, 'exclude', ?, ?, ?)""",
            [(capture_id, now, now, batch_key) for capture_id in excluded_ids],
        )
        after = _snapshot_overrides(connection, ordered_ids)
        revision_id = _record_revision(
            connection, "manual_edit", ordered_ids, before, after
        )
    rebuilt = _rebuild(connection)
    group_ids = []
    for group in groups:
        if len(group) < 2:
            continue
        row = connection.execute(
            "SELECT group_id FROM similarity_group_captures WHERE capture_id=?",
            (group[0],),
        ).fetchone()
        if row is not None and row["group_id"] not in group_ids:
            group_ids.append(row["group_id"])
    return {
        "batch_key": batch_key,
        "revision_id": revision_id,
        "group_ids": group_ids,
        **rebuilt,
    }
