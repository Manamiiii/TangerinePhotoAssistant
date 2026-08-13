from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import tomllib
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

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
    if item.get("inventory_key"):
        return str(item["inventory_key"])
    identity = item.get("model") or item.get("display_name") or item.get("kind")
    if kind == "accessory":
        identity = f"{item.get('section', 'accessories')}:{identity}"
    return str(identity or "未命名设备")


def _empty_inventory() -> dict[str, Any]:
    return {
        "version": 2,
        "ownership": {"camera": {}, "lens": {}, "accessory": {}},
        "custom": {"camera": [], "lens": [], "accessory": []},
        "overrides": {"camera": {}, "lens": {}, "accessory": {}},
        "hidden": {"camera": [], "lens": [], "accessory": []},
    }


def _load_inventory(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return _empty_inventory()
    data = json.loads(path.read_text(encoding="utf-8"))
    result = _empty_inventory()
    for container in ("ownership", "custom", "overrides", "hidden"):
        source = data.get(container) or {}
        for kind in ("camera", "lens", "accessory"):
            if kind in source:
                result[container][kind] = source[kind]
    return result


def _write_inventory(path: Path, inventory: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if path.is_file():
        shutil.copy2(path, path.with_name("inventory.backup.json"))
    temporary.replace(path)


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
    inventory = _load_inventory(path)
    inventory["ownership"][kind][key] = owned
    _write_inventory(path, inventory)


def save_equipment_item(
    path: Path,
    kind: EquipmentKind,
    item: dict[str, Any],
    key: str | None = None,
    existing_items: list[dict[str, Any]] | None = None,
) -> str:
    if kind not in {"camera", "lens", "accessory"}:
        raise ValueError("不支持的设备类型")
    model = str(item.get("model") or "").strip()
    display_name = str(item.get("display_name") or "").strip()
    if not model and not display_name:
        raise ValueError("型号或显示名称至少填写一项")
    inventory = _load_inventory(path)
    custom = None if key is None else next(
        (entry for entry in inventory["custom"][kind] if entry.get("inventory_key") == key),
        None,
    )
    if key is not None and custom is None:
        # Catalog/EXIF identity is immutable. Personal names and notes remain editable.
        item = {field: value for field, value in item.items() if field != "model"}
        model = key.split(":", 1)[-1] if kind == "accessory" else key
    normalized = _normalize_model(model)
    if normalized and existing_items:
        duplicate = next((
            entry for entry in existing_items
            if entry.get("inventory_key") != key
            and _normalize_model(str(entry.get("model") or "")) == normalized
        ), None)
        if duplicate is not None:
            raise ValueError(f"设备型号已存在：{duplicate.get('display_name') or duplicate.get('model')}")
    clean = {
        field: value.strip() if isinstance(value, str) else value
        for field, value in item.items()
        if field in {"brand", "model", "display_name", "category", "section", "kind", "notes", "filter_thread_mm", "thread_mm", "system_mm", "lens_thread_mm", "stops"}
        and value not in (None, "")
    }
    if key is None:
        custom_key = f"custom:{uuid4().hex}"
        inventory["custom"][kind].append({**clean, "inventory_key": custom_key})
        inventory["ownership"][kind][custom_key] = bool(item.get("owned", True))
        _write_inventory(path, inventory)
        return custom_key
    key = key.strip()
    if custom is not None:
        custom.clear()
        custom.update({**clean, "inventory_key": key})
    else:
        inventory["overrides"][kind][key] = clean
    if "owned" in item:
        inventory["ownership"][kind][key] = bool(item["owned"])
    _write_inventory(path, inventory)
    return key


def delete_equipment_item(path: Path, kind: EquipmentKind, key: str) -> None:
    if kind not in {"camera", "lens", "accessory"}:
        raise ValueError("不支持的设备类型")
    key = key.strip()
    if not key or len(key) > 300:
        raise ValueError("设备标识不能为空或过长")
    inventory = _load_inventory(path)
    custom = inventory["custom"][kind]
    remaining = [entry for entry in custom if entry.get("inventory_key") != key]
    if len(remaining) == len(custom):
        raise ValueError("只能删除手工新增的设备；目录或 EXIF 设备请使用隐藏")
    inventory["custom"][kind] = remaining
    inventory["ownership"][kind].pop(key, None)
    _write_inventory(path, inventory)


def set_equipment_visibility(path: Path, kind: EquipmentKind, key: str, visible: bool) -> None:
    if kind not in {"camera", "lens", "accessory"} or not key.strip():
        raise ValueError("无效的设备标识")
    inventory = _load_inventory(path)
    hidden = inventory["hidden"][kind]
    if visible:
        inventory["hidden"][kind] = [item for item in hidden if item != key]
    elif key not in hidden:
        hidden.append(key)
    _write_inventory(path, inventory)


def _decorate(
    item: dict[str, Any],
    kind: EquipmentKind,
    usage: dict[str, int],
    inventory: dict[str, Any],
    default_owned: bool,
) -> dict[str, Any]:
    key = _inventory_key(kind, item)
    identity_model = str(item.get("model", ""))
    item = {**item, **inventory["overrides"][kind].get(key, {})}
    owned = inventory["ownership"][kind].get(key, default_owned)
    count = _usage_for(identity_model, usage) if kind != "accessory" else 0
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
        catalog_item = {**catalog_item, "source": "catalog"}
        normalized = _normalize_model(str(catalog_item.get("model", "")))
        profile_item = profile_by_model.get(normalized)
        merged.append(({**catalog_item, **(profile_item or {}), "source": "profile" if profile_item else "catalog"}, profile_item is not None))
        known.add(normalized)
    for profile_item in profile_items:
        normalized = _normalize_model(str(profile_item.get("model", "")))
        if normalized not in known:
            merged.append(({**profile_item, "source": "profile"}, True))
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
    camera_pairs: list[tuple[dict[str, Any], bool]] = [({**camera, "source": "profile"}, True)] if camera else []
    for custom in inventory["custom"]["camera"]:
        camera_pairs.append(({**deepcopy(custom), "source": "custom"}, True))
    known_cameras = {_normalize_model(str(item.get("model", ""))) for item, _ in camera_pairs}
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

    for custom in inventory["custom"]["lens"]:
        lens_pairs.append(({**deepcopy(custom), "source": "custom"}, True))
    for custom in inventory["custom"]["accessory"]:
        accessories.append(_decorate({**deepcopy(custom), "source": "custom"}, "accessory", {}, inventory, True))

    cameras = [_decorate(item, "camera", camera_usage, inventory, owned) for item, owned in camera_pairs]
    lenses = [_decorate(item, "lens", lens_usage, inventory, owned) for item, owned in lens_pairs]
    all_items = {"camera": cameras, "lens": lenses, "accessory": accessories}
    hidden_items = {
        kind: [item for item in items if item["inventory_key"] in inventory["hidden"][kind]]
        for kind, items in all_items.items()
    }
    cameras = [item for item in cameras if item["inventory_key"] not in inventory["hidden"]["camera"]]
    lenses = [item for item in lenses if item["inventory_key"] not in inventory["hidden"]["lens"]]
    accessories = [item for item in accessories if item["inventory_key"] not in inventory["hidden"]["accessory"]]
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
        "hidden": hidden_items,
        "detected": {
            "cameras": [{"model": model, "capture_count": count} for model, count in camera_usage.items()],
            "lenses": [{"model": model, "capture_count": count} for model, count in lens_usage.items()],
        },
        "filter_system": profile.get("filter_system", {}),
    }
