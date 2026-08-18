from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .database import SCHEMA_VERSION
from .equipment import _empty_inventory, _load_inventory, _write_inventory
from .inventory import utc_now

FORMAT = "tangerine-human-data"
FORMAT_VERSION = 1
RESTORE_CONFIRMATION = "恢复人工数据"


def _rows(connection: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql).fetchall()]


def build_portable_backup(connection: sqlite3.Connection, inventory_path: Path) -> dict[str, Any]:
    return {
        "format": FORMAT, "format_version": FORMAT_VERSION,
        "source_schema": SCHEMA_VERSION, "created_at": utc_now(),
        "privacy": {"contains_photos": False, "contains_absolute_paths": False,
                    "contains_gps": False, "contains_model_results": False},
        "reviews": _rows(connection, """SELECT c.capture_key, r.user_rating, r.user_pick,
            r.user_reject, r.user_note, r.selection_reason_json, r.updated_at
            FROM capture_reviews r JOIN captures c ON c.id=r.capture_id
            WHERE r.user_rating IS NOT NULL OR r.user_pick IS NOT NULL OR r.user_reject=1
               OR r.user_note IS NOT NULL OR r.selection_reason_json IS NOT NULL"""),
        "tags": _rows(connection, """SELECT c.capture_key, d.dimension, d.name, t.source,
            t.confidence, t.created_at FROM capture_tags t
            JOIN captures c ON c.id=t.capture_id JOIN tag_definitions d ON d.id=t.tag_id
            WHERE t.source IN ('manual','import')"""),
        "grouping": _rows(connection, """SELECT c.capture_key, o.action,
            o.manual_batch_key, o.manual_group_key, o.created_at, o.updated_at
            FROM similarity_group_overrides o JOIN captures c ON c.id=o.capture_id"""),
        "edit_recipes": _rows(connection, """SELECT c.capture_key, r.parameter_space,
            r.parameters_json, r.status, r.note, r.created_at
            FROM edit_recipe_revisions r JOIN captures c ON c.id=r.capture_id ORDER BY r.id"""),
        "ai_reviews": _rows(connection, """SELECT c.capture_key, a.model_id,
            a.prompt_version, a.user_verdict, a.user_note, a.reviewed_at
            FROM ai_analyses a JOIN captures c ON c.id=a.capture_id
            WHERE a.user_verdict IS NOT NULL OR a.user_note IS NOT NULL"""),
        "equipment": _load_inventory(inventory_path),
    }


def write_portable_backup(connection: sqlite3.Connection, inventory_path: Path, reports: Path) -> dict[str, Any]:
    data = build_portable_backup(connection, inventory_path)
    reports.mkdir(parents=True, exist_ok=True)
    name = f"tangerine-human-data-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.json"
    path = reports / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"filename": name, "size_bytes": path.stat().st_size, "summary": backup_summary(data)}


def _validate(data: dict[str, Any]) -> None:
    if data.get("format") != FORMAT or data.get("format_version") != FORMAT_VERSION:
        raise ValueError("不是受支持的 Tangerine 人工数据备份")
    data.setdefault("ai_reviews", [])
    for key in ("reviews", "tags", "grouping", "edit_recipes", "ai_reviews"):
        if not isinstance(data.get(key), list) or len(data[key]) > 1_000_000:
            raise ValueError(f"备份字段无效：{key}")
    if not isinstance(data.get("equipment", {}), dict):
        raise ValueError("设备备份字段无效")


def backup_summary(data: dict[str, Any]) -> dict[str, int]:
    return {key: len(data.get(key, [])) for key in ("reviews", "tags", "grouping", "edit_recipes", "ai_reviews")}


