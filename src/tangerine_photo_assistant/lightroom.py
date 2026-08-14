from __future__ import annotations

import csv
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path, PureWindowsPath
from typing import Any

from .settings import Settings

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


def lightroom_preflight(settings: Settings) -> dict[str, Any]:
    root = settings.lightroom_catalog_root
    backup_root = settings.lightroom_catalog_backup_root
    catalogs: list[dict[str, Any]] = []
    if root is not None and root.is_dir():
        for catalog in sorted(root.glob("*.lrcat"), key=lambda item: item.name.casefold()):
            lock = catalog.with_suffix(".lrcat.lock")
            data = catalog.with_suffix(".lrcat-data")
            catalogs.append({
                "name": catalog.name,
                "path": str(catalog),
                "size_bytes": catalog.stat().st_size,
                "locked": lock.is_file(),
                "data_companion": data.is_file(),
            })
    locked_count = sum(int(item["locked"]) for item in catalogs)
    if root is None:
        status, message = "not_configured", "尚未配置 Lightroom 目录"
    elif not root.is_dir():
        status, message = "missing", "配置的 Lightroom 目录不存在"
    elif not catalogs:
        status, message = "no_catalog", "目录中未发现 .lrcat 目录文件"
    elif locked_count:
        status, message = "catalog_open", "检测到目录锁；Lightroom 可能正在使用目录"
    else:
        status, message = "ready_for_review", "目录已发现，可生成只读兼容性计划"
    return {
        "status": status,
        "message": message,
        "catalog_root": str(root) if root is not None else "",
        "catalog_root_exists": bool(root and root.is_dir()),
        "catalogs": catalogs,
        "catalog_count": len(catalogs),
        "locked_count": locked_count,
        "backup_root": str(backup_root) if backup_root is not None else "",
        "backup_root_exists": bool(backup_root and backup_root.is_dir()),
        "xmp_write_enabled": False,
        "catalog_direct_write_supported": False,
        "notes": [
            "不会打开或修改 .lrcat 数据库",
            "RAW 可规划同名 XMP sidecar；JPG 元数据写入会改动文件，因此保持目录内处理",
            "Lightroom Classic 15 可能同时维护 ACR sidecar，当前计划不会生成该文件",
        ],
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
                  AND COALESCE(aa.user_verdict, '')!='inaccurate'
                  AND aa.id=(SELECT MAX(newest.id) FROM ai_analyses newest
                             WHERE newest.capture_id=c.id AND newest.status='complete'))
                   AS ai_subject,
               (SELECT GROUP_CONCAT(portable.name, ';') FROM (
                    SELECT td.name FROM capture_tags ct
                    JOIN tag_definitions td ON td.id=ct.tag_id
                    WHERE ct.capture_id=c.id AND td.active=1
                      AND td.dimension IN ('subject', 'location')
                    ORDER BY td.dimension, td.sort_order, td.name
                ) portable) AS portable_tags
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
        if row["portable_tags"]:
            keywords.extend(str(row["portable_tags"]).split(";"))
        if row["ai_subject"]:
            keywords.append(row["ai_subject"])
        raw_path = Path(row["raw_path"]) if row["raw_path"] else None
        xmp_candidate = raw_path.with_suffix(".xmp") if raw_path else None
        xmp_exists = bool(
            xmp_candidate
            and (xmp_candidate.is_file() or xmp_candidate.with_suffix(".XMP").is_file())
        )
        planned_flag = (
            "picked" if row["user_pick"] else "rejected" if row["user_reject"] else "preserve"
        )
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
            "rating_action": "propose" if rating else "preserve",
            "flag_action": planned_flag,
            "keyword_action": "merge_review",
            "metadata_target": "raw_xmp_sidecar" if raw_path else "catalog_only",
            "xmp_candidate_path": str(xmp_candidate) if xmp_candidate else "",
            "xmp_exists": int(xmp_exists),
            "requires_conflict_review": int(xmp_exists),
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
            "raw_sidecar_candidates": sum(
                row["metadata_target"] == "raw_xmp_sidecar" for row in rows
            ),
            "existing_xmp_count": sum(row["xmp_exists"] for row in rows),
            "conflict_review_count": sum(row["requires_conflict_review"] for row in rows),
        },
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        **payload["summary"],
        "csv_name": csv_path.name,
        "json_name": json_path.name,
    }
