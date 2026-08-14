from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from PIL import Image, ImageEnhance, TiffImagePlugin

from .database import connect
from .inventory import utc_now
from .metadata import METADATA_PROFILE_VERSION
from .quality import rebuild_group_recommendations
from .tags import replace_manual_capture_tags
from .visual import rebuild_similarity_groups

GENERATOR_VERSION = 5

DEMO_RAW_COMPANIONS = ("BEACH_0003", "NIGHT_0002")
DEMO_AI_MODEL_ID = "DEMO-ONLY-no-inference"

# Rich but fictional values for exercising every useful detail-page section on
# the isolated Mac demo. These values are written only to the demo catalog;
# privacy-cleaned JPEG fixtures and production photos are never modified.
DEMO_EXIF_DETAILS: dict[str, Any] = {
    "ExposureProgram": "Aperture-priority AE",
    "ExposureMode": "Auto",
    "ShutterType": "Mechanical",
    "MeteringMode": "Multi-segment",
    "WhiteBalance": "Auto",
    "Flash": "No Flash",
    "FocusMode": "AF-C",
    "AFMode": "Zone",
    "AFAreaMode": "Zone",
    "FocusPixel": "960 640",
    "FilmMode": "REALA ACE",
    "DynamicRange": "DR200",
    "DynamicRangeSetting": "DR200",
    "Orientation": "Horizontal (normal)",
    "OffsetTimeOriginal": "+08:00",
    "ColorSpace": "sRGB",
    "BitsPerSample": 8,
    "Quality": "Fine",
    "ImageStabilization": "On",
    "DriveMode": "Continuous Low",
    "DriveSpeed": "3 fps",
    "AutoBracketing": "Off",
    "BlurWarning": "None",
    "FocusWarning": "Good",
    "ExposureWarning": "None",
    "FacesDetected": 0,
    "RollAngle": 0.4,
    "CameraElevationAngle": -1.2,
    "WhiteBalanceFineTune": "Red +1, Blue -1",
    "HighlightTone": -1,
    "ShadowTone": 0,
    "Saturation": 1,
    "Sharpness": 0,
    "NoiseReduction": -2,
    "Clarity": 0,
    "ColorChromeEffect": "Strong",
    "ColorChromeFXBlue": "Weak",
    "GrainEffectRoughness": "Weak",
    "GrainEffectSize": "Small",
    "LensModulationOptimizer": "On",
    "AutoDynamicRange": 200,
}

DEMO_REVIEWS: dict[str, tuple[int | None, bool, bool, str]] = {
    "BEACH_0001": (2, False, True, "演示：连拍中排除"),
    "BEACH_0003": (5, True, False, "演示：连拍入选封面"),
    "PARK_0004": (5, True, False, "演示：第一段连拍入选"),
    "PARK_0007": (4, True, False, "演示：第二段连拍入选"),
    "NIGHT_0002": (5, False, False, "演示：非连拍照片仅使用星级"),
    "DETAIL_0002": (2, False, False, "演示：非连拍照片仅使用星级"),
}

DEMO_TAGS: dict[str, list[dict[str, str]]] = {
    "BEACH_0003": [
        {"dimension": "subject", "name": "风景"},
        {"dimension": "status", "name": "待修"},
        {"dimension": "location", "name": "演示海岸"},
    ],
    "PARK_0004": [
        {"dimension": "subject", "name": "纪实"},
        {"dimension": "problem", "name": "背景干扰"},
    ],
    "NIGHT_0002": [
        {"dimension": "subject", "name": "星空"},
        {"dimension": "status", "name": "精选"},
    ],
}

