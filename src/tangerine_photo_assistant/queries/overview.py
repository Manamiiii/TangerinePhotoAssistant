from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..database import connect_readonly
from ..reporting import build_report
from ..structure import structure_summary
from ..work_queue import work_queue_summary


def _visual_summary(connection: sqlite3.Connection) -> dict[str, int]:
    duplicate = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(file_count), 0), COALESCE(SUM(total_bytes), 0) "
        "FROM duplicate_groups"
    ).fetchone()
    similarity = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(capture_count), 0), "
        "COALESCE(MAX(capture_count), 0) FROM similarity_groups"
    ).fetchone()
    fingerprints = connection.execute(
        "SELECT COUNT(*), SUM(CASE WHEN error IS NOT NULL THEN 1 ELSE 0 END) "
        "FROM visual_fingerprints"
    ).fetchone()
    return {
        "duplicate_group_count": duplicate[0],
        "duplicate_file_count": duplicate[1],
        "duplicate_total_bytes": duplicate[2],
        "similarity_group_count": similarity[0],
        "captures_in_similarity_groups": similarity[1],
        "largest_similarity_group": similarity[2],
        "fingerprint_count": fingerprints[0],
        "fingerprint_error_count": fingerprints[1] or 0,
    }


def query_overview(database_path: Path, daily_review_budget: int = 30) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        report = build_report(connection)
        latest = connection.execute(
            """
            SELECT id, started_at, finished_at, status, files_seen
            FROM scan_runs ORDER BY id DESC LIMIT 1
            """
        ).fetchone()
        capture_total = connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0]
        dated_captures = connection.execute(
            "SELECT COUNT(*) FROM captures WHERE captured_at IS NOT NULL"
        ).fetchone()[0]
        return {
            **report,
            "capture_total": capture_total,
            "dated_captures": dated_captures,
            "latest_scan": dict(latest) if latest else None,
            "cameras": report["cameras"][:6],
            "lenses": report["lenses"][:8],
            "structure": structure_summary(connection),
            "visual": _visual_summary(connection),
            "work_queue": work_queue_summary(connection, daily_review_budget),
        }
    finally:
        connection.close()


def query_inbox(database_path: Path, limit: int) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        # A no-op incremental scan must not hide the latest batch with new files.
        latest_run = connection.execute(
            "SELECT MAX(first_seen_run_id) FROM files WHERE present = 1"
        ).fetchone()[0]
        if latest_run is None:
            return {"scan_run_id": None, "count": 0, "items": []}
        count = connection.execute(
            """
            SELECT COUNT(DISTINCT cf.capture_id)
            FROM capture_files cf
            JOIN files f ON f.id = cf.file_id
            WHERE f.present = 1 AND f.first_seen_run_id = ?
            """,
            (latest_run,),
        ).fetchone()[0]
        rows = connection.execute(
            """
            SELECT
                c.id, c.parent_relative, c.stem, c.captured_at, c.pairing_status,
                MAX(f.camera_model) AS camera_model,
                MAX(f.lens_model) AS lens_model,
                COUNT(cf.file_id) AS file_count
            FROM captures c
            JOIN capture_files cf ON cf.capture_id = c.id
            JOIN files f ON f.id = cf.file_id
            WHERE f.present = 1 AND f.first_seen_run_id = ?
            GROUP BY c.id
            ORDER BY COALESCE(c.captured_at, '') DESC, c.id DESC
            LIMIT ?
            """,
            (latest_run, limit),
        ).fetchall()
        return {
            "scan_run_id": latest_run,
            "count": count,
            "items": [dict(row) for row in rows],
        }
    finally:
        connection.close()
