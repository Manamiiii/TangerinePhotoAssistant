from __future__ import annotations

import base64
import json
import math
import sqlite3
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, replace
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image, ImageFile, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError

from .database import transaction
from .inventory import utc_now

ALGORITHM_VERSION = "technical-v2"
HISTOGRAM_BUCKETS = 64
Progress = Callable[[int, int], None]


@dataclass(frozen=True)
class ImageMetrics:
    luminance_mean: float
    shadow_clip_pct: float
    highlight_clip_pct: float
    edge_strength: float
    exposure_score: float
    sharpness_score: float
    histogram: tuple[int, ...] = ()
    decode_warning: str | None = None


def _downsample_histogram(histogram: list[int]) -> tuple[int, ...]:
    """Fold a 256-bucket luminance histogram into HISTOGRAM_BUCKETS buckets."""
    step = 256 // HISTOGRAM_BUCKETS
    return tuple(
        sum(histogram[start:start + step]) for start in range(0, 256, step)
    )


def measure_luminance_histogram(path: Path, max_edge: int = 1280) -> tuple[int, ...]:
    """Decode only enough JPEG data for a display histogram, without rescoring."""
    with Image.open(path) as image:
        image.draft("RGB", (max_edge, max_edge))
        gray = ImageOps.grayscale(image)
        gray.thumbnail((max_edge, max_edge), Image.Resampling.BILINEAR)
        return _downsample_histogram(gray.histogram())


def _histogram_from_jpeg_bytes(data: bytes) -> tuple[int, ...]:
    with Image.open(BytesIO(data)) as image:
        return _downsample_histogram(ImageOps.grayscale(image).histogram())


def _measure_image_once(path: Path) -> ImageMetrics:
    with Image.open(path) as opened:
        opened.draft("RGB", (1280, 1280))
        image = ImageOps.exif_transpose(opened).convert("RGB")
        image.thumbnail((1280, 1280), Image.Resampling.LANCZOS)
        gray = image.convert("L")
        histogram = gray.histogram()
        pixel_count = max(1, sum(histogram))
        mean = ImageStat.Stat(gray).mean[0]
        shadows = 100.0 * sum(histogram[:9]) / pixel_count
        highlights = 100.0 * sum(histogram[248:]) / pixel_count
        edges = gray.filter(ImageFilter.FIND_EDGES)
        edge_strength = math.sqrt(max(0.0, ImageStat.Stat(edges).var[0]))

    brightness_penalty = max(0.0, abs(mean - 128.0) - 18.0) * 0.65
    clipping_penalty = min(30.0, shadows * 0.7 + highlights * 1.8)
    exposure_score = max(0.0, min(100.0, 100.0 - brightness_penalty - clipping_penalty))
    sharpness_score = max(0.0, min(100.0, 28.0 * math.log1p(edge_strength)))
    return ImageMetrics(
        luminance_mean=round(mean, 3),
        shadow_clip_pct=round(shadows, 3),
        highlight_clip_pct=round(highlights, 3),
        edge_strength=round(edge_strength, 3),
        exposure_score=round(exposure_score, 2),
        sharpness_score=round(sharpness_score, 2),
        histogram=_downsample_histogram(histogram),
    )


def measure_image(path: Path) -> ImageMetrics:
    """Measure a JPEG, retrying known recoverable stream truncation read-only."""
    try:
        return _measure_image_once(path)
    except OSError as exc:
        message = str(exc)
        if "truncated" not in message and "broken data stream" not in message:
            raise
        previous = ImageFile.LOAD_TRUNCATED_IMAGES
        ImageFile.LOAD_TRUNCATED_IMAGES = True
        try:
            return replace(_measure_image_once(path), decode_warning=message)
        finally:
            ImageFile.LOAD_TRUNCATED_IMAGES = previous


def exif_assessment(row: sqlite3.Row) -> tuple[float, list[dict[str, Any]]]:
    score = 100.0
    issues: list[dict[str, Any]] = []
    exposure = row["exposure_time"]
    focal = row["focal_length_35mm"] or row["focal_length_mm"]
    iso = row["iso"]
    if exposure and focal and exposure > 0:
        safe_handheld = 1.0 / max(float(focal), 1.0)
        if exposure > safe_handheld:
            ratio = exposure / safe_handheld
            penalty = min(22.0, 7.0 * math.log2(max(1.0, ratio)) + 5.0)
            score -= penalty
            issues.append({
                "code": "slow_shutter_risk",
                "severity": "warning" if ratio < 4 else "high",
                "evidence": {
                    "exposure_seconds": exposure,
                    "focal_length_35mm": focal,
                    "baseline_seconds": round(safe_handheld, 6),
                },
                "message": "按等效焦距估算，快门偏慢；防抖能减轻手抖，但不能冻结人物动作。",
                "inference": True,
            })
    if iso and iso >= 6400:
        score -= min(20.0, 8.0 + 4.0 * math.log2(iso / 6400))
        issues.append({
            "code": "high_iso",
            "severity": "warning",
            "evidence": {"iso": iso},
            "message": "高 ISO 可能降低细节和宽容度，需结合现场光线与曝光检查。",
            "inference": True,
        })
    return round(max(0.0, score), 2), issues


