from __future__ import annotations

from pathlib import Path
from typing import Any

from ..ai_analysis import ai_summary, quality_summary
from ..database import connect_readonly
from ..metadata import METADATA_PROFILE_VERSION
from ..tags import analysis_subject_tag_status


def query_analysis_overview(
    database_path: Path,
    ai_model_path: Path | None,
    ai_quantization: str,
    runtime_ready: bool,
    runtime_message: str,
) -> dict[str, Any]:
    connection = connect_readonly(database_path)
    try:
        return {
            "quality": quality_summary(connection),
            "ai": ai_summary(connection, ai_model_path, ai_quantization),
            "runtime": {"ready": runtime_ready, "message": runtime_message},
            "subject_tags": analysis_subject_tag_status(connection),
            "detail_data": {
                "metadata_profile_version": METADATA_PROFILE_VERSION,
                "metadata_pending": connection.execute(
                    """SELECT COUNT(*) FROM files f
                       JOIN capture_files cf ON cf.file_id=f.id
                       WHERE f.present=1 AND COALESCE(f.metadata_profile_version, 0) < ?
                         AND (cf.role='jpeg' OR (cf.role='raw' AND NOT EXISTS (
                           SELECT 1 FROM capture_files jpeg_cf
                           JOIN files jpeg_f ON jpeg_f.id=jpeg_cf.file_id
                           WHERE jpeg_cf.capture_id=cf.capture_id
                             AND jpeg_cf.role='jpeg' AND jpeg_f.present=1
                         )))""",
                    (METADATA_PROFILE_VERSION,),
                ).fetchone()[0],
                "histograms_pending": connection.execute(
                    """SELECT COUNT(*) FROM quality_metrics qm
                       JOIN files f ON f.id=qm.source_file_id
                       WHERE qm.error IS NULL AND qm.histogram_json IS NULL
                         AND f.present=1"""
                ).fetchone()[0],
            },
        }
    finally:
        connection.close()
