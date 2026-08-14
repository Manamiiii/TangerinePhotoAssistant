from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..database import connect_readonly


def query_quality(
    database_path: Path,
    limit: int,
    offset: int,
    review_filter: str = "all",
    search: str | None = None,
    album_id: int | None = None,
) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        conditions = ["1=1"]
        parameters: list[Any] = []
        if review_filter == "problems":
            conditions.append("qm.issue_json <> '[]'")
        elif review_filter == "low_score":
            conditions.append("qm.technical_score < 70")
        elif review_filter == "with_model":
            conditions.append("aa.id IS NOT NULL")
        elif review_filter == "without_model":
            conditions.append("aa.id IS NULL")
        elif review_filter == "unrated":
            conditions.append("cr.user_rating IS NULL")
        if album_id is not None:
            conditions.append("e.id = ?")
            parameters.append(album_id)
        if search:
            conditions.append("(c.stem LIKE ? OR e.proposed_name LIKE ?)")
            term = f"%{search.strip()}%"
            parameters.extend((term, term))
        from_sql = """
            FROM quality_metrics qm
            JOIN captures c ON c.id = qm.capture_id
            JOIN event_captures ec ON ec.capture_id = c.id
            JOIN events e ON e.id = ec.event_id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            LEFT JOIN ai_analyses aa ON aa.id = (
                SELECT aa2.id FROM ai_analyses aa2
                WHERE aa2.capture_id = c.id AND aa2.status = 'complete'
                ORDER BY aa2.id DESC LIMIT 1
            )
        """
        where_sql = " AND ".join(conditions)
        total = connection.execute(
            f"SELECT COUNT(*) {from_sql} WHERE {where_sql}", parameters
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT qm.capture_id, c.stem, c.captured_at, e.id AS event_id,
                   e.proposed_name AS event_name,
                   e.category, qm.technical_score, qm.exposure_score, qm.sharpness_score,
                   qm.exif_score, qm.highlight_clip_pct, qm.shadow_clip_pct,
                   qm.issue_json, qm.error, cr.auto_rating, cr.auto_pick,
                   cr.similarity_rank, cr.user_rating, cr.user_pick,
                   cr.user_reject, cr.user_note, aa.result_json AS ai_result_json
            {from_sql}
            WHERE {where_sql}
            ORDER BY qm.error IS NOT NULL, qm.technical_score ASC, qm.capture_id
            LIMIT ? OFFSET ?
            """,
            (*parameters, limit, offset),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["issues"] = json.loads(item.pop("issue_json"))
            raw_ai = item.pop("ai_result_json")
            item["ai_result"] = json.loads(raw_ai) if raw_ai else None
            item["thumbnail_url"] = f"/api/thumbnails/{item['capture_id']}?size=320"
            items.append(item)
        album_rows = connection.execute(
            """
            SELECT e.id, e.proposed_name AS name, e.category,
                   COUNT(qm.capture_id) AS analyzed_count,
                   SUM(CASE WHEN qm.issue_json <> '[]' THEN 1 ELSE 0 END) AS problem_count,
                   SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM ai_analyses aa
                       WHERE aa.capture_id = c.id AND aa.status = 'complete'
                   ) THEN 1 ELSE 0 END) AS model_count
              FROM events e
              JOIN event_captures ec ON ec.event_id = e.id
              JOIN captures c ON c.id = ec.capture_id
              JOIN quality_metrics qm ON qm.capture_id = c.id
             GROUP BY e.id
             ORDER BY problem_count DESC, analyzed_count DESC, e.start_at DESC
            """
        ).fetchall()
        return {
            "count": total,
            "limit": limit,
            "offset": offset,
            "items": items,
            "albums": [dict(row) for row in album_rows],
        }
    finally:
        connection.close()
