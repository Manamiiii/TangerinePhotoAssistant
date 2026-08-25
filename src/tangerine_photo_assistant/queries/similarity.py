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
    confidence_filter: str = "all",
    age_filter: str = "all",
) -> dict[str, Any]:
    if confidence_filter not in {"all", "high", "medium", "low"}:
        raise ValueError("相似组置信度筛选无效")
    if age_filter not in {"all", "recent", "month", "older"}:
        raise ValueError("相似组拍摄时间筛选无效")
    connection = connect_readonly(database_path)
    try:
        album_filter = " AND event_id=?" if album_id is not None else ""
        count_parameters = (album_id,) if album_id is not None else ()
        facts_cte = """
            WITH group_facts AS (
                SELECT sg.id, sg.capture_count, sg.max_adjacent_hamming,
                       b.start_at, b.end_at, e.id AS event_id,
                       e.proposed_name AS event_name, e.category,
                       ROUND(AVG(qm.technical_score), 1) AS average_score,
                       MAX(CASE WHEN cr.auto_pick = 1 THEN c.id END)
                           AS recommended_capture_id,
                       MAX(CASE WHEN cr.auto_pick = 1 THEN c.stem END)
                           AS recommended_stem,
                       MIN(CASE WHEN sgc.sequence_index = 0 THEN c.id END)
                           AS cover_capture_id,
                       SUM(CASE WHEN COALESCE(cr.user_pick, 0)=1 THEN 1 ELSE 0 END)
                           AS pick_count,
                       SUM(CASE WHEN COALESCE(cr.user_reject, 0)=1 THEN 1 ELSE 0 END)
                           AS reject_count,
                       SUM(CASE WHEN qm.technical_score IS NOT NULL THEN 1 ELSE 0 END)
                           AS analyzed_count,
                       SUM(CASE WHEN COALESCE(cr.auto_pick, 0)=1 THEN 1 ELSE 0 END)
                           AS auto_pick_count,
                       MAX(CASE WHEN cr.auto_pick=1 THEN qm.technical_score END)
                           AS recommended_score,
                       MAX(CASE WHEN cr.auto_pick=1
                                THEN COALESCE(cr.user_reject,0) END)
                           AS recommended_reject,
                       MAX(CASE WHEN COALESCE(cr.auto_pick, 0)=0
                                THEN qm.technical_score END) AS runner_up_score,
                       SUM(CASE WHEN sgo.capture_id IS NOT NULL THEN 1 ELSE 0 END)
                           AS override_count,
                       MAX(0, CAST(julianday('now') -
                           julianday(COALESCE(b.end_at, b.start_at)) AS INTEGER))
                           AS pending_age_days
                  FROM similarity_groups sg
                  JOIN bursts b ON b.id=sg.burst_id
                  JOIN events e ON e.id=b.event_id
                  JOIN similarity_group_captures sgc ON sgc.group_id=sg.id
                  JOIN captures c ON c.id=sgc.capture_id
                  LEFT JOIN quality_metrics qm
                    ON qm.capture_id=c.id AND qm.error IS NULL
                  LEFT JOIN capture_reviews cr ON cr.capture_id=c.id
                  LEFT JOIN similarity_group_overrides sgo ON sgo.capture_id=c.id
                 GROUP BY sg.id
            )
        """
        pending_condition = "pick_count=0 AND reject_count<capture_count"
        completed_condition = f"NOT ({pending_condition})"
        adjusted_condition = "override_count>0"
        review_condition = {
            "pending": pending_condition,
            "completed": completed_condition,
            "adjusted": adjusted_condition,
        }.get(review_filter, "1=1")
        confidence_case = """CASE
            WHEN auto_pick_count=1 AND analyzed_count=capture_count
             AND recommended_reject=0 AND override_count=0
             AND max_adjacent_hamming<=8
             AND recommended_score>=75
             AND (runner_up_score IS NULL OR recommended_score-runner_up_score>=5)
              THEN 'high'
            WHEN auto_pick_count=1 AND analyzed_count=capture_count
             AND recommended_reject=0 AND max_adjacent_hamming<=14 THEN 'medium'
            ELSE 'low' END"""
        confidence_condition = (
            "1=1" if confidence_filter == "all"
            else f"({confidence_case})='{confidence_filter}'"
        )
        age_condition = {
            "all": "1=1", "recent": "pending_age_days<30",
            "month": "pending_age_days>=30 AND pending_age_days<180",
            "older": "pending_age_days>=180",
        }[age_filter]
        summary = connection.execute(
            f"""{facts_cte}
            SELECT COUNT(*) AS total_count,
                   SUM(CASE WHEN {pending_condition} THEN 1 ELSE 0 END)
                       AS pending_count,
                   SUM(CASE WHEN {review_condition} AND {confidence_condition}
                                  AND {age_condition} THEN 1 ELSE 0 END)
                       AS filtered_count,
                   SUM(CASE WHEN {pending_condition}
                                  AND ({confidence_case})='high' THEN 1 ELSE 0 END)
                       AS high_count,
                   SUM(CASE WHEN {pending_condition}
                                  AND ({confidence_case})='medium' THEN 1 ELSE 0 END)
                       AS medium_count,
                   SUM(CASE WHEN {pending_condition}
                                  AND ({confidence_case})='low' THEN 1 ELSE 0 END)
                       AS low_count
              FROM group_facts WHERE 1=1{album_filter}""",
            count_parameters,
        ).fetchone()
        total = int(summary["total_count"] or 0)
        pending_count = int(summary["pending_count"] or 0)
        review_timing = connection.execute(
            """SELECT AVG(active_seconds)
               FROM selection_sessions
               WHERE status='completed' AND active_seconds > 0"""
        ).fetchone()[0]
        seconds_per_group = max(15.0, min(float(review_timing or 30.0), 300.0))
        album_rows = connection.execute(
            f"""{facts_cte}
            SELECT event_id AS id, event_name AS name, category,
                   COUNT(*) AS total_count,
                   SUM(CASE WHEN {pending_condition} THEN 1 ELSE 0 END)
                       AS pending_count
              FROM group_facts GROUP BY event_id
             ORDER BY pending_count DESC, total_count DESC, start_at DESC"""
        ).fetchall()
        filtered_count = int(summary["filtered_count"] or 0)
        rows = connection.execute(
            f"""
            {facts_cte}
            SELECT *, ({confidence_case}) AS confidence_level
            FROM group_facts
            WHERE {review_condition} AND {confidence_condition}
              AND {age_condition} {album_filter}
            ORDER BY CASE ({confidence_case}) WHEN 'low' THEN 0
                         WHEN 'medium' THEN 1 ELSE 2 END,
                     pending_age_days DESC, capture_count DESC, start_at DESC
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
            "estimated_review_minutes": round(pending_count * seconds_per_group / 60),
            "estimate_basis": (
                "completed_sessions" if review_timing is not None else "default_30_seconds"
            ),
            "albums": [dict(row) for row in album_rows],
            "confidence_counts": {
                "high": int(summary["high_count"] or 0),
                "medium": int(summary["medium_count"] or 0),
                "low": int(summary["low_count"] or 0),
            },
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
                   cr.selection_reason_json,
                   sgo.action AS grouping_override, sgo.manual_batch_key,
                   vf.dhash64, vf.mean_r, vf.mean_g, vf.mean_b,
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
            LEFT JOIN visual_fingerprints vf ON vf.capture_id = c.id AND vf.error IS NULL
            WHERE sgc.group_id = ? ORDER BY sgc.sequence_index
            """,
            (group_id,),
        ).fetchall()
        items = []
        for row in rows:
            item = dict(row)
            raw_issues = item.pop("issue_json")
            item["issues"] = json.loads(raw_issues) if raw_issues else []
            raw_selection_reasons = item.pop("selection_reason_json")
            item["selection_reasons"] = (
                json.loads(raw_selection_reasons) if raw_selection_reasons else []
            )
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
            item["recommendation_tier"] = "unrated"
            if best is None or item["technical_score"] is None:
                continue
            if item["capture_id"] == best["capture_id"]:
                item["recommendation_tier"] = "best"
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
                    f"组内技术健康度最高，{strongest[1]}领先 {strongest[0]:.0f} 分"
                    if strongest[0] >= 1 else "组内技术健康度最高"
                )
                continue
            gap = max(0.0, float(best["technical_score"]) - float(item["technical_score"]))
            item["score_gap"] = round(gap, 1)
            item["recommendation_tier"] = (
                "alternative" if gap <= 5
                else "weak" if gap >= 10 and float(item["technical_score"]) < 70
                else "candidate"
            )
            differences = [
                (float(best[field]) - float(item[field]), label)
                for field, label in component_labels
                if best[field] is not None and item[field] is not None
            ]
            strongest = max(differences, default=(0.0, ""))
            item["recommendation_reason"] = (
                f"较推荐片{strongest[1]}低 {strongest[0]:.0f} 分"
                if strongest[0] >= 1 else f"较推荐片技术健康度低 {gap:.1f} 分"
            )
        _add_diversity_recommendations(items, best)
        for item in items:
            for internal_key in ("dhash64", "mean_r", "mean_g", "mean_b"):
                item.pop(internal_key, None)
        return {**dict(group), "items": items}
    finally:
        connection.close()