def _image_issues(metrics: ImageMetrics) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    if metrics.decode_warning:
        issues.append({
            "code": "jpeg_stream_recovered",
            "severity": "warning",
            "evidence": {"decoder_message": metrics.decode_warning},
            "message": "JPEG 数据流不完整，但已在只读容错模式下成功解码；建议人工确认画面末端区域。",
            "inference": False,
        })
    if metrics.highlight_clip_pct >= 2.0:
        issues.append({
            "code": "highlight_clipping",
            "severity": "high" if metrics.highlight_clip_pct >= 8 else "warning",
            "evidence": {"highlight_clip_pct": metrics.highlight_clip_pct},
            "message": "亮部存在明显接近纯白的区域，需确认是否为天空、灯光或皮肤高光。",
            "inference": False,
        })
    if metrics.shadow_clip_pct >= 12.0:
        issues.append({
            "code": "deep_shadows",
            "severity": "warning",
            "evidence": {"shadow_clip_pct": metrics.shadow_clip_pct},
            "message": "暗部占比较高；夜景或剪影可能是有意效果。",
            "inference": True,
        })
    if metrics.sharpness_score < 48:
        issues.append({
            "code": "low_global_detail",
            "severity": "warning",
            "evidence": {"sharpness_score": metrics.sharpness_score},
            "message": "全局边缘细节偏弱，可能来自失焦、运动、柔焦滤镜或浅景深。",
            "inference": True,
        })
    return issues


def _auto_rating(score: float) -> int:
    if score >= 85:
        return 5
    if score >= 75:
        return 4
    if score >= 60:
        return 3
    if score >= 45:
        return 2
    return 1


def rebuild_group_recommendations(connection: sqlite3.Connection) -> dict[str, int]:
    groups = connection.execute(
        "SELECT id FROM similarity_groups ORDER BY id"
    ).fetchall()
    picks = 0
    ranked = 0
    with transaction(connection):
        connection.execute("UPDATE capture_reviews SET auto_pick = 0, similarity_rank = NULL")
        for group in groups:
            rows = connection.execute(
                """
                SELECT sgc.capture_id, qm.technical_score
                FROM similarity_group_captures sgc
                LEFT JOIN quality_metrics qm ON qm.capture_id = sgc.capture_id
                WHERE sgc.group_id = ? AND qm.error IS NULL
                ORDER BY qm.technical_score DESC, sgc.sequence_index
                """,
                (group["id"],),
            ).fetchall()
            for rank, row in enumerate(rows, 1):
                connection.execute(
                    """
                    INSERT INTO capture_reviews(
                        capture_id, auto_pick, similarity_rank, updated_at
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(capture_id) DO UPDATE SET
                        auto_pick=excluded.auto_pick,
                        similarity_rank=excluded.similarity_rank,
                        updated_at=excluded.updated_at
                    """,
                    (row["capture_id"], int(rank == 1), rank, utc_now()),
                )
                ranked += 1
                if rank == 1:
                    picks += 1
    return {"recommended_picks": picks, "ranked_group_captures": ranked}


