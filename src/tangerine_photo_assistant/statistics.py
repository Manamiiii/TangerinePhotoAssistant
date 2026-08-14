from __future__ import annotations

import sqlite3
from typing import Any

from .critique import classify_repairability

CAPTURE_CTE = """
WITH capture_exif AS (
    SELECT c.id, c.captured_at, e.category, e.id AS event_id,
           f.camera_model, f.lens_model, f.exposure_time, f.f_number, f.iso,
           f.focal_length_mm, f.focal_length_35mm, f.exposure_compensation,
           qm.technical_score, cr.auto_rating, cr.user_rating,
           cr.user_pick, cr.user_reject
    FROM captures c
    JOIN event_captures ec ON ec.capture_id = c.id
    JOIN events e ON e.id = ec.event_id
    JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
      AND cf.file_id = (SELECT MIN(cf2.file_id) FROM capture_files cf2
                        JOIN files f2 ON f2.id = cf2.file_id
                        WHERE cf2.capture_id=c.id AND cf2.role='jpeg' AND f2.present=1)
    JOIN files f ON f.id = cf.file_id
    LEFT JOIN quality_metrics qm ON qm.capture_id = c.id AND qm.error IS NULL
    LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
)
"""


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(CAPTURE_CTE + sql).fetchall()]


