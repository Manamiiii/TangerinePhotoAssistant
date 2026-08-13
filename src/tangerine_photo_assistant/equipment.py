from __future__ import annotations

import json
import os
import re
import sqlite3
import tomllib
from pathlib import Path
from typing import Any, Literal

ACCESSORY_SECTIONS = (
    "supports",
    "remotes",
    "lighting",
    "filters",
    "adapters",
    "accessories",
)
EquipmentKind = Literal["camera", "lens", "accessory"]


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


def _normalize_model(value: str) -> str:
    value = re.sub(r"\b(?:FUJINON|FUJIFILM|LENS)\b", "", value.upper())
    return re.sub(r"[^A-Z0-9]", "", value)


def _usage_for(model: str, usage: dict[str, int]) -> int:
    normalized = _normalize_model(model)
    return sum(count for name, count in usage.items() if _normalize_model(name) == normalized)


def _inventory_key(kind: EquipmentKind, item: dict[str, Any]) -> str:
    identity = item.get("model") or item.get("display_name") or item.get("kind")
    if kind == "accessory":
        identity = f"{item.get('section', 'accessories')}:{identity}"
    return str(identity or "未命名设备")


def _load_inventory(path: Path | None) -> dict[str, dict[str, bool]]:
    if path is None or not path.is_file():
        return {"camera": {}, "lens": {}, "accessory": {}}
    data = json.loads(path.read_text(encoding="utf-8"))
    ownership = data.get("ownership") or {}
    return {
        kind: {str(key): bool(value) for key, value in (ownership.get(kind) or {}).items()}
        for kind in ("camera", "lens", "accessory")
    }


def save_equipment_ownership(
    path: Path,
    kind: EquipmentKind,
    key: str,
    owned: bool,
) -> None:
    if kind not in {"camera", "lens", "accessory"}:
        raise ValueError("不支持的设备类型")
    key = key.strip()
    if not key or len(key) > 300:
        raise ValueError("设备标识不能为空或过长")
    ownership = _load_inventory(path)
    ownership[kind][key] = owned
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"version": 1, "ownership": ownership}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _decorate(
    item: dict[str, Any],
    kind: EquipmentKind,
    usage: dict[str, int],
    inventory: dict[str, dict[str, bool]],
    default_owned: bool,
) -> dict[str, Any]:
    key = _inventory_key(kind, item)
    owned = inventory[kind].get(key, default_owned)
    count = _usage_for(str(item.get("model", "")), usage) if kind != "accessory" else 0
    status = "owned" if owned else ("detected" if count else "unowned")
    return {
        **item,
        "display_name": item.get("display_name") or item.get("model") or "未命名设备",
        "capture_count": count,
        "inventory_key": key,
        "owned": owned,
        "status": status,
    }


def _merge_lenses(
    catalog_items: list[dict[str, Any]],
    profile_items: list[dict[str, Any]],
    detected: dict[str, int],
) -> list[tuple[dict[str, Any], bool]]:
    merged: list[tuple[dict[str, Any], bool]] = []
    profile_by_model = {_normalize_model(str(item.get("model", ""))): item for item in profile_items}
    known: set[str] = set()
    for catalog_item in catalog_items:
        normalized = _normalize_model(str(catalog_item.get("model", "")))
        profile_item = profile_by_model.get(normalized)
        merged.append(({**catalog_item, **(profile_item or {})}, profile_item is not None))
        known.add(normalized)
    for profile_item in profile_items:
        normalized = _normalize_model(str(profile_item.get("model", "")))
        if normalized not in known:
            merged.append((profile_item, True))
            known.add(normalized)
    for model in detected:
        normalized = _normalize_model(model)
        if normalized not in known:
            merged.append(({
                "brand": "Fujifilm" if normalized.startswith(("XF", "XC")) else "未知品牌",
                "model": model,
                "source": "exif",
            }, False))
            known.add(normalized)
    return merged


def build_equipment_catalog(
    connection: sqlite3.Connection,
    profile_path: Path,
    catalog_path: Path | None = None,
    inventory_path: Path | None = None,
) -> dict[str, Any]:
    if not profile_path.is_file():
        raise FileNotFoundError(f"器材档案不存在：{profile_path}")
    with profile_path.open("rb") as handle:
        profile = tomllib.load(handle)
    catalog: dict[str, Any] = {}
    if catalog_path is not None:
        if not catalog_path.is_file():
            raise FileNotFoundError(f"器材目录不存在：{catalog_path}")
        with catalog_path.open("rb") as handle:
            catalog = tomllib.load(handle)

    inventory = _load_inventory(inventory_path)
    camera_usage = _capture_usage(connection, "camera_model")
    lens_usage = _capture_usage(connection, "lens_model")

    camera = dict(profile.get("camera") or {})
    camera_pairs: list[tuple[dict[str, Any], bool]] = [(camera, True)] if camera else []
    known_cameras = {_normalize_model(str(camera.get("model", "")))} if camera else set()
    for model in camera_usage:
        if _normalize_model(model) not in known_cameras:
            camera_pairs.append(({"brand": "未知品牌", "model": model, "source": "exif"}, False))

    lens_pairs = _merge_lenses(
        [dict(item) for item in catalog.get("lenses", [])],
        [dict(item) for item in profile.get("lenses", [])],
        lens_usage,
    )
    accessories: list[dict[str, Any]] = []
    for section in ACCESSORY_SECTIONS:
        for raw_item in profile.get(section, []):
            item = {**dict(raw_item), "section": section, "source": "profile"}
            accessories.append(_decorate(item, "accessory", {}, inventory, True))

    cameras = [_decorate(item, "camera", camera_usage, inventory, owned) for item, owned in camera_pairs]
    lenses = [_decorate(item, "lens", lens_usage, inventory, owned) for item, owned in lens_pairs]
    return {
        "schema_version": max(int(profile.get("schema_version", 1)), int(catalog.get("schema_version", 1))),
        "profile_file": profile_path.name,
        "catalog": {
            "name": catalog.get("name"),
            "source_url": catalog.get("source_url"),
            "checked_at": catalog.get("checked_at"),
        },
        "summary": {
            "camera_count": sum(1 for item in cameras if item["owned"]),
            "lens_count": sum(1 for item in lenses if item["owned"]),
            "catalog_lens_count": len(catalog.get("lenses", [])),
            "unowned_lens_count": sum(1 for item in lenses if not item["owned"]),
            "accessory_count": sum(1 for item in accessories if item["owned"]),
            "detected_camera_count": len(camera_usage),
            "detected_lens_count": len(lens_usage),
        },
        "cameras": cameras,
        "lenses": lenses,
        "accessories": accessories,
        "detected": {
            "cameras": [{"model": model, "capture_count": count} for model, count in camera_usage.items()],
            "lenses": [{"model": model, "capture_count": count} for model, count in lens_usage.items()],
        },
        "filter_system": profile.get("filter_system", {}),
    }