DEMO_AI_RESULTS: dict[str, dict[str, Any]] = {
    "BEACH_0003": {
        "subject_type": "风景",
        "quality_summary": "模拟结果：主体清楚、层次自然，可轻微压低高光。",
        "visible_problems": [
            {
                "name": "天空高光略亮",
                "severity": "low",
                "evidence": "模拟样例用于检查问题证据的完整展示。",
                "confidence": 0.78,
            }
        ],
        "shooting_advice": [
            {
                "suggestion": "保留当前快门并尝试降低约三分之一档曝光",
                "reason": "为亮部保留更多余量",
                "exif_basis": "1/500 秒、ISO 200",
            }
        ],
        "lightroom_suggestions": [
            {
                "adjustment": "高光",
                "direction": "降低 10–20",
                "reason": "恢复天空层次",
            }
        ],
        "photoshop_needed": False,
        "photoshop_reason": "不需要",
        "overall_confidence": 0.78,
    },
    "PARK_0004": {
        "subject_type": "其他",
        "quality_summary": "模拟结果：动作瞬间完整，背景稍显杂乱。",
        "visible_problems": [
            {
                "name": "背景干扰",
                "severity": "medium",
                "evidence": "模拟样例用于检查多层建议和人工复核入口。",
                "confidence": 0.72,
            }
        ],
        "shooting_advice": [
            {
                "suggestion": "连拍前向侧面移动半步简化背景",
                "reason": "减少主体轮廓附近的干扰元素",
                "exif_basis": "135mm、1/1000 秒",
            }
        ],
        "lightroom_suggestions": [
            {
                "adjustment": "主体蒙版",
                "direction": "曝光提高约 0.15 EV",
                "reason": "让主体从背景中更明确地分离",
            }
        ],
        "photoshop_needed": False,
        "photoshop_reason": "不需要",
        "overall_confidence": 0.72,
    },
    "NIGHT_0002": {
        "subject_type": "风景",
        "quality_summary": "模拟结果：夜景曝光均衡，暗部可按个人风格微调。",
        "visible_problems": [],
        "shooting_advice": [],
        "lightroom_suggestions": [
            {
                "adjustment": "阴影",
                "direction": "按需提高 5–10",
                "reason": "轻微展开暗部但保持夜景氛围",
            }
        ],
        "photoshop_needed": False,
        "photoshop_reason": "不需要",
        "overall_confidence": 0.84,
    },
}

SCENES: tuple[dict[str, Any], ...] = (
    {
        "relative": "旅行/2026/2026-07-12_海边散步",
        "prefix": "BEACH",
        "count": 7,
        "sources": ("MAC_TEST_0001.JPG",),
        "start": datetime(2026, 7, 12, 17, 35, 10),
        "gap_seconds": 2,
        "lens": "XF23mmF1.4 R LM WR",
        "exposure": (1, 500),
        "aperture": (20, 10),
        "iso": 200,
        "focal": (23, 1),
        "brightness": 1.04,
    },
    {
        "relative": "日常/2026/2026-07-20_公园抓拍",
        "prefix": "PARK",
        "count": 9,
        "sources": ("MAC_TEST_0003.JPG",),
        "start": datetime(2026, 7, 20, 10, 10, 20),
        "gap_seconds": 1,
        "lens": "XF70-300mmF4-5.6 R LM OIS WR",
        "exposure": (1, 1000),
        "aperture": (56, 10),
        "iso": 800,
        "focal": (135, 1),
        "brightness": 1.0,
    },
    {
        "relative": "旅行/2026/2026-08-01_城市夜景",
        "prefix": "NIGHT",
        "count": 6,
        "sources": ("MAC_TEST_0002.JPG", "MAC_TEST_0004.JPG", "MAC_TEST_0001.JPG", "MAC_TEST_0003.JPG"),
        "start": datetime(2026, 8, 1, 20, 15, 0),
        "gap_seconds": 4,
        "lens": "XF16-80mmF4 R OIS WR",
        "exposure": (1, 60),
        "aperture": (40, 10),
        "iso": 1600,
        "focal": (35, 1),
        "brightness": 0.62,
    },
    {
        "relative": "日常/2026/2026-08-05_静物练习",
        "prefix": "DETAIL",
        "count": 4,
        "sources": ("MAC_TEST_0004.JPG", "MAC_TEST_0002.JPG", "MAC_TEST_0001.JPG", "MAC_TEST_0003.JPG"),
        "start": datetime(2026, 8, 5, 15, 40, 0),
        "gap_seconds": 8,
        "lens": "XC15-45mmF3.5-5.6 OIS PZ",
        "exposure": (1, 125),
        "aperture": (50, 10),
        "iso": 400,
        "focal": (35, 1),
        "brightness": 1.08,
    },
)