def _fingerprint_difference(left: dict[str, Any], right: dict[str, Any]) -> float | None:
    """Return a conservative 0-100 visual difference from existing JPEG fingerprints."""
    if not left.get("dhash64") or not right.get("dhash64"):
        return None
    try:
        hamming = (int(left["dhash64"], 16) ^ int(right["dhash64"], 16)).bit_count()
    except (TypeError, ValueError):
        return None
    color_values = (
        left.get("mean_r"), left.get("mean_g"), left.get("mean_b"),
        right.get("mean_r"), right.get("mean_g"), right.get("mean_b"),
    )
    color_distance = 0.0
    if all(value is not None for value in color_values):
        color_distance = sum(
            abs(float(left[channel]) - float(right[channel]))
            for channel in ("mean_r", "mean_g", "mean_b")
        ) / 7.65
    return round(min(100.0, hamming / 64.0 * 85.0 + color_distance * 0.15), 1)


def _add_diversity_recommendations(
    items: list[dict[str, Any]], best: dict[str, Any] | None
) -> None:
    """Add an optional stable review order; never changes automatic or manual picks."""
    for item in items:
        item["visual_difference"] = None
        item["diversity_candidate"] = False
        item["diversity_reason"] = None
        item["balanced_rank"] = item.get("similarity_rank")
    if best is None:
        return

    best_score = float(best["technical_score"])
    scored: list[tuple[dict[str, Any], float]] = []
    for item in items:
        if item["capture_id"] == best["capture_id"]:
            item["visual_difference"] = 0.0
            scored.append((item, 10_000.0))
            continue
        difference = _fingerprint_difference(best, item)
        item["visual_difference"] = difference
        technical = float(item["technical_score"]) if item["technical_score"] is not None else -1.0
        # A difference can lift a technically close alternative, but cannot rescue a weak frame.
        viable = technical >= 70 and best_score - technical <= 10
        bonus = min(difference or 0.0, 40.0) * 0.22 if viable else 0.0
        scored.append((item, technical + bonus))

    ordered = sorted(
        scored,
        key=lambda entry: (
            entry[0]["capture_id"] != best["capture_id"],
            -entry[1],
            entry[0].get("similarity_rank") or 10_000,
            entry[0]["sequence_index"],
        ),
    )
    for rank, (item, _) in enumerate(ordered, start=1):
        item["balanced_rank"] = rank

    alternatives = [
        item for item in items
        if item["capture_id"] != best["capture_id"]
        and item["technical_score"] is not None
        and float(item["technical_score"]) >= 70
        and best_score - float(item["technical_score"]) <= 10
        and item["visual_difference"] is not None
    ]
    if len(items) < 3 or not alternatives:
        return
    candidate = max(
        alternatives,
        key=lambda item: (item["visual_difference"], -item["sequence_index"]),
    )
    if float(candidate["visual_difference"]) < 10:
        return
    candidate["diversity_candidate"] = True
    candidate["diversity_reason"] = (
        f"与技术最佳画面差异 {candidate['visual_difference']:.0f}%，"
        "可人工复核动作、表情或构图差异"
    )
