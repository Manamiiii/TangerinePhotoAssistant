from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..database import connect_readonly


def query_albums(
    database_path: Path, limit: int, offset: int
) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        total = connection.execute(
            "SELECT COUNT(*) FROM events WHERE status != 'archived'"
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                e.id, e.proposed_name, e.category, e.date_label, e.start_at, e.end_at,
                e.capture_count, e.status, e.confidence, e.reason_json,
                COUNT(DISTINCT es.parent_relative) AS source_count,
                COUNT(DISTINCT b.id) AS burst_count,
                COALESCE(MAX(b.capture_count), 0) AS largest_burst,
                (SELECT COUNT(*) FROM event_equipment ee
                 WHERE ee.event_id=e.id AND ee.equipment_kind='accessory') AS equipment_count
            FROM events e
            LEFT JOIN event_sources es ON es.event_id = e.id
            LEFT JOIN bursts b ON b.event_id = e.id
            WHERE e.status != 'archived'
            GROUP BY e.id
            ORDER BY e.start_at IS NULL, e.start_at DESC, e.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["reason"] = json.loads(item.pop("reason_json"))
            item["sources"] = [
                source[0]
                for source in connection.execute(
                    """
                    SELECT parent_relative FROM event_sources
                    WHERE event_id = ? ORDER BY parent_relative
                    """,
                    (row["id"],),
                )
            ]
            item["equipment_keys"] = [
                equipment[0]
                for equipment in connection.execute(
                    """SELECT equipment_key FROM event_equipment
                       WHERE event_id=? AND equipment_kind='accessory'
                       ORDER BY equipment_key""",
                    (row["id"],),
                )
            ]
            items.append(item)
        return {"count": total, "limit": limit, "offset": offset, "items": items}
    finally:
        connection.close()