def build_statistics(connection: sqlite3.Connection) -> dict[str, Any]:
    summary = connection.execute(
        CAPTURE_CTE
        + """
        SELECT COUNT(*) AS capture_count, MIN(captured_at) AS first_capture,
               MAX(captured_at) AS last_capture,
               COUNT(DISTINCT CASE WHEN captured_at IS NOT NULL
                                    THEN substr(captured_at, 1, 10) END) AS shooting_days,
               COUNT(DISTINCT event_id) AS album_count,
               COUNT(technical_score) AS quality_analyzed,
               ROUND(AVG(technical_score), 2) AS average_technical_score,
               SUM(CASE WHEN user_pick = 1 THEN 1 ELSE 0 END) AS user_picks,
               SUM(CASE WHEN user_reject = 1 THEN 1 ELSE 0 END) AS user_rejects
        FROM capture_exif
        """
    ).fetchone()
    issues = [dict(row) for row in connection.execute(
        """
        SELECT json_extract(issue.value, '$.code') AS code,
               json_extract(issue.value, '$.message') AS message,
               COUNT(*) AS count
        FROM quality_metrics qm, json_each(qm.issue_json) issue
        WHERE qm.error IS NULL
        GROUP BY code, message ORDER BY count DESC
        """
    ).fetchall()]
    selection_benchmark = dict(connection.execute(
        """WITH group_results AS (
               SELECT sg.id,
                      MAX(CASE WHEN COALESCE(cr.user_pick, 0)=1 THEN 1 ELSE 0 END) AS has_pick,
                      MAX(CASE WHEN COALESCE(cr.user_pick, 0)=1
                                    AND COALESCE(cr.auto_pick, 0)=1 THEN 1 ELSE 0 END) AS top1_hit,
                      MAX(CASE WHEN COALESCE(cr.user_pick, 0)=1
                                    AND cr.similarity_rank<=2 THEN 1 ELSE 0 END) AS top2_hit
               FROM similarity_groups sg
               JOIN similarity_group_captures sgc ON sgc.group_id=sg.id
               LEFT JOIN capture_reviews cr ON cr.capture_id=sgc.capture_id
               GROUP BY sg.id
           )
           SELECT SUM(has_pick) AS reviewed_groups,
                  SUM(CASE WHEN has_pick=1 THEN top1_hit ELSE 0 END) AS top1_hits,
                  SUM(CASE WHEN has_pick=1 THEN top2_hit ELSE 0 END) AS top2_hits,
                  ROUND(100.0 * SUM(CASE WHEN has_pick=1 THEN top1_hit ELSE 0 END)
                        / NULLIF(SUM(has_pick), 0), 1) AS top1_rate,
                  ROUND(100.0 * SUM(CASE WHEN has_pick=1 THEN top2_hit ELSE 0 END)
                        / NULLIF(SUM(has_pick), 0), 1) AS top2_rate
           FROM group_results"""
    ).fetchone())
    selection_reasons = [dict(row) for row in connection.execute(
        """SELECT reason.value AS reason, COUNT(DISTINCT cr.capture_id) AS count
           FROM capture_reviews cr,
                json_each(COALESCE(cr.selection_reason_json, '[]')) AS reason
           WHERE COALESCE(cr.user_pick, 0)=1
           GROUP BY reason.value
           ORDER BY count DESC, reason.value"""
    ).fetchall()]
    shooting_review_summary = dict(connection.execute(
        """WITH latest AS (
               SELECT aa.result_json
               FROM ai_analyses aa
               WHERE aa.status='complete' AND aa.result_json IS NOT NULL
                 AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                            WHERE newest.capture_id=aa.capture_id
                              AND newest.status='complete')
           )
           SELECT COUNT(*) AS reviewed_captures,
                  SUM(CASE WHEN json_array_length(json_extract(result_json, '$.visible_problems'))>0 THEN 1 ELSE 0 END) AS with_observations,
                  SUM(CASE WHEN json_array_length(json_extract(result_json, '$.shooting_advice'))>0 THEN 1 ELSE 0 END) AS with_next_time,
                  SUM(CASE WHEN json_array_length(json_extract(result_json, '$.lightroom_suggestions'))>0 THEN 1 ELSE 0 END) AS with_editing,
                  ROUND(AVG(CAST(json_extract(result_json, '$.overall_confidence') AS REAL))*100, 1) AS average_confidence
           FROM latest"""
    ).fetchone())
    shooting_review_problems = []
    for row in connection.execute(
        """WITH latest AS (
               SELECT aa.capture_id, aa.result_json
               FROM ai_analyses aa
               WHERE aa.status='complete' AND aa.result_json IS NOT NULL
                 AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                            WHERE newest.capture_id=aa.capture_id
                              AND newest.status='complete')
           )
           SELECT json_extract(problem.value, '$.name') AS problem,
                  COUNT(DISTINCT latest.capture_id) AS count,
                  ROUND(AVG(CAST(json_extract(problem.value, '$.confidence') AS REAL))*100, 1) AS average_confidence
           FROM latest, json_each(json_extract(latest.result_json, '$.visible_problems')) problem
           WHERE json_extract(problem.value, '$.name') IS NOT NULL
           GROUP BY problem ORDER BY count DESC, problem LIMIT 12"""
    ).fetchall():
        item = dict(row)
        item["repairability"], item["repairability_label"] = classify_repairability(
            str(item["problem"])
        )
        shooting_review_problems.append(item)
    return {
        "summary": dict(summary),
        "selection_benchmark": selection_benchmark,
        "selection_reasons": selection_reasons,
        "shooting_review_summary": shooting_review_summary,
        "shooting_review_problems": shooting_review_problems,
        "categories": _rows(
            connection,
            """SELECT category, COUNT(*) AS count,
                      ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif GROUP BY category ORDER BY count DESC""",
        ),
        "months": _rows(
            connection,
            """SELECT substr(captured_at, 1, 7) AS month, COUNT(*) AS count,
                      ROUND(AVG(technical_score), 1) AS average_score,
                      SUM(CASE WHEN user_pick = 1 THEN 1 ELSE 0 END) AS user_picks
               FROM capture_exif WHERE captured_at IS NOT NULL
               GROUP BY month ORDER BY month""",
        ),
        "cameras": _rows(
            connection,
            """SELECT camera_model, COUNT(*) AS count,
                      ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif
               WHERE camera_model IS NOT NULL AND camera_model != ''
               GROUP BY camera_model ORDER BY count DESC LIMIT 12""",
        ),
        "lenses": _rows(
            connection,
            """SELECT COALESCE(lens_model, '未知镜头') AS lens_model, COUNT(*) AS count,
                      ROUND(AVG(technical_score), 1) AS average_score,
                      SUM(CASE WHEN user_pick = 1 THEN 1 ELSE 0 END) AS user_picks,
                      ROUND(100.0 * SUM(CASE WHEN user_pick = 1 THEN 1 ELSE 0 END)
                            / COUNT(*), 1) AS pick_rate
               FROM capture_exif GROUP BY lens_model ORDER BY count DESC LIMIT 12""",
        ),
        "focal_ranges": _rows(
            connection,
            """SELECT CASE
                    WHEN focal_length_mm IS NULL THEN '未知'
                    WHEN focal_length_mm < 20 THEN '<20mm'
                    WHEN focal_length_mm < 35 THEN '20–34mm'
                    WHEN focal_length_mm < 55 THEN '35–54mm'
                    WHEN focal_length_mm < 100 THEN '55–99mm'
                    WHEN focal_length_mm < 200 THEN '100–199mm'
                    ELSE '≥200mm' END AS bucket,
                    COUNT(*) AS count, ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif GROUP BY bucket ORDER BY MIN(COALESCE(focal_length_mm, 9999))""",
        ),
        "iso_ranges": _rows(
            connection,
            """SELECT CASE
                    WHEN iso IS NULL THEN '未知'
                    WHEN iso <= 200 THEN '≤200'
                    WHEN iso <= 800 THEN '201–800'
                    WHEN iso <= 1600 THEN '801–1600'
                    WHEN iso <= 3200 THEN '1601–3200'
                    WHEN iso <= 6400 THEN '3201–6400'
                    ELSE '>6400' END AS bucket,
                    COUNT(*) AS count, ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif GROUP BY bucket ORDER BY MIN(COALESCE(iso, 999999))""",
        ),
        "aperture_ranges": _rows(
            connection,
            """SELECT CASE
                    WHEN f_number IS NULL THEN '未知'
                    WHEN f_number < 2 THEN '<f/2'
                    WHEN f_number < 2.9 THEN 'f/2–2.8'
                    WHEN f_number < 4.5 THEN 'f/2.9–4'
                    WHEN f_number < 8.5 THEN 'f/4.1–8'
                    ELSE '>f/8' END AS bucket,
                    COUNT(*) AS count, ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif GROUP BY bucket ORDER BY MIN(COALESCE(f_number, 99))""",
        ),
        "shutter_ranges": _rows(
            connection,
            """SELECT CASE
                    WHEN exposure_time IS NULL THEN '未知'
                    WHEN exposure_time <= 0.001 THEN '≥1/1000s'
                    WHEN exposure_time <= 0.004 THEN '1/999–1/250s'
                    WHEN exposure_time <= 0.008 THEN '1/249–1/125s'
                    WHEN exposure_time <= 1.0/60 THEN '1/124–1/60s'
                    WHEN exposure_time <= 1.0/15 THEN '1/59–1/15s'
                    ELSE '慢于1/15s' END AS bucket,
                    COUNT(*) AS count, ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif GROUP BY bucket
               ORDER BY MIN(COALESCE(exposure_time, 9999))""",
        ),
        "exposure_compensation_ranges": _rows(
            connection,
            """SELECT CASE
                    WHEN exposure_compensation IS NULL THEN '未知'
                    WHEN exposure_compensation <= -1.0 THEN '≤-1EV'
                    WHEN exposure_compensation < -0.3 THEN '-0.9–-0.4EV'
                    WHEN exposure_compensation <= 0.3 THEN '-0.3–+0.3EV'
                    WHEN exposure_compensation < 1.0 THEN '+0.4–+0.9EV'
                    ELSE '≥+1EV' END AS bucket,
                    COUNT(*) AS count, ROUND(AVG(technical_score), 1) AS average_score
               FROM capture_exif GROUP BY bucket
               ORDER BY MIN(COALESCE(exposure_compensation, 9999))""",
        ),
        "ratings": _rows(
            connection,
            """SELECT COALESCE(user_rating, auto_rating) AS rating, COUNT(*) AS count,
                      SUM(CASE WHEN user_rating IS NOT NULL THEN 1 ELSE 0 END) AS user_rated
               FROM capture_exif WHERE COALESCE(user_rating, auto_rating) IS NOT NULL
               GROUP BY rating ORDER BY rating DESC""",
        ),
        "issues": issues,
    }
