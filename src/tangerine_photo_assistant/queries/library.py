from __future__ import annotations

from pathlib import Path
from typing import Any

from ..database import connect_readonly


def query_library_captures(
    database_path: Path,
    limit: int,
    offset: int,
    *,
    album_id: int | None = None,
    unassigned_only: bool = False,
    category: str | None = None,
    camera_model: str | None = None,
    lens_model: str | None = None,
    rating: int | None = None,
    selection: str | None = None,
    quality: str | None = None,
    tag_subject: str | None = None,
    tag_status: str | None = None,
    tag_problem: str | None = None,
    tag_location: str | None = None,
    selection_reason: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    sort: str = "newest",
    collapse_groups: bool = False,
) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        conditions = [
            "f.present = 1",
            "cf.file_id = (SELECT MIN(cf2.file_id) FROM capture_files cf2 JOIN files f2 ON f2.id = cf2.file_id WHERE cf2.capture_id = c.id AND cf2.role = 'jpeg' AND f2.present = 1)",
        ]
        parameters: list[Any] = []
        if album_id is not None:
            conditions.append("e.id = ?")
            parameters.append(album_id)
        elif unassigned_only:
            conditions.append("e.id IS NULL")
        if category:
            conditions.append("e.category = ?")
            parameters.append(category)
        if camera_model:
            conditions.append("f.camera_model = ?")
            parameters.append(camera_model)
        if lens_model:
            conditions.append("f.lens_model = ?")
            parameters.append(lens_model)
        if rating is not None:
            conditions.append("cr.user_rating = ?")
            parameters.append(rating)
        if selection == "picked":
            conditions.append("COALESCE(cr.user_pick, 0) = 1")
        elif selection == "rejected":
            conditions.append("COALESCE(cr.user_reject, 0) = 1")
        elif selection == "unreviewed":
            conditions.append(
                "cr.user_rating IS NULL AND COALESCE(cr.user_pick, 0) = 0 "
                "AND COALESCE(cr.user_reject, 0) = 0"
            )
        if quality == "problems":
            conditions.append(
                "qm.issue_json IS NOT NULL AND qm.issue_json NOT IN ('', '[]')"
            )
        elif quality == "low":
            conditions.append("qm.technical_score < 70")
        elif quality == "high":
            conditions.append("qm.technical_score >= 85")
        elif quality == "unanalyzed":
            conditions.append("qm.technical_score IS NULL")
        for dimension, name in (
            ("subject", tag_subject),
            ("status", tag_status),
            ("problem", tag_problem),
            ("location", tag_location),
        ):
            if name:
                conditions.append(
                    """EXISTS (
                        SELECT 1 FROM capture_tags filter_ct
                        JOIN tag_definitions filter_td ON filter_td.id=filter_ct.tag_id
                        WHERE filter_ct.capture_id=c.id
                          AND filter_td.dimension=? AND filter_td.name=?
                    )"""
                )
                parameters.extend((dimension, name))
        if selection_reason:
            conditions.append(
                """COALESCE(cr.user_pick, 0)=1 AND EXISTS (
                       SELECT 1
                       FROM json_each(COALESCE(cr.selection_reason_json, '[]')) reason
                       WHERE reason.value=?
                   )"""
            )
            parameters.append(selection_reason)
        if date_from:
            conditions.append("substr(c.captured_at, 1, 10) >= ?")
            parameters.append(date_from)
        if date_to:
            conditions.append("substr(c.captured_at, 1, 10) <= ?")
            parameters.append(date_to)
        if search:
            conditions.append(
                "(c.stem LIKE ? OR e.proposed_name LIKE ? OR c.parent_relative LIKE ?)"
            )
            term = f"%{search.strip()}%"
            parameters.extend((term, term, term))
        where_sql = " AND ".join(conditions)
        from_sql = """
            FROM captures c
            JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
            JOIN files f ON f.id = cf.file_id
            LEFT JOIN event_captures ec ON ec.capture_id = c.id
            LEFT JOIN events e ON e.id = ec.event_id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            LEFT JOIN similarity_group_captures sgc ON sgc.capture_id = c.id
            LEFT JOIN similarity_groups sg ON sg.id = sgc.group_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
            LEFT JOIN similarity_group_overrides sgo ON sgo.capture_id = c.id
            LEFT JOIN (
                SELECT members.group_id,
                       SUM(CASE WHEN COALESCE(reviews.user_pick, 0)=1 THEN 1 ELSE 0 END) AS pick_count,
                       SUM(CASE WHEN COALESCE(reviews.user_reject, 0)=1 THEN 1 ELSE 0 END) AS reject_count,
                       SUM(CASE WHEN reviews.user_rating IS NULL
                                     AND COALESCE(reviews.user_pick, 0)=0
                                     AND COALESCE(reviews.user_reject, 0)=0 THEN 1 ELSE 0 END) AS unreviewed_count
                FROM similarity_group_captures members
                LEFT JOIN capture_reviews reviews ON reviews.capture_id=members.capture_id
                GROUP BY members.group_id
            ) group_stats ON group_stats.group_id=sg.id
        """
        ordering = {
            "oldest": "c.captured_at IS NULL, c.captured_at ASC, c.id ASC",
            "name": "c.stem COLLATE NOCASE ASC, c.id ASC",
            "rating": "cr.user_rating IS NULL, cr.user_rating DESC, c.captured_at DESC",
        }.get(sort, "c.captured_at IS NULL, c.captured_at DESC, c.id DESC")
        row_sql = f"""
            SELECT c.id, c.stem, c.captured_at, c.pairing_status,
                   f.camera_model, f.lens_model, e.id AS album_id,
                   e.proposed_name AS album_name, e.category,
                   cr.user_rating, cr.user_pick, cr.user_reject, cr.user_note,
                   cr.auto_pick, qm.technical_score,
                   sgo.action AS grouping_override, sgo.manual_batch_key,
                   COALESCE((
                       SELECT SUM(member_file.size_bytes)
                       FROM capture_files member_cf
                       JOIN files member_file ON member_file.id=member_cf.file_id
                       WHERE member_cf.capture_id=c.id AND member_file.present=1
                   ), 0) AS size_bytes,
                   MAX(sg.id) AS similarity_group_id,
                   MAX(sg.capture_count) AS similarity_group_size,
                   MAX(group_stats.pick_count) AS group_pick_count,
                   MAX(group_stats.reject_count) AS group_reject_count,
                   MAX(group_stats.unreviewed_count) AS group_unreviewed_count
            {from_sql}
            WHERE {where_sql}
            GROUP BY c.id
            ORDER BY {ordering}
            """
        if collapse_groups:
            rows = connection.execute(row_sql, parameters).fetchall()
        else:
            rows = connection.execute(
                f"{row_sql} LIMIT ? OFFSET ?", (*parameters, limit, offset)
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["thumbnail_url"] = f"/api/thumbnails/{item['id']}?size=640"
            item["item_type"] = "photo"
            item["selection_capture_ids"] = [item["id"]]
            items.append(item)
        if collapse_groups:
            folded: list[dict[str, Any]] = []
            positions: dict[int, int] = {}
            members: dict[int, list[dict[str, Any]]] = {}
            for item in items:
                group_id = item["similarity_group_id"]
                if group_id is None:
                    folded.append(item)
                    continue
                members.setdefault(group_id, []).append(item)
                if group_id not in positions:
                    positions[group_id] = len(folded)
                    group_item = dict(item)
                    group_item["item_type"] = "group"
                    folded.append(group_item)
                    continue
                current = folded[positions[group_id]]
                candidate_rank = (
                    int(bool(item["user_pick"])), item["user_rating"] or 0,
                    int(bool(item["auto_pick"])), item["technical_score"] or -1,
                )
                current_rank = (
                    int(bool(current["user_pick"])), current["user_rating"] or 0,
                    int(bool(current["auto_pick"])), current["technical_score"] or -1,
                )
                if candidate_rank > current_rank:
                    replacement = dict(item)
                    replacement["item_type"] = "group"
                    folded[positions[group_id]] = replacement
            for group_id, group_members in members.items():
                group_item = folded[positions[group_id]]
                group_item["selection_capture_ids"] = [
                    item["id"] for item in group_members
                ]
                group_item["size_bytes"] = sum(
                    item["size_bytes"] for item in group_members
                )
            total = len(folded)
            return {
                "count": total,
                "limit": limit,
                "offset": offset,
                "items": folded[offset:offset + limit],
                "collapsed": True,
            }
        total = connection.execute(
            f"SELECT COUNT(DISTINCT c.id) {from_sql} WHERE {where_sql}",
            parameters,
        ).fetchone()[0]
        return {
            "count": total,
            "limit": limit,
            "offset": offset,
            "items": items,
            "collapsed": False,
        }
    finally:
        connection.close()


def query_library_filters(database_path: Path) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        albums = connection.execute(
            """SELECT id, proposed_name AS name, category, capture_count, status
               FROM events WHERE status != 'archived'
               ORDER BY start_at IS NULL, start_at DESC, proposed_name"""
        ).fetchall()
        types = connection.execute(
            "SELECT name, built_in FROM album_types ORDER BY sort_order, name"
        ).fetchall()
        cameras = connection.execute(
            """SELECT DISTINCT camera_model FROM files
               WHERE present=1 AND camera_model IS NOT NULL AND camera_model!=''
               ORDER BY camera_model"""
        ).fetchall()
        lenses = connection.execute(
            """SELECT DISTINCT lens_model FROM files
               WHERE present=1 AND lens_model IS NOT NULL AND lens_model!=''
               ORDER BY lens_model"""
        ).fetchall()
        tags = connection.execute(
            """SELECT td.dimension, td.name, COUNT(DISTINCT ct.capture_id) AS capture_count
               FROM tag_definitions td
               JOIN capture_tags ct ON ct.tag_id=td.id
               GROUP BY td.id
               ORDER BY CASE td.dimension
                            WHEN 'subject' THEN 1 WHEN 'status' THEN 2
                            WHEN 'problem' THEN 3 ELSE 4 END,
                        td.sort_order, td.name"""
        ).fetchall()
        return {
            "albums": [dict(row) for row in albums],
            "album_types": [dict(row) for row in types],
            "cameras": [row[0] for row in cameras],
            "lenses": [row[0] for row in lenses],
            "tags": [dict(row) for row in tags],
        }
    finally:
        connection.close()
