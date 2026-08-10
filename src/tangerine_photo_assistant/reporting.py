from __future__ import annotations

from datetime import datetime
from pathlib import Path
import json
import sqlite3
from typing import Any


def _rows(connection: sqlite3.Connection, query: str) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query).fetchall()]


def build_report(connection: sqlite3.Connection) -> dict[str, Any]:
    total = connection.execute(
        """
        SELECT COUNT(*) AS count, COALESCE(SUM(size_bytes), 0) AS size_bytes
        FROM files WHERE present = 1
        """
    ).fetchone()
    return {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "files": {"count": total["count"], "size_bytes": total["size_bytes"]},
        "by_media_kind": _rows(
            connection,
            """
            SELECT media_kind, COUNT(*) AS count, SUM(size_bytes) AS size_bytes
            FROM files WHERE present = 1
            GROUP BY media_kind ORDER BY count DESC
            """,
        ),
        "by_extension": _rows(
            connection,
            """
            SELECT extension, COUNT(*) AS count, SUM(size_bytes) AS size_bytes
            FROM files WHERE present = 1
            GROUP BY extension ORDER BY count DESC, extension
            """,
        ),
        "top_level_folders": _rows(
            connection,
            """
            SELECT
              CASE
                WHEN instr(relative_path, '\\') = 0 THEN '[root]'
                ELSE substr(relative_path, 1, instr(relative_path, '\\') - 1)
              END AS folder,
              COUNT(*) AS count,
              SUM(size_bytes) AS size_bytes
            FROM files WHERE present = 1
            GROUP BY folder ORDER BY count DESC
            """,
        ),
        "pairing": _rows(
            connection,
            """
            SELECT pairing_status, COUNT(*) AS count
            FROM captures GROUP BY pairing_status ORDER BY count DESC
            """,
        ),
        "metadata": _rows(
            connection,
            """
            SELECT metadata_status, COUNT(*) AS count
            FROM files WHERE present = 1
            GROUP BY metadata_status ORDER BY count DESC
            """,
        ),
        "cameras": _rows(
            connection,
            """
            SELECT camera_make, camera_model, COUNT(*) AS count
            FROM files
            WHERE present = 1 AND camera_model IS NOT NULL
            GROUP BY camera_make, camera_model ORDER BY count DESC
            """,
        ),
        "lenses": _rows(
            connection,
            """
            SELECT lens_model, COUNT(*) AS count
            FROM files
            WHERE present = 1 AND lens_model IS NOT NULL
            GROUP BY lens_model ORDER BY count DESC
            """,
        ),
        "scan_errors": connection.execute("SELECT COUNT(*) AS count FROM scan_errors").fetchone()[
            "count"
        ],
    }


def write_report(report: dict[str, Any], output_directory: Path) -> tuple[Path, Path]:
    output_directory.mkdir(parents=True, exist_ok=True)
    json_path = output_directory / "inventory-latest.json"
    markdown_path = output_directory / "inventory-latest.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _size_gb(size_bytes: int | None) -> str:
    return f"{(size_bytes or 0) / (1024**3):.2f} GB"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 照片库只读审计报告",
        "",
        f"生成时间：{report['generated_at']}",
        "",
        f"文件总数：{report['files']['count']:,}",
        "",
        f"总体积：{_size_gb(report['files']['size_bytes'])}",
        "",
        "## 文件类型",
        "",
        "| 类型 | 数量 | 体积 |",
        "|---|---:|---:|",
    ]
    for row in report["by_media_kind"]:
        lines.append(f"| {row['media_kind']} | {row['count']:,} | {_size_gb(row['size_bytes'])} |")

    lines.extend(["", "## JPG/RAW 拍摄单元", "", "| 状态 | 数量 |", "|---|---:|"])
    for row in report["pairing"]:
        lines.append(f"| {row['pairing_status']} | {row['count']:,} |")

    lines.extend(["", "## 顶层目录", "", "| 目录 | 文件数 | 体积 |", "|---|---:|---:|"])
    for row in report["top_level_folders"]:
        lines.append(f"| {row['folder']} | {row['count']:,} | {_size_gb(row['size_bytes'])} |")

    lines.extend(["", "## 元数据状态", "", "| 状态 | 数量 |", "|---|---:|"])
    for row in report["metadata"]:
        lines.append(f"| {row['metadata_status']} | {row['count']:,} |")

    lines.extend(["", f"扫描访问错误：{report['scan_errors']:,}", ""])
    return "\n".join(lines)
