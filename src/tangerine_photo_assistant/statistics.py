from __future__ import annotations

import sqlite3
from typing import Any

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
    selection = connection.execute(
        """
        SELECT COUNT(*) AS group_total,
               SUM(reviewed) AS groups_reviewed,
               ROUND(AVG(CASE WHEN reviewed = 1 THEN picks END), 2) AS average_picks_per_group
        FROM (
            SELECT sg.id,
                   MAX(CASE WHEN COALESCE(cr.user_pick, 0) = 1
                        OR COALESCE(cr.user_reject, 0) = 1 THEN 1 ELSE 0 END) AS reviewed,
                   SUM(CASE WHEN COALESCE(cr.user_pick, 0) = 1 THEN 1 ELSE 0 END) AS picks
            FROM similarity_groups sg
            JOIN similarity_group_captures sgc ON sgc.group_id = sg.id
            LEFT JOIN capture_reviews cr ON cr.capture_id = sgc.capture_id
            GROUP BY sg.id
        )
        """
    ).fetchone()
    return {
        "summary": dict(summary),
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
        "selection": dict(selection) if selection else None,
    }
