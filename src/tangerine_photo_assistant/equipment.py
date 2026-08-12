from __future__ import annotations

import sqlite3
import tomllib
from pathlib import Path
from typing import Any

ACCESSORY_SECTIONS = (
    "supports",
    "remotes",
    "lighting",
    "filters",
    "adapters",
    "accessories",
)


def _capture_usage(connection: sqlite3.Connection, field: str) -> dict[str, int]:
    if field not in {"camera_model", "lens_model"}:
        raise ValueError("unsupported equipment usage field")
    rows = connection.execute(
        f"""
        SELECT f.{field} AS model, COUNT(DISTINCT c.id) AS capture_count
        FROM captures c
        JOIN capture_files cf ON cf.capture_id = c.id
        JOIN files f ON f.id = cf.file_id AND f.present = 1
        WHERE f.{field} IS NOT NULL AND TRIM(f.{field}) != ''
        GROUP BY f.{field}
        ORDER BY capture_count DESC, model
        """
    ).fetchall()
    return {str(row["model"]): int(row["capture_count"]) for row in rows}


def _with_usage(items: list[dict[str, Any]], usage: dict[str, int]) -> list[dict[str, Any]]:
    return [
        {
            **item,
            "display_name": item.get("display_name") or item.get("model") or "未命名设备",
            "capture_count": usage.get(str(item.get("model", "")), 0),
            "status": "owned",
        }
        for item in items
    ]


def build_equipment_catalog(
    connection: sqlite3.Connection,
    profile_path: Path,
) -> dict[str, Any]:
    if not profile_path.is_file():
        raise FileNotFoundError(f"器材档案不存在：{profile_path}")
    with profile_path.open("rb") as handle:
        profile = tomllib.load(handle)

    camera = dict(profile.get("camera") or {})
    cameras = [camera] if camera else []
    lenses = [dict(item) for item in profile.get("lenses", [])]
    accessories: list[dict[str, Any]] = []
    for section in ACCESSORY_SECTIONS:
        for item in profile.get(section, []):
            accessories.append({**dict(item), "section": section, "status": "owned"})

    camera_usage = _capture_usage(connection, "camera_model")
    lens_usage = _capture_usage(connection, "lens_model")
    return {
        "schema_version": int(profile.get("schema_version", 1)),
        "profile_file": profile_path.name,
        "summary": {
            "camera_count": len(cameras),
            "lens_count": len(lenses),
            "accessory_count": len(accessories),
            "detected_camera_count": len(camera_usage),
            "detected_lens_count": len(lens_usage),
        },
        "cameras": _with_usage(cameras, camera_usage),
        "lenses": _with_usage(lenses, lens_usage),
        "accessories": accessories,
        "detected": {
            "cameras": [
                {"model": model, "capture_count": count}
                for model, count in camera_usage.items()
            ],
            "lenses": [
                {"model": model, "capture_count": count}
                for model, count in lens_usage.items()
            ],
        },
        "filter_system": profile.get("filter_system", {}),
    }
