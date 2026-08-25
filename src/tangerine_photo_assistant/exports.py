from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile

from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_SHARE_EDGES = (1080, 2048, 3840)


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:80] or "photo"


def write_photo_export(
    connection: sqlite3.Connection,
    originals: Path,
    reports_path: Path,
    capture_ids: list[int],
    max_edge: int = 2048,
    quality: int = 90,
    *,
    include_jpeg: bool = True,
    include_raw: bool = False,
    original_jpeg: bool = False,
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(capture_ids))
    if not unique_ids or len(unique_ids) > 100:
        raise ValueError("每次必须选择 1 到 100 张照片")
    if not include_jpeg and not include_raw:
        raise ValueError("至少选择 JPG 或 RAW 一种导出文件")
    if include_jpeg and not original_jpeg and max_edge not in ALLOWED_SHARE_EDGES:
        raise ValueError(f"导出长边必须是 {ALLOWED_SHARE_EDGES} 之一")
    if not 70 <= quality <= 95:
        raise ValueError("JPEG 质量必须在 70 到 95 之间")

    placeholders = ",".join("?" for _ in unique_ids)
    rows = connection.execute(
        f"""
        SELECT c.id AS capture_id, c.stem, c.captured_at, cf.role, f.path,
               f.file_name, f.size_bytes
        FROM captures c
        JOIN capture_files cf ON cf.capture_id = c.id AND cf.role IN ('jpeg', 'raw')
        JOIN files f ON f.id = cf.file_id AND f.present = 1
        WHERE c.id IN ({placeholders})
          AND cf.file_id = (
            SELECT MIN(cf2.file_id) FROM capture_files cf2
            JOIN files f2 ON f2.id = cf2.file_id
            WHERE cf2.capture_id = c.id AND cf2.role = cf.role AND f2.present = 1
          )
        """,
        unique_ids,
    ).fetchall()
    by_id_role = {(int(row["capture_id"]), str(row["role"])): row for row in rows}
    missing_jpeg = [capture_id for capture_id in unique_ids if (capture_id, "jpeg") not in by_id_role]
    if include_jpeg and missing_jpeg:
        raise ValueError(f"所选照片缺少可用 JPG：{missing_jpeg[:5]}")
    raw_rows = [by_id_role[(capture_id, "raw")] for capture_id in unique_ids if (capture_id, "raw") in by_id_role]
    if include_raw and not raw_rows:
        raise ValueError("所选照片没有可用 RAW 文件")

    originals = originals.resolve()
    reports_path = reports_path.resolve()
    reports_path.mkdir(parents=True, exist_ok=True)
    export_rows = []
    if include_jpeg:
        export_rows.extend(by_id_role[(capture_id, "jpeg")] for capture_id in unique_ids)
    if include_raw:
        export_rows.extend(raw_rows)
    required_free = sum(int(row["size_bytes"]) for row in export_rows) + 256 * 1024**2
    if shutil.disk_usage(reports_path).free < required_free:
        raise ValueError("报告目录空间不足，未创建照片导出包")
    timestamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    filename = f"photo-export-{timestamp}-{uuid4().hex[:8]}.zip"
    target = (reports_path / filename).resolve()
    temporary = (reports_path / f".{filename}.{uuid4().hex}.partial").resolve()
    if not target.is_relative_to(reports_path) or not temporary.is_relative_to(reports_path):
        raise RuntimeError("导出路径超出报告目录")

    manifest: list[dict[str, Any]] = []
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for index, capture_id in enumerate(unique_ids, 1):
                requested_roles = []
                if include_jpeg:
                    requested_roles.append("jpeg")
                if include_raw and (capture_id, "raw") in by_id_role:
                    requested_roles.append("raw")
                for role in requested_roles:
                    row = by_id_role[(capture_id, role)]
                    source = Path(row["path"]).resolve()
                    if not source.is_file() or not source.is_relative_to(originals):
                        raise ValueError(f"照片不在当前活动图库中：{capture_id}")
                    suffix = source.suffix.lower() or (".jpg" if role == "jpeg" else ".raw")
                    arcname = f"{index:03d}_{_safe_stem(str(row['stem']))}{suffix}"
                    if role == "jpeg" and not original_jpeg:
                        try:
                            with Image.open(source) as opened:
                                image = ImageOps.exif_transpose(opened).convert("RGB")
                            image.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
                            output = BytesIO()
                            image.save(output, format="JPEG", quality=quality, optimize=True)
                        except (OSError, UnidentifiedImageError, ValueError) as exc:
                            raise ValueError(f"无法生成照片副本：{capture_id}") from exc
                        arcname = f"{index:03d}_{_safe_stem(str(row['stem']))}.jpg"
                        archive.writestr(arcname, output.getvalue())
                    else:
                        archive.write(source, arcname, compress_type=ZIP_STORED)
                    manifest.append({
                        "capture_id": capture_id,
                        "role": role,
                        "file": arcname,
                        "captured_at": row["captured_at"],
                        "max_edge": None if role == "raw" or original_jpeg else max_edge,
                        "quality": quality if role == "jpeg" and not original_jpeg else None,
                        "metadata_removed": role == "jpeg" and not original_jpeg,
                    })
            archive.writestr(
                "export-info.json",
                json.dumps(
                    {
                        "purpose": "photo-export",
                        "capture_count": len({item["capture_id"] for item in manifest}),
                        "file_count": len(manifest),
                        "files": manifest,
                    },
                    ensure_ascii=False,
                    indent=2,
                ).encode("utf-8"),
            )
        with temporary.open("r+b") as handle:
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return {
        "filename": filename,
        "photo_count": len({item["capture_id"] for item in manifest}),
        "file_count": len(manifest),
        "jpeg_count": sum(item["role"] == "jpeg" for item in manifest),
        "raw_count": sum(item["role"] == "raw" for item in manifest),
        "missing_raw_count": len(unique_ids) - len(raw_rows) if include_raw else 0,
        "size_bytes": target.stat().st_size,
        "max_edge": None if original_jpeg or not include_jpeg else max_edge,
        "quality": quality,
        "metadata_removed": include_jpeg and not original_jpeg,
    }
