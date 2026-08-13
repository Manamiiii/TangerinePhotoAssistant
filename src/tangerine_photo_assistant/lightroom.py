from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

INVALID_COMPONENT = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _safe_component(value: str) -> str:
    cleaned = INVALID_COMPONENT.sub("_", value).strip(" .")
    return cleaned[:120] or "未命名"


def lightroom_status(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        "capture_count": connection.execute(
            "SELECT COUNT(*) FROM event_captures"
        ).fetchone()[0],
        "confirmed_events": connection.execute(
            "SELECT COUNT(*) FROM events WHERE status='confirmed'"
        ).fetchone()[0],
        "event_count": connection.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "rated_captures": connection.execute(
            """SELECT COUNT(*) FROM capture_reviews
               WHERE COALESCE(user_rating, auto_rating) IS NOT NULL"""
        ).fetchone()[0],
        "user_picks": connection.execute(
            "SELECT COUNT(*) FROM capture_reviews WHERE user_pick=1"
        ).fetchone()[0],
        "user_rejects": connection.execute(
            "SELECT COUNT(*) FROM capture_reviews WHERE user_reject=1"
        ).fetchone()[0],
    }


def build_lightroom_rows(
    connection: sqlite3.Connection,
    scope: str = "all",
    album_id: int | None = None,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT c.id AS capture_id, c.captured_at, c.pairing_status, e.id AS event_id,
               e.proposed_name AS event_name, e.category, e.status AS event_status,
               MAX(CASE WHEN cf.role='jpeg' THEN f.path END) AS jpeg_path,
               MAX(CASE WHEN cf.role='raw' THEN f.path END) AS raw_path,
               SUM(f.size_bytes) AS source_bytes,
               cr.auto_rating, cr.user_rating, cr.auto_pick, cr.user_pick,
               cr.user_reject, cr.user_note,
               (SELECT json_extract(aa.result_json, '$.subject_type')
                FROM ai_analyses aa WHERE aa.capture_id=c.id AND aa.status='complete'
                ORDER BY aa.id DESC LIMIT 1) AS ai_subject
        FROM captures c
        JOIN event_captures ec ON ec.capture_id=c.id
        JOIN events e ON e.id=ec.event_id
        JOIN capture_files cf ON cf.capture_id=c.id
        JOIN files f ON f.id=cf.file_id AND f.present=1
        LEFT JOIN capture_reviews cr ON cr.capture_id=c.id
        GROUP BY c.id
        ORDER BY c.captured_at IS NULL, c.captured_at, c.id
        """
    ).fetchall()
    result = []
    for row in rows:
        year = row["captured_at"][:4] if row["captured_at"] else "日期未知"
        target = PureWindowsPath(
            _safe_component(row["category"]), year, _safe_component(row["event_name"])
        )
        rating = row["user_rating"] if row["user_rating"] is not None else row["auto_rating"]
        keywords = [row["category"], row["event_name"]]
        if row["ai_subject"]:
            keywords.append(row["ai_subject"])
        result.append({
            "capture_id": row["capture_id"],
            "event_id": row["event_id"],
            "captured_at": row["captured_at"] or "",
            "event_name": row["event_name"],
            "event_status": row["event_status"],
            "category": row["category"],
            "pairing_status": row["pairing_status"],
            "jpeg_path": row["jpeg_path"] or "",
            "raw_path": row["raw_path"] or "",
            "source_bytes": row["source_bytes"],
            "effective_rating": rating or "",
            "rating_source": "user" if row["user_rating"] is not None else (
                "automatic" if row["auto_rating"] is not None else ""
            ),
            "pick": int(bool(row["user_pick"])),
            "reject_label": int(bool(row["user_reject"])),
            "note": row["user_note"] or "",
            "keywords": ";".join(dict.fromkeys(keywords)),
            "proposed_copy_folder": str(target),
            "write_xmp": 0,
            "copy_or_move_executed": 0,
        })
    if scope == "picked":
        return [row for row in result if row["pick"]]
    if scope == "rated":
        return [row for row in result if row["effective_rating"]]
    if scope == "album":
        if album_id is None:
            raise ValueError("按相册生成时必须提供相册 ID")
        return [row for row in result if row["event_id"] == album_id]
    if scope != "all":
        raise ValueError("不支持的 Lightroom 清单范围")
    return result


def write_lightroom_manifest(
    connection: sqlite3.Connection, reports_path: Path,
    scope: str = "all", album_id: int | None = None,
) -> dict[str, Any]:
    rows = build_lightroom_rows(connection, scope, album_id)
    reports_path.mkdir(parents=True, exist_ok=True)
    csv_path = reports_path / "lightroom-import-plan-latest.csv"
    json_path = reports_path / "lightroom-import-plan-latest.json"
    fields = list(rows[0]) if rows else ["capture_id"]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    payload = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "scope": scope,
        "safety": {
            "source_library_mutated": False,
            "xmp_written": False,
            "copy_or_move_executed": False,
            "purpose": "reviewable Lightroom preparation manifest",
        },
        "summary": {
            "capture_count": len(rows),
            "rated_count": sum(bool(row["effective_rating"]) for row in rows),
            "user_pick_count": sum(row["pick"] for row in rows),
            "user_reject_count": sum(row["reject_label"] for row in rows),
            "source_bytes": sum(row["source_bytes"] for row in rows),
        },
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        **payload["summary"],
        "csv_name": csv_path.name,
        "json_name": json_path.name,
    }