def _exif(scene: dict[str, Any], captured_at: datetime) -> Image.Exif:
    exif = Image.Exif()
    timestamp = captured_at.strftime("%Y:%m:%d %H:%M:%S")
    focal_length = TiffImagePlugin.IFDRational(*scene["focal"])
    exif[271] = "FUJIFILM"
    exif[272] = "X-S20"
    exif[274] = 1
    exif[306] = timestamp
    exif[34850] = 3
    exif[36867] = timestamp
    exif[42036] = scene["lens"]
    exif[33434] = TiffImagePlugin.IFDRational(*scene["exposure"])
    exif[33437] = TiffImagePlugin.IFDRational(*scene["aperture"])
    exif[34855] = scene["iso"]
    exif[37380] = TiffImagePlugin.IFDRational(0, 1)
    exif[37383] = 5
    exif[37385] = 0
    exif[37386] = focal_length
    exif[40961] = 1
    exif[41986] = 0
    exif[41987] = 0
    exif[41989] = round(float(focal_length) * 1.5)
    return exif


def _render_variant(source: Path, target: Path, scene: dict[str, Any], index: int) -> None:
    with Image.open(source) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    inset = min(index % 4, 3) * max(1, min(width, height) // 120)
    horizontal = (index % 3 - 1) * inset
    vertical = ((index + 1) % 3 - 1) * inset
    left = max(0, inset + horizontal)
    top = max(0, inset + vertical)
    right = min(width, width - inset + horizontal)
    bottom = min(height, height - inset + vertical)
    if right - left > width // 2 and bottom - top > height // 2:
        image = image.crop((left, top, right, bottom)).resize((width, height), Image.Resampling.LANCZOS)
    brightness = float(scene["brightness"]) * (0.96 + (index % 5) * 0.02)
    image = ImageEnhance.Brightness(image).enhance(brightness)
    image = ImageEnhance.Contrast(image).enhance(0.98 + (index % 3) * 0.025)
    captured_at = scene["start"] + timedelta(seconds=scene["gap_seconds"] * index)
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, format="JPEG", quality=88, optimize=True, exif=_exif(scene, captured_at))


