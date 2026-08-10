from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
from typing import Any
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from PIL import Image, ImageOps, UnidentifiedImageError


ALLOWED_SHARE_EDGES = (1080, 2048, 3840)


def _safe_stem(value: str) -> str:
    cleaned = re.sub(r"[^\w.-]+", "_", value, flags=re.UNICODE).strip("._")
    return cleaned[:80] or "photo"


def write_phone_share_export(
    connection: sqlite3.Connection,
    originals: Path,
    reports_path: Path,
    capture_ids: list[int],
    max_edge: int = 2048,
    quality: int = 90,
) -> dict[str, Any]:
    unique_ids = list(dict.fromkeys(capture_ids))
    if not unique_ids or len(unique_ids) > 100:
        raise ValueError("每次必须选择 1 到 100 张照片")
    if max_edge not in ALLOWED_SHARE_EDGES:
        raise ValueError(f"导出长边必须是 {ALLOWED_SHARE_EDGES} 之一")
    if not 70 <= quality <= 95:
        raise ValueError("JPEG 质量必须在 70 到 95 之间")

    placeholders = ",".join("?" for _ in unique_ids)
    rows = connection.execute(
        f"""
        SELECT c.id AS capture_id, c.stem, c.captured_at, f.path, f.file_name,
               f.size_bytes
        FROM captures c
        JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
        JOIN files f ON f.id = cf.file_id AND f.present = 1
        WHERE c.id IN ({placeholders})
          AND cf.file_id = (
            SELECT MIN(cf2.file_id) FROM capture_files cf2
            JOIN files f2 ON f2.id = cf2.file_id
            WHERE cf2.capture_id = c.id AND cf2.role = 'jpeg' AND f2.present = 1
          )
        """,
        unique_ids,
    ).fetchall()
    by_id = {int(row["capture_id"]): row for row in rows}
    missing = [capture_id for capture_id in unique_ids if capture_id not in by_id]
    if missing:
        raise ValueError(f"所选照片缺少可用 JPG：{missing[:5]}")

    originals = originals.resolve()
    reports_path = reports_path.resolve()
    reports_path.mkdir(parents=True, exist_ok=True)
    required_free = sum(int(row["size_bytes"]) for row in rows) + 256 * 1024**2
    if shutil.disk_usage(reports_path).free < required_free:
        raise ValueError("报告目录空间不足，未创建手机分享包")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    filename = f"phone-share-{timestamp}-{uuid4().hex[:8]}.zip"
    target = (reports_path / filename).resolve()
    temporary = (reports_path / f".{filename}.{uuid4().hex}.partial").resolve()
    if not target.is_relative_to(reports_path) or not temporary.is_relative_to(reports_path):
        raise RuntimeError("导出路径超出报告目录")

    manifest: list[dict[str, Any]] = []
    try:
        with ZipFile(temporary, "w", compression=ZIP_DEFLATED, compresslevel=6) as archive:
            for index, capture_id in enumerate(unique_ids, 1):
                row = by_id[capture_id]
                source = Path(row["path"]).resolve()
                if not source.is_file() or not source.is_relative_to(originals):
                    raise ValueError(f"照片不在当前活动图库中：{capture_id}")
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
                manifest.append({
                    "capture_id": capture_id,
                    "file": arcname,
                    "captured_at": row["captured_at"],
                    "max_edge": max_edge,
                    "quality": quality,
                })
            archive.writestr(
                "export-info.json",
                json.dumps(
                    {
                        "purpose": "phone-sharing",
                        "photo_count": len(manifest),
                        "metadata_removed": True,
                        "photos": manifest,
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
        "photo_count": len(manifest),
        "size_bytes": target.stat().st_size,
        "max_edge": max_edge,
        "quality": quality,
        "metadata_removed": True,
    }
