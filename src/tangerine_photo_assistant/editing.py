from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from typing import Any

from .database import transaction
from .inventory import utc_now

PARAMETER_LIMITS: dict[str, tuple[float, float]] = {
    "exposure_ev": (-2.0, 2.0),
    "contrast": (-100.0, 100.0),
    "highlights": (-100.0, 100.0),
    "shadows": (-100.0, 100.0),
    "temperature": (-100.0, 100.0),
    "tint": (-100.0, 100.0),
    "saturation": (-100.0, 100.0),
    "sharpness": (0.0, 100.0),
}
EDIT_STATUSES = frozenset({"draft", "accepted", "dismissed"})


class EditRecipeError(ValueError):
    pass


def normalize_edit_parameters(raw: Mapping[str, Any]) -> dict[str, float]:
    unknown = set(raw) - set(PARAMETER_LIMITS)
    if unknown:
        raise EditRecipeError(f"不支持的修图参数：{', '.join(sorted(unknown))}")
    normalized: dict[str, float] = {}
    for name, (minimum, maximum) in PARAMETER_LIMITS.items():
        value = raw.get(name, 0)
        if isinstance(value, bool):
            raise EditRecipeError(f"修图参数 {name} 必须是数字")
        try:
            numeric = float(value)
        except (TypeError, ValueError) as exc:
            raise EditRecipeError(f"修图参数 {name} 必须是数字") from exc
        if not minimum <= numeric <= maximum:
            raise EditRecipeError(f"修图参数 {name} 超出 {minimum:g}–{maximum:g} 范围")
        normalized[name] = round(numeric, 2)
    return normalized


def _row_to_recipe(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "capture_id": int(row["capture_id"]),
        "source_analysis_id": row["source_analysis_id"],
        "parameter_space": row["parameter_space"],
        "parameters": json.loads(row["parameters_json"]),
        "status": row["status"],
        "note": row["note"],
        "created_at": row["created_at"],
    }


def edit_recipe_history(
    connection: sqlite3.Connection, capture_id: int, limit: int = 10
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """SELECT * FROM edit_recipe_revisions WHERE capture_id=?
           ORDER BY id DESC LIMIT ?""",
        (capture_id, limit),
    ).fetchall()
    return [_row_to_recipe(row) for row in rows]


def save_edit_recipe(
    connection: sqlite3.Connection,
    capture_id: int,
    parameters: Mapping[str, Any],
    *,
    status: str = "draft",
    note: str | None = None,
    source_analysis_id: int | None = None,
) -> dict[str, Any]:
    if status not in EDIT_STATUSES:
        raise EditRecipeError("修图方案状态无效")
    if not connection.execute("SELECT 1 FROM captures WHERE id=?", (capture_id,)).fetchone():
        raise EditRecipeError("拍摄单元不存在")
    if source_analysis_id is not None and not connection.execute(
        "SELECT 1 FROM ai_analyses WHERE id=? AND capture_id=? AND status='complete'",
        (source_analysis_id, capture_id),
    ).fetchone():
        raise EditRecipeError("来源模型分析不存在或不属于当前照片")
    normalized = normalize_edit_parameters(parameters)
    cleaned_note = " ".join((note or "").split())[:1000] or None
    with transaction(connection):
        cursor = connection.execute(
            """INSERT INTO edit_recipe_revisions(
                   capture_id, source_analysis_id, parameters_json, status, note, created_at
               ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                capture_id,
                source_analysis_id,
                json.dumps(normalized, ensure_ascii=False, separators=(",", ":")),
                status,
                cleaned_note,
                utc_now(),
            ),
        )
    return edit_recipe_history(connection, capture_id, 1)[0] | {"id": cursor.lastrowid}


def restore_edit_recipe(
    connection: sqlite3.Connection, capture_id: int, revision_id: int
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM edit_recipe_revisions WHERE id=? AND capture_id=?",
        (revision_id, capture_id),
    ).fetchone()
    if row is None:
        raise EditRecipeError("修图方案历史不存在")
    recipe = _row_to_recipe(row)
    return save_edit_recipe(
        connection,
        capture_id,
        recipe["parameters"],
        status="draft",
        note=f"从版本 {revision_id} 恢复",
        source_analysis_id=recipe["source_analysis_id"],
    )