def generate_demo_library(source_root: Path, target_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    target_root = target_root.resolve()
    manifest_path = target_root.parent / "demo-library.json"
    if manifest_path.is_file():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if existing.get("generator_version") == GENERATOR_VERSION:
            files = [target_root / item["relative_path"] for item in existing.get("files", [])]
            if files and all(path.is_file() for path in files):
                return existing
        for item in existing.get("files", []):
            stale = (target_root / item["relative_path"]).resolve()
            if target_root in stale.parents and stale.is_file():
                stale.unlink()

    source_files = {path.name: path for path in source_root.glob("*.JPG")}
    required = {name for scene in SCENES for name in scene["sources"]}
    missing = sorted(required - source_files.keys())
    if missing:
        raise FileNotFoundError(f"缺少演示样片：{', '.join(missing)}")

    generated: list[dict[str, Any]] = []
    for scene in SCENES:
        for index in range(int(scene["count"])):
            source_name = scene["sources"][index % len(scene["sources"])]
            file_name = f"{scene['prefix']}_{index + 1:04d}.JPG"
            target = target_root / scene["relative"] / file_name
            _render_variant(source_files[source_name], target, scene, index)
            generated.append({
                "relative_path": target.relative_to(target_root).as_posix(),
                "role": "photo",
                "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            })

    for stem in DEMO_RAW_COMPANIONS:
        jpeg_item = next(
            item for item in generated
            if Path(item["relative_path"]).stem == stem
        )
        jpeg_path = target_root / jpeg_item["relative_path"]
        raw_path = jpeg_path.with_suffix(".RAF")
        # This fixture exercises pairing and UI states only. Its payload remains
        # the privacy-cleaned JPEG derivative so no production RAW is bundled.
        shutil.copyfile(jpeg_path, raw_path)
        generated.append({
            "relative_path": raw_path.relative_to(target_root).as_posix(),
            "role": "simulated-raw-companion",
            "paired_with": jpeg_item["relative_path"],
            "sha256": hashlib.sha256(raw_path.read_bytes()).hexdigest(),
        })

    duplicate_root = target_root / "待整理/重复参考"
    for index, source_relative in enumerate((generated[0]["relative_path"], generated[8]["relative_path"]), 1):
        source = target_root / source_relative
        target = duplicate_root / source.name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        generated.append({
            "relative_path": target.relative_to(target_root).as_posix(),
            "role": "exact-duplicate",
            "duplicate_of": source_relative,
            "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        })

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "generated_at": "deterministic-fixture",
        "sample_count": len(generated),
        "event_count": len(SCENES),
        "exact_duplicate_count": 2,
        "simulated_raw_count": len(DEMO_RAW_COMPANIONS),
        "privacy": {
            "source_samples_are_sanitized": True,
            "gps_included": False,
            "serial_numbers_included": False,
            "timestamps_are_fictional": True,
        },
        "files": generated,
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def _seed_demo_ai_results(connection: sqlite3.Connection) -> int:
    connection.execute("DELETE FROM ai_runs WHERE model_id=?", (DEMO_AI_MODEL_ID,))
    cursor = connection.execute(
        """INSERT INTO ai_runs(
               mode, model_id, prompt_version, status, requested_count,
               completed_count, failed_count, started_at, finished_at
           ) VALUES ('benchmark', ?, 'photo-critique-v4', 'complete', ?, ?, 0,
                     '2026-08-06T10:00:00+00:00', '2026-08-06T10:00:24+00:00')""",
        (DEMO_AI_MODEL_ID, len(DEMO_AI_RESULTS), len(DEMO_AI_RESULTS)),
    )
    run_id = int(cursor.lastrowid)
    inserted = 0
    for offset, (stem, result) in enumerate(DEMO_AI_RESULTS.items()):
        capture = connection.execute(
            "SELECT id FROM captures WHERE stem=? ORDER BY id LIMIT 1", (stem,)
        ).fetchone()
        if capture is None:
            continue
        connection.execute(
            """INSERT INTO ai_analyses(
                   run_id, capture_id, model_id, prompt_version, status, priority,
                   selection_reason, result_json, attempt_count, started_at, finished_at
               ) VALUES (?, ?, ?, 'photo-critique-v4', 'complete', 100,
                         'isolated_demo_fixture', ?, 1, ?, ?)""",
            (
                run_id,
                capture["id"],
                DEMO_AI_MODEL_ID,
                json.dumps(result, ensure_ascii=False),
                f"2026-08-06T10:00:{offset * 8:02d}+00:00",
                f"2026-08-06T10:00:{(offset + 1) * 8:02d}+00:00",
            ),
        )
        inserted += 1
    connection.execute(
        "UPDATE ai_runs SET requested_count=?, completed_count=? WHERE id=?",
        (inserted, inserted, run_id),
    )
    return inserted


def seed_demo_equipment(workspace: Path) -> Path:
    """Create deterministic fictional inventory inside an isolated workspace."""
    inventory_path = workspace / "Equipment" / "inventory.json"
    if inventory_path.is_file():
        return inventory_path
    inventory_path.parent.mkdir(parents=True, exist_ok=True)
    inventory = {
        "version": 2,
        "ownership": {
            "camera": {"X-S20": True},
            "lens": {
                "XF23mmF1.4 R LM WR": True,
                "XF70-300mmF4-5.6 R LM OIS WR": True,
                "XF16-80mmF4 R OIS WR": False,
                "XC15-45mmF3.5-5.6 OIS PZ": True,
            },
            "accessory": {
                "custom:demo-tripod": True,
                "custom:demo-battery": False,
            },
        },
        "custom": {
            "camera": [],
            "lens": [],
            "accessory": [
                {
                    "brand": "Demo",
                    "model": "Travel Tripod",
                    "display_name": "演示旅行三脚架",
                    "section": "supports",
                    "notes": "隔离样例，可自由增删改",
                    "inventory_key": "custom:demo-tripod",
                },
                {
                    "brand": "Demo",
                    "model": "Spare Battery",
                    "display_name": "演示备用电池",
                    "section": "accessories",
                    "notes": "未拥有状态示例",
                    "inventory_key": "custom:demo-battery",
                },
            ],
        },
        "overrides": {"camera": {}, "lens": {}, "accessory": {}},
        "hidden": {"camera": [], "lens": [], "accessory": []},
    }
    inventory_path.write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return inventory_path


def seed_demo_catalog(database_path: Path) -> dict[str, int]:
    """Add deterministic review and grouping examples to the isolated demo catalog."""
    connection = connect(database_path)
    try:
        now = utc_now()
        metadata_updated = 0
        for row in connection.execute(
            """SELECT f.id, f.exif_json, f.captured_at, c.stem
               FROM files f
               JOIN capture_files cf ON cf.file_id=f.id
               JOIN captures c ON c.id=cf.capture_id
               WHERE f.present=1 AND cf.role='jpeg'"""
        ).fetchall():
            try:
                values = json.loads(row["exif_json"] or "{}")
            except json.JSONDecodeError:
                values = {}
            values.update(DEMO_EXIF_DETAILS)
            captured_at = str(row["captured_at"] or "2026-01-01T00:00:00")
            values["SubSecDateTimeOriginal"] = (
                captured_at.replace("-", ":", 2).replace("T", " ") + ".25"
            )
            stem = str(row["stem"])
            sequence = stem.rsplit("_", 1)[-1]
            values["SequenceNumber"] = int(sequence) if sequence.isdigit() else 1
            if stem.startswith(("NIGHT_", "DETAIL_")):
                values.update(
                    {
                        "FocusMode": "AF-S",
                        "AFMode": "Single Point",
                        "DriveMode": "Single",
                    }
                )
            connection.execute(
                """UPDATE files SET exif_json=?, metadata_profile_version=?,
                          metadata_refreshed_at=?, metadata_status='complete', metadata_error=NULL
                   WHERE id=?""",
                (
                    json.dumps(values, ensure_ascii=False, sort_keys=True),
                    METADATA_PROFILE_VERSION, now, row["id"],
                ),
            )
            metadata_updated += 1
        updated = 0
        for stem, (rating, picked, rejected, note) in DEMO_REVIEWS.items():
            row = connection.execute(
                "SELECT id FROM captures WHERE stem=? ORDER BY id LIMIT 1", (stem,)
            ).fetchone()
            if row is None:
                continue
            connection.execute(
                """INSERT INTO capture_reviews(
                       capture_id, user_rating, user_pick, user_reject,
                       user_note, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(capture_id) DO UPDATE SET
                       user_rating=excluded.user_rating,
                       user_pick=excluded.user_pick,
                       user_reject=excluded.user_reject,
                       user_note=excluded.user_note,
                       updated_at=excluded.updated_at""",
                (row["id"], rating, int(picked), int(rejected), note, now),
            )
            updated += 1
        connection.commit()
        tagged = 0
        for stem, tags in DEMO_TAGS.items():
            row = connection.execute(
                "SELECT id FROM captures WHERE stem=? ORDER BY id LIMIT 1", (stem,)
            ).fetchone()
            if row is None:
                continue
            replace_manual_capture_tags(connection, int(row["id"]), tags)
            tagged += 1
        split = connection.execute(
            "SELECT id FROM captures WHERE stem='PARK_0006' ORDER BY id LIMIT 1"
        ).fetchone()
        if split is not None:
            connection.execute(
                """INSERT INTO similarity_group_overrides(
                       capture_id, action, created_at, updated_at
                   ) VALUES (?, 'split_before', ?, ?)
                   ON CONFLICT(capture_id) DO UPDATE SET
                       action=excluded.action, updated_at=excluded.updated_at""",
                (split["id"], now, now),
            )
        connection.commit()
        groups = rebuild_similarity_groups(connection)
        rebuild_group_recommendations(connection)
        ai_results = _seed_demo_ai_results(connection)
        equipment_album = connection.execute(
            """SELECT id FROM events WHERE status!='archived'
               ORDER BY start_at IS NULL, start_at DESC, id DESC LIMIT 1"""
        ).fetchone()
        if equipment_album is not None:
            connection.execute(
                """INSERT OR IGNORE INTO event_equipment(
                       event_id, equipment_kind, equipment_key, source, created_at
                   ) VALUES (?, 'accessory', 'custom:demo-tripod', 'manual', ?)""",
                (equipment_album["id"], now),
            )
        connection.commit()
        return {
            "reviews": updated,
            "tagged_captures": tagged,
            "manual_splits": int(split is not None),
            "similarity_groups": groups["similarity_groups"],
            "metadata_profiles": metadata_updated,
            "ai_results": ai_results,
            "album_equipment": int(equipment_album is not None),
        }
    finally:
        connection.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the isolated Mac demo photo library")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    arguments = parser.parse_args()
    result = generate_demo_library(arguments.source, arguments.target)
    print(
        f"Mac demo library ready: {result['sample_count']} files, "
        f"{result['event_count']} events, {result['exact_duplicate_count']} exact duplicates"
    )
    if arguments.database is not None:
        seeded = seed_demo_catalog(arguments.database)
        equipment_path = seed_demo_equipment(arguments.database.parent.parent)
        print(
            f"Demo selections ready: {seeded['reviews']} reviews, "
            f"{seeded['manual_splits']} manual split, "
            f"{seeded['similarity_groups']} similarity groups, "
            f"{seeded['metadata_profiles']} rich metadata profiles, "
            f"{seeded['tagged_captures']} tagged captures, "
            f"{seeded['ai_results']} simulated model results, "
            f"equipment inventory at {equipment_path}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
