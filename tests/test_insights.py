import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.insights import build_conditional_review_insights
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.queries.library import query_library_captures
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import rebuild_structure


def settings_for(root: Path) -> Settings:
    originals = root / "originals"
    originals.mkdir()
    return Settings(
        originals=originals, workspace=root / "workspace", cache_root=root / "cache",
        cache_max_size_gb=2, thumbnail_max_size_gb=1,
        offline_only=True, read_only=True, allow_move=False,
        allow_delete=False, allow_original_metadata_write=False, raw_extensions=(".raf",),
        exiftool=None, metadata_batch_size=8, burst_time_gap_seconds=3.0,
    )


class ConditionalInsightTests(unittest.TestCase):
    def test_condition_requires_sample_and_drills_to_exact_photos(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            event = settings.originals / "旅行" / "2026-08-10_条件统计"
            event.mkdir(parents=True)
            for index in range(6):
                (event / f"IMG_{index + 1:04d}.JPG").write_bytes(b"jpeg")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            capture_rows = connection.execute(
                "SELECT id, stem FROM captures ORDER BY stem"
            ).fetchall()
            for index, row in enumerate(capture_rows):
                connection.execute(
                    """UPDATE files SET iso=?, exposure_time=1.0/250,
                           f_number=4, focal_length_mm=35, focal_length_35mm=53
                       WHERE stem=?""",
                    (6400 if index < 3 else 100, row["stem"]),
                )
            connection.execute(
                """INSERT INTO ai_runs(mode, model_id, prompt_version, status,
                       requested_count, completed_count, started_at)
                   VALUES ('benchmark', 'test', 'v4', 'complete', 6, 6, 'now')"""
            )
            run_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            for index, row in enumerate(capture_rows):
                problems = [{
                    "name": "高 ISO 噪点", "severity": "medium",
                    "evidence": "暗部颗粒", "confidence": 0.8,
                }] if index < 2 else []
                result = {
                    "subject_type": "旅行", "visible_problems": problems,
                    "overall_confidence": 0.8,
                }
                connection.execute(
                    """INSERT INTO ai_analyses(
                           run_id, capture_id, model_id, prompt_version, status,
                           selection_reason, result_json, finished_at)
                       VALUES (?, ?, 'test', 'v4', 'complete', 'test', ?, 'now')""",
                    (run_id, row["id"], json.dumps(result, ensure_ascii=False)),
                )
            connection.commit()

            insights = build_conditional_review_insights(connection)
            iso_insight = next(
                item for item in insights
                if item["condition_key"] == "iso|3201–6400"
                and item["problem"] == "高 ISO 噪点"
            )
            self.assertEqual(iso_insight["sample_count"], 3)
            self.assertEqual(iso_insight["problem_count"], 2)
            self.assertEqual(iso_insight["problem_rate"], 66.7)
            connection.close()

            page = query_library_captures(
                settings.database_path, 20, 0,
                model_problem="高 ISO 噪点", review_condition="iso|3201–6400",
                sort="name",
            )
            self.assertEqual([item["stem"] for item in page["items"]], [
                "IMG_0001", "IMG_0002",
            ])
            with self.assertRaisesRegex(ValueError, "不受支持"):
                query_library_captures(
                    settings.database_path, 20, 0, review_condition="sql|anything"
                )


if __name__ == "__main__":
    unittest.main()