def preflight_restore(connection: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    _validate(data)
    keys = {str(row.get("capture_key", "")) for section in ("reviews", "tags", "grouping", "edit_recipes", "ai_reviews") for row in data[section]}
    existing = set()
    for batch_start in range(0, len(keys), 500):
        batch = list(keys)[batch_start:batch_start + 500]
        if batch:
            existing.update(row[0] for row in connection.execute(
                f"SELECT capture_key FROM captures WHERE capture_key IN ({','.join('?' for _ in batch)})", batch))
    return {"valid": True, "summary": backup_summary(data), "capture_keys": len(keys),
            "matched_captures": len(keys & existing), "missing_captures": len(keys - existing),
            "equipment_included": bool(data.get("equipment")), "confirmation": RESTORE_CONFIRMATION}


def restore_portable_backup(connection: sqlite3.Connection, data: dict[str, Any], inventory_path: Path, backup_root: Path, confirmation: str) -> dict[str, Any]:
    if confirmation != RESTORE_CONFIRMATION:
        raise ValueError(f"请输入确认文字：{RESTORE_CONFIRMATION}")
    preflight = preflight_restore(connection, data)
    backup_root.mkdir(parents=True, exist_ok=True)
    db_backup = backup_root / f"catalog-before-human-restore-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.sqlite3"
    destination = sqlite3.connect(db_backup)
    try:
        connection.backup(destination); destination.commit()
        if destination.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise RuntimeError("恢复前数据库备份校验失败")
    finally:
        destination.close()
    capture_ids = {row["capture_key"]: row["id"] for row in connection.execute("SELECT id,capture_key FROM captures")}
    now = utc_now()
    try:
        connection.execute("BEGIN")
        for row in data["reviews"]:
            capture_id = capture_ids.get(row.get("capture_key"))
            if capture_id is None: continue
            connection.execute("""INSERT INTO capture_reviews(capture_id,user_rating,user_pick,user_reject,user_note,selection_reason_json,updated_at)
                VALUES (?,?,?,?,?,?,?) ON CONFLICT(capture_id) DO UPDATE SET user_rating=excluded.user_rating,user_pick=excluded.user_pick,
                user_reject=excluded.user_reject,user_note=excluded.user_note,selection_reason_json=excluded.selection_reason_json,updated_at=excluded.updated_at""",
                (capture_id,row.get("user_rating"),row.get("user_pick"),int(bool(row.get("user_reject"))),row.get("user_note"),row.get("selection_reason_json"),row.get("updated_at") or now))
        tag_capture_ids = {capture_ids[row.get("capture_key")] for row in data["tags"] if row.get("capture_key") in capture_ids}
        for capture_id in tag_capture_ids:
            connection.execute("DELETE FROM capture_tags WHERE capture_id=? AND source IN ('manual','import')", (capture_id,))
        for row in data["tags"]:
            capture_id = capture_ids.get(row.get("capture_key")); source = row.get("source")
            if capture_id is None or source not in {"manual", "import"}: continue
            connection.execute("INSERT OR IGNORE INTO tag_definitions(dimension,name,built_in,sort_order,created_at) VALUES (?,?,0,100,?)", (row.get("dimension"),row.get("name"),now))
            tag_id = connection.execute("SELECT id FROM tag_definitions WHERE dimension=? AND name=?", (row.get("dimension"),row.get("name"))).fetchone()[0]
            connection.execute("INSERT INTO capture_tags(capture_id,tag_id,source,confidence,created_at) VALUES (?,?,?,?,?)", (capture_id,tag_id,source,row.get("confidence"),row.get("created_at") or now))
        grouping_ids = {capture_ids[row.get("capture_key")] for row in data["grouping"] if row.get("capture_key") in capture_ids}
        for capture_id in grouping_ids: connection.execute("DELETE FROM similarity_group_overrides WHERE capture_id=?", (capture_id,))
        for row in data["grouping"]:
            capture_id = capture_ids.get(row.get("capture_key")); action = row.get("action")
            if capture_id is None or action not in {"exclude", "split_before"}: continue
            connection.execute("INSERT INTO similarity_group_overrides(capture_id,action,created_at,updated_at,manual_batch_key,manual_group_key) VALUES (?,?,?,?,?,?)", (capture_id,action,row.get("created_at") or now,row.get("updated_at") or now,row.get("manual_batch_key"),row.get("manual_group_key")))
        recipe_ids = {capture_ids[row.get("capture_key")] for row in data["edit_recipes"] if row.get("capture_key") in capture_ids}
        for capture_id in recipe_ids: connection.execute("DELETE FROM edit_recipe_revisions WHERE capture_id=?", (capture_id,))
        for row in data["edit_recipes"]:
            capture_id = capture_ids.get(row.get("capture_key"))
            if capture_id is None: continue
            connection.execute("INSERT INTO edit_recipe_revisions(capture_id,source_analysis_id,parameter_space,parameters_json,status,note,created_at) VALUES (?,NULL,?,?,?,?,?)", (capture_id,row.get("parameter_space"),row.get("parameters_json"),row.get("status"),row.get("note"),row.get("created_at") or now))
        for row in data["ai_reviews"]:
            capture_id = capture_ids.get(row.get("capture_key"))
            if capture_id is None: continue
            match = connection.execute("""SELECT id FROM ai_analyses WHERE capture_id=? AND model_id=? AND prompt_version=?
                ORDER BY finished_at DESC,id DESC LIMIT 1""", (capture_id,row.get("model_id"),row.get("prompt_version"))).fetchone()
            if match is not None:
                connection.execute("UPDATE ai_analyses SET user_verdict=?,user_note=?,reviewed_at=? WHERE id=?", (row.get("user_verdict"),row.get("user_note"),row.get("reviewed_at") or now,match[0]))
        inventory = _empty_inventory(); supplied = data.get("equipment", {})
        for container in inventory:
            if container == "version": continue
            for kind in inventory[container]:
                if isinstance(supplied.get(container, {}).get(kind), type(inventory[container][kind])):
                    inventory[container][kind] = supplied[container][kind]
        _write_inventory(inventory_path, inventory)
        connection.commit()
    except BaseException:
        connection.rollback(); raise
    return {**preflight, "restored": True, "database_backup": str(db_backup)}
