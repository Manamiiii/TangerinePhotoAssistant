from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..database import connect_readonly
from ..insights import review_condition_sql


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
    model_problem: str | None = None,
    review_condition: str | None = None,
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
        if model_problem:
            conditions.append(
                """EXISTS (
                       SELECT 1
                       FROM ai_analyses filter_ai,
                            json_each(json_extract(filter_ai.result_json, '$.visible_problems')) problem
                       WHERE filter_ai.capture_id=c.id AND filter_ai.status='complete'
                         AND COALESCE(filter_ai.user_verdict, '')!='inaccurate'
                         AND filter_ai.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                                          WHERE newest.capture_id=c.id
                                            AND newest.status='complete')
                         AND json_extract(problem.value, '$.name')=?
                   )"""
            )
            parameters.append(model_problem)
        if review_condition:
            expression, condition_parameters = review_condition_sql(review_condition)
            conditions.append(expression)
            parameters.extend(condition_parameters)
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
        select_sql = f"""
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
            """
        if collapse_groups:
            outer_ordering = {
                "oldest": "captured_at IS NULL, captured_at ASC, id ASC",
                "name": "stem COLLATE NOCASE ASC, id ASC",
                "rating": "user_rating IS NULL, user_rating DESC, captured_at DESC",
            }.get(sort, "captured_at IS NULL, captured_at DESC, id DESC")
            collapsed_sql = f"""
                WITH matched AS ({select_sql}),
                summaries AS (
                    SELECT COALESCE(similarity_group_id, -id) AS item_key,
                           COUNT(*) AS member_count,
                           SUM(size_bytes) AS folded_size_bytes,
                           json_group_array(id) AS selection_capture_ids
                    FROM matched
                    GROUP BY item_key
                ),
                ranked AS (
                    SELECT matched.*,
                           COALESCE(similarity_group_id, -id) AS item_key,
                           ROW_NUMBER() OVER (
                               PARTITION BY COALESCE(similarity_group_id, -id)
                               ORDER BY COALESCE(user_pick, 0) DESC,
                                        COALESCE(user_rating, 0) DESC,
                                        COALESCE(auto_pick, 0) DESC,
                                        COALESCE(technical_score, -1) DESC,
                                        id
                           ) AS representative_rank
                    FROM matched
                )
                SELECT ranked.*, summaries.member_count,
                       summaries.folded_size_bytes,
                       summaries.selection_capture_ids
                FROM ranked
                JOIN summaries USING (item_key)
                WHERE representative_rank=1
                ORDER BY {outer_ordering}
                LIMIT ? OFFSET ?
            """
            rows = connection.execute(
                collapsed_sql, (*parameters, limit, offset)
            ).fetchall()
        else:
            rows = connection.execute(
                f"{select_sql} ORDER BY {ordering} LIMIT ? OFFSET ?",
                (*parameters, limit, offset),
            ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            item["thumbnail_url"] = f"/api/thumbnails/{item['id']}?size=640"
            if collapse_groups:
                item["item_type"] = (
                    "group" if item["similarity_group_id"] is not None else "photo"
                )
                item["selection_capture_ids"] = json.loads(
                    item.pop("selection_capture_ids")
                )
                item["size_bytes"] = item.pop("folded_size_bytes")
                item.pop("item_key")
                item.pop("representative_rank")
                item.pop("member_count")
            else:
                item["item_type"] = "photo"
                item["selection_capture_ids"] = [item["id"]]
            items.append(item)
        if collapse_groups:
            total = connection.execute(
                f"""WITH matched AS ({select_sql})
                    SELECT COUNT(*) FROM (
                        SELECT COALESCE(similarity_group_id, -id)
                        FROM matched GROUP BY COALESCE(similarity_group_id, -id)
                    )""",
                parameters,
            ).fetchone()[0]
            return {
                "count": total,
                "limit": limit,
                "offset": offset,
                "items": items,
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
        model_problems = connection.execute(
            """WITH latest AS (
                   SELECT aa.capture_id, aa.result_json
                   FROM ai_analyses aa
                   WHERE aa.status='complete' AND aa.result_json IS NOT NULL
                     AND COALESCE(aa.user_verdict, '')!='inaccurate'
                     AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                                WHERE newest.capture_id=aa.capture_id
                                  AND newest.status='complete')
               )
               SELECT json_extract(problem.value, '$.name') AS name,
                      COUNT(DISTINCT latest.capture_id) AS capture_count
               FROM latest,
                    json_each(json_extract(latest.result_json, '$.visible_problems')) problem
               WHERE json_extract(problem.value, '$.name') IS NOT NULL
               GROUP BY name ORDER BY capture_count DESC, name"""
        ).fetchall()
        return {
            "albums": [dict(row) for row in albums],
            "album_types": [dict(row) for row in types],
            "cameras": [row[0] for row in cameras],
            "lenses": [row[0] for row in lenses],
            "tags": [dict(row) for row in tags],
            "model_problems": [dict(row) for row in model_problems],
        }
    finally:
        connection.close()
