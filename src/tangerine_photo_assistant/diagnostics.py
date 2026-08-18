from __future__ import annotations

import json
import platform
import re
import sqlite3
import zipfile
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from .database import SCHEMA_VERSION
from .equipment import _load_inventory
from .settings import Settings

SAFE_TABLE_COUNTS = (
    "files", "captures", "events", "similarity_groups", "quality_metrics",
    "capture_reviews", "capture_tags", "ai_runs", "ai_analyses", "edit_recipe_revisions",
)


def _package_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def _safe_category(value: object) -> str:
    text = str(value or "unknown")
    return text if re.fullmatch(r"[A-Za-z0-9_.:-]{1,80}", text) else "other"


def _group_counts(connection: sqlite3.Connection, table: str, field: str) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for row in connection.execute(
        f"SELECT {field} AS value, COUNT(*) AS count FROM {table} GROUP BY {field}"
    ):
        category = _safe_category(row["value"])
        counts[category] = counts.get(category, 0) + int(row["count"])
    return [
        {"value": category, "count": count}
        for category, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_diagnostic_report(connection: sqlite3.Connection, settings: Settings, task: dict[str, Any]) -> dict[str, Any]:
    inventory = _load_inventory(settings.workspace / "Equipment" / "inventory.json")
    table_counts = {table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]) for table in SAFE_TABLE_COUNTS}
    integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    equipment_counts = {
        container: {kind: len(values) for kind, values in inventory[container].items()}
        for container in ("ownership", "custom", "overrides", "hidden")
    }
    return {
        "format": "tangerine-redacted-diagnostics", "format_version": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "application": {"version": _package_version("tangerine-photo-assistant") or "development", "schema": SCHEMA_VERSION},
        "runtime": {"platform": platform.system().lower(), "platform_release": platform.release(),
                    "python": platform.python_version(), "architecture": platform.machine(),
                    "packages": {name: _package_version(name) for name in ("fastapi", "pillow", "uvicorn")}},
        "safety": {"offline_only": settings.offline_only, "read_only": settings.read_only,
                   "allow_move": settings.allow_move, "allow_delete": settings.allow_delete,
                   "allow_metadata_write": settings.allow_original_metadata_write},
        "capabilities": {"exiftool": settings.find_exiftool() is not None,
                         "local_ai": settings.ai_runtime_status()[0],
                         "raw_extension_count": len(settings.raw_extensions)},
        "configuration": {"cache_max_size_gb": settings.cache_max_size_gb,
                          "thumbnail_max_size_gb": settings.thumbnail_max_size_gb,
                          "metadata_batch_size": settings.metadata_batch_size,
                          "burst_time_gap_seconds": settings.burst_time_gap_seconds,
                          "ai_quantization": settings.ai_quantization,
                          "ai_image_max_edge": settings.ai_image_max_edge},
        "database": {"integrity": integrity, "table_counts": table_counts,
                     "scan_statuses": _group_counts(connection, "scan_runs", "status"),
                     "scan_error_types": _group_counts(connection, "scan_errors", "error_type"),
                     "ai_run_statuses": _group_counts(connection, "ai_runs", "status"),
                     "migration_failure_stages": _group_counts(connection, "migration_failures", "stage")},
        "equipment_counts": equipment_counts,
        "task": {"status": _safe_category(task.get("status")), "stage": _safe_category(task.get("stage")),
                 **{key: task.get(key) for key in ("current", "total", "failure_count", "pausable")}},
        "redaction": {"photos": "excluded", "image_content": "excluded", "absolute_paths": "excluded",
                      "relative_paths_and_filenames": "excluded", "gps": "excluded", "serial_numbers": "excluded",
                      "user_notes_and_tag_names": "excluded", "model_prompts_responses_and_results": "excluded",
                      "raw_error_messages": "excluded"},
    }


def write_diagnostic_bundle(connection: sqlite3.Connection, settings: Settings, task: dict[str, Any]) -> dict[str, Any]:
    report = build_diagnostic_report(connection, settings, task)
    settings.reports_path.mkdir(parents=True, exist_ok=True)
    filename = f"tangerine-diagnostics-{datetime.now(UTC):%Y%m%d-%H%M%S-%f}.zip"
    path = settings.reports_path / filename
    payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("diagnostics.json", payload)
    return {"filename": filename, "size_bytes": path.stat().st_size,
            "integrity": report["database"]["integrity"], "redaction": report["redaction"]}
