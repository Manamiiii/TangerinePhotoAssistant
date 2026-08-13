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
    connection: sqlite3.Connection, capture_id: int, limit: int = 10
) -> list[dict[str, object]]:
    rows = connection.execute(
        """SELECT r.id, r.operation, r.after_json, r.created_at
             FROM similarity_group_revisions r
             JOIN similarity_group_revision_captures rc ON rc.revision_id=r.id
            WHERE rc.capture_id=?
            ORDER BY r.id DESC LIMIT ?""",
        (capture_id, limit),
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
) -> dict[str, int | str]:
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
    if any(not group for group in groups):
        raise SimilarityGroupingError("不能保存空分组")
    submitted = [capture_id for group in groups for capture_id in group]
    submitted.extend(excluded_ids)
    if len(submitted) != len(set(submitted)) or set(submitted) != source_ids:
        raise SimilarityGroupingError("每张照片必须且只能放入一个组或移出区")

    batch_key = f"manual:{uuid4().hex}"
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
            if len(group) == 1:
                connection.execute(
                    """INSERT INTO similarity_group_overrides(
                           capture_id, action, created_at, updated_at, manual_batch_key
                       ) VALUES (?, 'exclude', ?, ?, ?)""",
                    (group[0], now, now, batch_key),
                )
                continue
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
    return {
        "batch_key": batch_key,
        "revision_id": revision_id,
        **_rebuild(connection),
    }
