from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..database import connect_readonly

METERING_MODE_LABELS = {
    0: "未知", 1: "平均", 2: "中央重点", 3: "点测光",
    4: "多点", 5: "评价测光", 6: "局部", 255: "其他",
}
WHITE_BALANCE_LABELS = {0: "自动", 1: "手动"}
FILM_MODE_LABELS = {
    0x000: "PROVIA / 标准", 0x100: "彩色高饱和", 0x110: "彩色柔和",
    0x120: "ASTIA / 柔和", 0x200: "Velvia / 鲜艳", 0x300: "PRO Neg. Std",
    0x310: "PRO Neg. Hi", 0x400: "CLASSIC CHROME", 0x500: "ETERNA / 影院",
    0x510: "CLASSIC Neg.", 0x520: "ETERNA 漂白", 0x530: "NOSTALGIC Neg.",
    0x600: "REALA ACE",
}
DYNAMIC_RANGE_LABELS = {0x000: "自动", 0x001: "手动", 0x100: "DR100", 0x200: "DR200", 0x400: "DR400"}


def _exif_label(value: Any, labels: dict[int, str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
        return value
    try:
        code = int(value)
    except (TypeError, ValueError):
        return str(value)
    return labels.get(code, str(value))


def _exif_extras(exif_json: str | None) -> dict[str, Any]:
    if not exif_json:
        return {}
    try:
        values = json.loads(exif_json)
    except (TypeError, json.JSONDecodeError):
        return {}
    flash = values.get("Flash")
    flash_label = None
    if flash is not None:
        try:
            flash_label = "已闪光" if int(flash) & 0x1 else "未闪光"
        except (TypeError, ValueError):
            flash_label = str(flash)
    return {
        "metering_mode": _exif_label(values.get("MeteringMode"), METERING_MODE_LABELS),
        "white_balance": _exif_label(values.get("WhiteBalance"), WHITE_BALANCE_LABELS),
        "flash": flash_label,
        "focus_mode": values.get("FocusMode"),
        "film_simulation": _exif_label(values.get("FilmMode"), FILM_MODE_LABELS),
        "dynamic_range": _exif_label(
            values.get("DynamicRangeSetting", values.get("DynamicRange")),
            DYNAMIC_RANGE_LABELS,
        ),
        "exposure_program": values.get("ExposureProgram"),
        "exposure_mode": values.get("ExposureMode"),
        "shutter_type": values.get("ShutterType"),
        "orientation": values.get("Orientation"),
        "captured_at_precise": values.get("SubSecDateTimeOriginal"),
        "timezone_offset": values.get("OffsetTimeOriginal"),
        "color_space": values.get("ColorSpace"),
        "bits_per_sample": values.get("BitsPerSample"),
        "image_quality": values.get("Quality"),
        "image_stabilization": values.get("ImageStabilization"),
        "drive_mode": values.get("DriveMode"),
        "drive_speed": values.get("DriveSpeed"),
        "sequence_number": values.get("SequenceNumber"),
        "auto_bracketing": values.get("AutoBracketing"),
        "af_mode": values.get("AFMode"),
        "af_area_mode": values.get("AFAreaMode"),
        "focus_pixel": values.get("FocusPixel"),
        "blur_warning": values.get("BlurWarning"),
        "focus_warning": values.get("FocusWarning"),
        "exposure_warning": values.get("ExposureWarning"),
        "faces_detected": values.get("FacesDetected"),
        "roll_angle": values.get("RollAngle"),
        "camera_elevation_angle": values.get("CameraElevationAngle"),
        "white_balance_fine_tune": values.get("WhiteBalanceFineTune"),
        "highlight_tone": values.get("HighlightTone"),
        "shadow_tone": values.get("ShadowTone"),
        "saturation": values.get("Saturation"),
        "camera_sharpness": values.get("Sharpness"),
        "noise_reduction": values.get("NoiseReduction"),
        "clarity": values.get("Clarity"),
        "color_chrome_effect": values.get("ColorChromeEffect"),
        "color_chrome_fx_blue": values.get("ColorChromeFXBlue"),
        "grain_effect_roughness": values.get("GrainEffectRoughness"),
        "grain_effect_size": values.get("GrainEffectSize"),
        "lens_modulation_optimizer": values.get("LensModulationOptimizer"),
        "auto_dynamic_range": values.get("AutoDynamicRange"),
        "raw_compression": values.get("RAFCompression"),
    }


def query_capture_detail(database_path: Path, capture_id: int) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        row = connection.execute(
            """
            SELECT c.id, c.stem, c.parent_relative, c.captured_at, c.pairing_status,
                   e.id AS event_id, e.proposed_name AS event_name, e.category,
                   qm.luminance_mean, qm.shadow_clip_pct, qm.highlight_clip_pct,
                   qm.edge_strength, qm.exposure_score, qm.sharpness_score,
                   qm.exif_score, qm.technical_score, qm.issue_json,
                   qm.histogram_json, qm.error,
                   cr.auto_rating, cr.auto_pick, cr.similarity_rank,
                   cr.user_rating, cr.user_pick, cr.user_reject, cr.user_note
            FROM captures c
            LEFT JOIN event_captures ec ON ec.capture_id = c.id
            LEFT JOIN events e ON e.id = ec.event_id
            LEFT JOIN quality_metrics qm ON qm.capture_id = c.id
            LEFT JOIN capture_reviews cr ON cr.capture_id = c.id
            WHERE c.id = ?
            """,
            (capture_id,),
        ).fetchone()
        if row is None:
            raise ValueError("拍摄单元不存在")
        item = dict(row)
        raw_issues = item.pop("issue_json")
        item["issues"] = json.loads(raw_issues) if raw_issues else []
        raw_histogram = item.pop("histogram_json")
        item["histogram"] = json.loads(raw_histogram) if raw_histogram else None
        item["files"] = [dict(file) for file in connection.execute(
            """
            SELECT f.id, f.file_name, f.path, f.extension, f.media_kind, f.size_bytes,
                   cf.role, f.camera_make, f.camera_model, f.lens_model,
                   f.exposure_time, f.f_number, f.iso, f.focal_length_mm,
                   f.focal_length_35mm, f.exposure_compensation, f.width, f.height,
                   f.gps_latitude, f.gps_longitude, f.exif_json
            FROM capture_files cf JOIN files f ON f.id = cf.file_id
            WHERE cf.capture_id = ? AND f.present = 1 ORDER BY cf.role, f.id
            """,
            (capture_id,),
        )]
        for file in item["files"]:
            file.update(_exif_extras(file.pop("exif_json")))
        analyses = connection.execute(
            """
            SELECT id, model_id, prompt_version, result_json, finished_at,
                   user_verdict, user_note, reviewed_at
            FROM ai_analyses WHERE capture_id=? AND status='complete'
            ORDER BY id DESC
            """,
            (capture_id,),
        ).fetchall()
        item["ai_analyses"] = [
            {
                **dict(analysis),
                "result": json.loads(analysis["result_json"])
                if analysis["result_json"] else {},
            }
            for analysis in analyses
        ]
        for analysis in item["ai_analyses"]:
            analysis.pop("result_json", None)
        item["tags"] = [dict(tag) for tag in connection.execute(
            """SELECT td.id, td.dimension, td.name, td.built_in,
                      ct.source, ct.confidence
               FROM capture_tags ct
               JOIN tag_definitions td ON td.id = ct.tag_id
               WHERE ct.capture_id=?
               ORDER BY CASE td.dimension
                            WHEN 'subject' THEN 1 WHEN 'status' THEN 2
                            WHEN 'problem' THEN 3 ELSE 4 END,
                        td.sort_order, td.name""",
            (capture_id,),
        )]
        item["tag_catalog"] = [dict(tag) for tag in connection.execute(
            """SELECT id, dimension, name, built_in
               FROM tag_definitions
               WHERE active=1
               ORDER BY CASE dimension
                            WHEN 'subject' THEN 1 WHEN 'status' THEN 2
                            WHEN 'problem' THEN 3 ELSE 4 END,
                        sort_order, name"""
        )]
        item["thumbnail_url"] = f"/api/thumbnails/{capture_id}?size=1280"
    finally:
        connection.close()
    return item
