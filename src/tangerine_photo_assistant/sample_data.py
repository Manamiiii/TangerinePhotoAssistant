from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any

from PIL import Image, ImageEnhance, TiffImagePlugin

from .database import connect
from .inventory import utc_now
from .quality import rebuild_group_recommendations
from .visual import rebuild_similarity_groups


GENERATOR_VERSION = 3

DEMO_REVIEWS: dict[str, tuple[int | None, bool, bool, str]] = {
    "BEACH_0001": (2, False, True, "演示：连拍中排除"),
    "BEACH_0003": (5, True, False, "演示：连拍精选封面"),
    "PARK_0004": (5, True, False, "演示：第一段连拍精选"),
    "PARK_0007": (4, True, False, "演示：第二段连拍精选"),
    "NIGHT_0002": (5, True, False, "演示：非连拍照片精选"),
    "DETAIL_0002": (2, False, True, "演示：非连拍照片排除"),
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
    exif[271] = "FUJIFILM"
    exif[272] = "X-S20"
    exif[306] = timestamp
    exif[36867] = timestamp
    exif[42036] = scene["lens"]
    exif[33434] = TiffImagePlugin.IFDRational(*scene["exposure"])
    exif[33437] = TiffImagePlugin.IFDRational(*scene["aperture"])
    exif[34855] = scene["iso"]
    exif[37386] = TiffImagePlugin.IFDRational(*scene["focal"])
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


def seed_demo_catalog(database_path: Path) -> dict[str, int]:
    """Add deterministic review and grouping examples to the isolated demo catalog."""
    connection = connect(database_path)
    try:
        now = utc_now()
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
        return {
            "reviews": updated,
            "manual_splits": int(split is not None),
            "similarity_groups": groups["similarity_groups"],
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
        print(
            f"Demo selections ready: {seeded['reviews']} reviews, "
            f"{seeded['manual_splits']} manual split, "
            f"{seeded['similarity_groups']} similarity groups"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
