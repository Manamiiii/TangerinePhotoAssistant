from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from uuid import uuid4

from .database import transaction
from .inventory import utc_now
from .quality import rebuild_group_recommendations
from .visual import rebuild_similarity_groups


class SimilarityGroupingError(ValueError):
    pass


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
    return {"restored_overrides": cursor.rowcount, **_rebuild(connection)}


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
    return {"batch_key": batch_key, **_rebuild(connection)}