def analyze_quality(
    connection: sqlite3.Connection,
    progress: Progress | None = None,
    limit: int | None = None,
) -> dict[str, int]:
    params: list[int] = []
    limit_sql = ""
    if limit is not None:
        limit_sql = " LIMIT ?"
        params.append(limit)
    rows = connection.execute(
        """
        SELECT c.id AS capture_id, f.id AS file_id, f.path, f.size_bytes, f.modified_ns,
               f.exposure_time, f.f_number, f.iso, f.focal_length_mm, f.focal_length_35mm,
               qm.source_file_id, qm.algorithm_version,
               qm.size_bytes AS cached_size, qm.modified_ns AS cached_modified,
               qm.error AS cached_error
        FROM captures c
        JOIN event_captures ec ON ec.capture_id = c.id
        JOIN capture_files cf ON cf.capture_id = c.id AND cf.role = 'jpeg'
            AND cf.file_id = (
                SELECT MIN(cf2.file_id) FROM capture_files cf2
                JOIN files f2 ON f2.id = cf2.file_id
                WHERE cf2.capture_id = c.id AND cf2.role = 'jpeg' AND f2.present = 1
            )
        JOIN files f ON f.id = cf.file_id AND f.present = 1
        LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
        GROUP BY c.id
        ORDER BY f.path
        """ + limit_sql,
        params,
    ).fetchall()
    updated = 0
    cached = 0
    errors = 0
    total = len(rows)
    for index, row in enumerate(rows, 1):
        fresh = (
            row["source_file_id"] == row["file_id"]
            and row["algorithm_version"] == ALGORITHM_VERSION
            and row["cached_size"] == row["size_bytes"]
            and row["cached_modified"] == row["modified_ns"]
            and row["cached_error"] is None
        )
        if fresh:
            cached += 1
        else:
            error = None
            metrics: ImageMetrics | None = None
            try:
                metrics = measure_image(Path(row["path"]))
                exif_score, issues = exif_assessment(row)
                issues = _image_issues(metrics) + issues
                technical = round(
                    metrics.exposure_score * 0.34
                    + metrics.sharpness_score * 0.46
                    + exif_score * 0.20,
                    2,
                )
            except (OSError, UnidentifiedImageError, ValueError) as exc:
                exif_score, issues, technical = 0.0, [], 0.0
                error = str(exc)
                errors += 1
            connection.execute(
                """
                INSERT INTO quality_metrics(
                    capture_id, source_file_id, algorithm_version,
                    luminance_mean, shadow_clip_pct, highlight_clip_pct,
                    edge_strength, exposure_score, sharpness_score, exif_score,
                    technical_score, issue_json, histogram_json,
                    size_bytes, modified_ns, computed_at, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    source_file_id=excluded.source_file_id,
                    algorithm_version=excluded.algorithm_version,
                    luminance_mean=excluded.luminance_mean,
                    shadow_clip_pct=excluded.shadow_clip_pct,
                    highlight_clip_pct=excluded.highlight_clip_pct,
                    edge_strength=excluded.edge_strength,
                    exposure_score=excluded.exposure_score,
                    sharpness_score=excluded.sharpness_score,
                    exif_score=excluded.exif_score,
                    technical_score=excluded.technical_score,
                    issue_json=excluded.issue_json,
                    histogram_json=excluded.histogram_json,
                    size_bytes=excluded.size_bytes,
                    modified_ns=excluded.modified_ns,
                    computed_at=excluded.computed_at,
                    error=excluded.error
                """,
                (
                    row["capture_id"], row["file_id"], ALGORITHM_VERSION,
                    metrics.luminance_mean if metrics else None,
                    metrics.shadow_clip_pct if metrics else None,
                    metrics.highlight_clip_pct if metrics else None,
                    metrics.edge_strength if metrics else None,
                    metrics.exposure_score if metrics else None,
                    metrics.sharpness_score if metrics else None,
                    exif_score, technical, json.dumps(issues, ensure_ascii=False),
                    json.dumps(list(metrics.histogram)) if metrics and metrics.histogram else None,
                    row["size_bytes"], row["modified_ns"], utc_now(), error,
                ),
            )
            connection.execute(
                """
                INSERT INTO capture_reviews(capture_id, auto_rating, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(capture_id) DO UPDATE SET
                    auto_rating=excluded.auto_rating, updated_at=excluded.updated_at
                """,
                (row["capture_id"], _auto_rating(technical) if not error else None, utc_now()),
            )
            updated += 1
        if index % 25 == 0:
            connection.commit()
        if progress and (index == total or index % 10 == 0):
            progress(index, total)
    connection.commit()
    result = {
        "quality_considered": total,
        "quality_updated": updated,
        "quality_cached": cached,
        "quality_errors": errors,
    }
    if limit is None:
        result.update(rebuild_group_recommendations(connection))
    return result


def backfill_histograms(
    connection: sqlite3.Connection,
    progress: Progress | None = None,
    exiftool: Path | None = None,
    batch_size: int = 64,
) -> dict[str, int]:
    """Fill display histograms from embedded JPEG previews without rescoring."""
    rows = connection.execute(
        """
        SELECT qm.capture_id, f.path
        FROM quality_metrics qm
        JOIN files f ON f.id = qm.source_file_id
        WHERE qm.error IS NULL AND qm.histogram_json IS NULL AND f.present = 1
        ORDER BY qm.capture_id
        """
    ).fetchall()
    updated = 0
    errors = 0
    total = len(rows)
    size = max(1, min(batch_size, 96))
    for start in range(0, total, size):
        batch = rows[start:start + size]
        records: list[dict[str, Any]] = []
        if exiftool is not None:
            completed = subprocess.run(
                [
                    str(exiftool), "-j", "-b", "-ThumbnailImage",
                    *[row["path"] for row in batch],
                ],
                capture_output=True, check=False,
            )
            try:
                records = json.loads(completed.stdout) if completed.returncode == 0 else []
            except (json.JSONDecodeError, UnicodeDecodeError):
                records = []
        for position, row in enumerate(batch):
            try:
                thumbnail = (
                    records[position].get("ThumbnailImage")
                    if position < len(records) else None
                )
                if isinstance(thumbnail, str) and thumbnail.startswith("base64:"):
                    histogram = _histogram_from_jpeg_bytes(base64.b64decode(thumbnail[7:]))
                else:
                    histogram = measure_luminance_histogram(Path(row["path"]))
                connection.execute(
                    """UPDATE quality_metrics SET histogram_json=?
                       WHERE capture_id=? AND histogram_json IS NULL""",
                    (json.dumps(list(histogram)), row["capture_id"]),
                )
                updated += 1
            except (OSError, UnidentifiedImageError, ValueError):
                errors += 1
        connection.commit()
        if progress:
            progress(min(start + len(batch), total), total)
    connection.commit()
    return {
        "histograms_updated": updated,
        "histogram_errors": errors,
        "histogram_total": total,
    }
