from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..database import connect_readonly


def query_similarity_groups(
    database_path: Path,
    limit: int,
    offset: int,
    review_filter: str = "all",
    album_id: int | None = None,
) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        album_filter = " AND b.event_id=?" if album_id is not None else ""
        count_parameters = (album_id,) if album_id is not None else ()
        pending_condition = """
            NOT EXISTS (
                SELECT 1 FROM similarity_group_captures psgc
                JOIN capture_reviews pcr ON pcr.capture_id = psgc.capture_id
                WHERE psgc.group_id = sg.id AND COALESCE(pcr.user_pick, 0) = 1
            ) AND EXISTS (
                SELECT 1 FROM similarity_group_captures rsgc
                LEFT JOIN capture_reviews rcr ON rcr.capture_id = rsgc.capture_id
                WHERE rsgc.group_id = sg.id AND COALESCE(rcr.user_reject, 0) = 0
            )
        """
        completed_condition = f"NOT ({pending_condition})"
        adjusted_condition = """
            EXISTS (
                SELECT 1 FROM similarity_group_captures asgc
                JOIN similarity_group_overrides aso ON aso.capture_id = asgc.capture_id
                WHERE asgc.group_id = sg.id
            )
        """
        review_condition = {
            "pending": pending_condition,
            "completed": completed_condition,
            "adjusted": adjusted_condition,
        }.get(review_filter, "1=1")
        total = connection.execute(
            f"""SELECT COUNT(*) FROM similarity_groups sg
                JOIN bursts b ON b.id=sg.burst_id WHERE 1=1{album_filter}""",
            count_parameters,
        ).fetchone()[0]
        pending_count = connection.execute(
            f"""
            SELECT COUNT(*) FROM similarity_groups sg
            JOIN bursts b ON b.id=sg.burst_id
            WHERE {pending_condition}
            {album_filter}
            """,
            count_parameters,
        ).fetchone()[0]
        album_rows = connection.execute(
            """
            SELECT e.id, e.proposed_name AS name, e.category,
                   COUNT(*) AS total_count,
                   SUM(CASE WHEN NOT EXISTS (
                       SELECT 1 FROM similarity_group_captures psgc
                       JOIN capture_reviews pcr ON pcr.capture_id=psgc.capture_id
                       WHERE psgc.group_id=sg.id AND COALESCE(pcr.user_pick, 0)=1
                   ) AND EXISTS (
                       SELECT 1 FROM similarity_group_captures rsgc
                       LEFT JOIN capture_reviews rcr ON rcr.capture_id=rsgc.capture_id
                       WHERE rsgc.group_id=sg.id AND COALESCE(rcr.user_reject, 0)=0
                   ) THEN 1 ELSE 0 END) AS pending_count
              FROM similarity_groups sg
              JOIN bursts b ON b.id=sg.burst_id
              JOIN events e ON e.id=b.event_id
             GROUP BY e.id
             ORDER BY pending_count DESC, total_count DESC, e.start_at DESC
            """
        ).fetchall()
        filtered_count = connection.execute(
            f"""SELECT COUNT(*) FROM similarity_groups sg
                JOIN bursts b ON b.id=sg.burst_id
                WHERE {review_condition}{album_filter}""",
            count_parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"""
            SELECT sg.id, sg.capture_count, sg.max_adjacent_hamming,
                   b.start_at, b.end_at, e.id AS event_id,
                   e.proposed_name AS event_name, e.category,
                   ROUND(AVG(qm.technical_score), 1) AS average_score,
                   MAX(CASE WHEN cr.auto_pick = 1 THEN c.id END) AS recommended_capture_id,
                   MAX(CASE WHEN cr.auto_pick = 1 THEN c.stem END) AS recommended_stem,
                   MIN(CASE WHEN sgc.sequence_index = 0 THEN c.id END) AS cover_capture_id,
                   SUM(CASE WHEN COALESCE(cr.user_pick, 0)=1 THEN 1 ELSE 0 END) AS pick_count,
                   SUM(CASE WHEN COALESCE(cr.user_reject, 0)=1 THEN 1 ELSE 0 END) AS reject_count
            FROM similarity_groups sg
            JOIN bursts b ON b.id = sg.burst_id
            JOIN events e ON e.id = b.event_id
            JOIN similarity_group_captures sgc ON sgc.group_id = sg.id
            JOIN captures c ON c.id = sgc.capture_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id AND qm.error IS NULL
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            WHERE {review_condition} {album_filter}
            GROUP BY sg.id
            ORDER BY sg.capture_count DESC, b.start_at DESC
            LIMIT ? OFFSET ?
            """,
            (*count_parameters, limit, offset),
        ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["thumbnail_url"] = f"/api/thumbnails/{item['cover_capture_id']}?size=320"
            item["review_status"] = (
                "picked" if item["pick_count"] else
                "skipped" if item["reject_count"] >= item["capture_count"] else "pending"
            )
        return {
            "count": filtered_count,
            "limit": limit,
            "offset": offset,
            "items": items,
            "total_count": total,
            "pending_count": pending_count,
            "albums": [dict(row) for row in album_rows],
        }
    finally:
        connection.close()


def query_similarity_group(database_path: Path, group_id: int) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        group = connection.execute(
            """
            SELECT sg.id, sg.capture_count, sg.max_adjacent_hamming,
                   b.start_at, b.end_at, e.proposed_name AS event_name, e.category
            FROM similarity_groups sg
            JOIN bursts b ON b.id = sg.burst_id
            JOIN events e ON e.id = b.event_id
            WHERE sg.id = ?
            """,
            (group_id,),
        ).fetchone()
        if group is None:
            raise ValueError("相似组不存在")
        rows = connection.execute(
            """
            SELECT c.id AS capture_id, c.stem, c.captured_at, sgc.sequence_index,
                   sgc.distance_from_previous, qm.technical_score,
                   qm.exposure_score, qm.sharpness_score, qm.exif_score,
                   qm.issue_json, cr.auto_rating, cr.auto_pick, cr.similarity_rank,
                   cr.user_rating, cr.user_pick, cr.user_reject, cr.user_note,
                   sgo.action AS grouping_override, sgo.manual_batch_key,
                   f.exposure_time, f.f_number, f.iso, f.focal_length_mm,
                   f.focal_length_35mm, f.camera_model, f.lens_model
            FROM similarity_group_captures sgc
            JOIN captures c ON c.id = sgc.capture_id
            JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
              AND cf.file_id = (SELECT MIN(cf2.file_id) FROM capture_files cf2
                                JOIN files f2 ON f2.id = cf2.file_id
                                WHERE cf2.capture_id=c.id AND cf2.role='jpeg' AND f2.present=1)
            JOIN files f ON f.id = cf.file_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            LEFT JOIN similarity_group_overrides sgo ON sgo.capture_id = c.id
            WHERE sgc.group_id = ? ORDER BY sgc.sequence_index
            """,
            (group_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            raw_issues = item.pop("issue_json")
            item["issues"] = json.loads(raw_issues) if raw_issues else []
            item["thumbnail_url"] = f"/api/thumbnails/{item['capture_id']}?size=640"
            items.append(item)
        ranked = sorted(
            (item for item in items if item["technical_score"] is not None),
            key=lambda item: (
                item["similarity_rank"] is None,
                item["similarity_rank"] or 10_000,
                -float(item["technical_score"]),
                item["sequence_index"],
            ),
        )
        best = ranked[0] if ranked else None
        runner_up = ranked[1] if len(ranked) > 1 else None
        component_labels = (
            ("sharpness_score", "清晰度"),
            ("exposure_score", "曝光"),
            ("exif_score", "参数稳健性"),
        )
        for item in items:
            item["score_gap"] = None
            item["recommendation_reason"] = "等待技术评分"
            if best is None or item["technical_score"] is None:
                continue
            if item["capture_id"] == best["capture_id"]:
                comparison = runner_up
                if comparison is None:
                    item["recommendation_reason"] = "组内唯一已评分照片"
                    continue
                advantages = [
                    (float(item[field]) - float(comparison[field]), label)
                    for field, label in component_labels
                    if item[field] is not None and comparison[field] is not None
                ]
                strongest = max(advantages, default=(0.0, ""))
                item["recommendation_reason"] = (
                    f"组内技术分最高，{strongest[1]}领先 {strongest[0]:.0f} 分"
                    if strongest[0] >= 1 else "组内技术分最高"
                )
                continue
            gap = max(0.0, float(best["technical_score"]) - float(item["technical_score"]))
            item["score_gap"] = round(gap, 1)
            differences = [
                (float(best[field]) - float(item[field]), label)
                for field, label in component_labels
                if best[field] is not None and item[field] is not None
            ]
            strongest = max(differences, default=(0.0, ""))
            item["recommendation_reason"] = (
                f"较推荐片{strongest[1]}低 {strongest[0]:.0f} 分"
                if strongest[0] >= 1 else f"较推荐片技术分低 {gap:.1f} 分"
            )
        return {**dict(group), "items": items}
    finally:
        connection.close()
