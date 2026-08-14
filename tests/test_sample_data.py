import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.equipment import build_equipment_catalog
from tangerine_photo_assistant.inventory import enrich_metadata, scan_library
from tangerine_photo_assistant.metadata import PillowMetadataReader
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.quality import analyze_quality
from tangerine_photo_assistant.sample_data import (
    DEMO_AI_MODEL_ID,
    generate_demo_library,
    seed_demo_catalog,
    seed_demo_equipment,
)
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.visual import build_visual_fingerprints, rebuild_similarity_groups


class DemoLibraryTests(unittest.TestCase):
    def test_generates_deterministic_private_demo_library(self) -> None:
        source = Path(__file__).resolve().parents[1] / "sample-library" / "photos" / "mac-test-event"
        with TemporaryDirectory() as temporary:
            target = Path(temporary) / "photos"
            first = generate_demo_library(source, target)
            second = generate_demo_library(source, target)

            self.assertEqual(first, second)
            self.assertEqual(first["sample_count"], 30)
            self.assertEqual(first["event_count"], 4)
            self.assertEqual(first["exact_duplicate_count"], 2)
            self.assertEqual(first["simulated_raw_count"], 2)
            self.assertEqual(len(list(target.rglob("*.JPG"))), 28)
            self.assertEqual(len(list(target.rglob("*.RAF"))), 2)
            self.assertEqual(
                (target / first["files"][-1]["relative_path"]).read_bytes(),
                (target / first["files"][-1]["duplicate_of"]).read_bytes(),
            )
            with Image.open(target / first["files"][0]["relative_path"]) as image:
                exif = image.getexif()
                self.assertEqual(exif.get(272), "X-S20")
                self.assertIsNone(exif.get(34853))
                self.assertTrue(str(exif.get(36867)).startswith("2026:"))

    def test_seeds_visible_selection_and_manual_grouping_examples(self) -> None:
        source = Path(__file__).resolve().parents[1] / "sample-library" / "photos" / "mac-test-event"
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            originals = root / "photos"
            generate_demo_library(source, originals)
            settings = Settings(
                originals=originals, workspace=root / "workspace", cache_root=root / "cache",
                cache_max_size_gb=2, thumbnail_max_size_gb=1,
                offline_only=True, read_only=True,
                allow_move=False, allow_delete=False, allow_original_metadata_write=False,
                raw_extensions=(".raf",), exiftool=None, metadata_batch_size=8,
                burst_time_gap_seconds=3.0,
            )
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            enrich_metadata(connection, settings, PillowMetadataReader())
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            build_visual_fingerprints(connection)
            rebuild_similarity_groups(connection)
            analyze_quality(connection)
            connection.close()

            seeded = seed_demo_catalog(settings.database_path)
            self.assertEqual(seeded["reviews"], 6)
            self.assertEqual(seeded["manual_splits"], 1)
            self.assertEqual(seeded["similarity_groups"], 3)
            self.assertEqual(seeded["metadata_profiles"], 28)
            self.assertEqual(seeded["ai_results"], 3)
            self.assertEqual(seeded["album_equipment"], 1)
            connection = connect(settings.database_path)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capture_reviews WHERE user_pick=1").fetchone()[0],
                3,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM capture_reviews
                       WHERE selection_reason_json IS NOT NULL
                         AND selection_reason_json != '[]'"""
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capture_reviews WHERE user_reject=1").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM similarity_group_overrides").fetchone()[0],
                1,
            )
            metadata = connection.execute(
                """SELECT exif_json, metadata_profile_version
                   FROM files WHERE file_name='BEACH_0001.JPG'"""
            ).fetchone()
            self.assertEqual(metadata["metadata_profile_version"], 2)
            exif = json.loads(metadata["exif_json"])
            self.assertEqual(exif["ShutterType"], "Mechanical")
            self.assertEqual(exif["AFMode"], "Zone")
            self.assertEqual(exif["FilmMode"], "REALA ACE")
            self.assertEqual(exif["OffsetTimeOriginal"], "+08:00")
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM similarity_group_captures sgc
                       JOIN captures c ON c.id=sgc.capture_id
                       WHERE c.stem LIKE 'NIGHT_%'"""
                ).fetchone()[0],
                0,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM capture_files WHERE role='raw'"
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(DISTINCT ct.capture_id)
                       FROM capture_tags ct WHERE ct.source='manual'"""
                ).fetchone()[0],
                3,
            )
            self.assertEqual(
                connection.execute(
                    """SELECT td.name FROM capture_tags ct
                       JOIN tag_definitions td ON td.id=ct.tag_id
                       JOIN captures c ON c.id=ct.capture_id
                       WHERE c.stem='BEACH_0003' AND td.dimension='location'"""
                ).fetchone()[0],
                "演示海岸",
            )
            self.assertEqual(
                connection.execute(
                    """SELECT COUNT(*) FROM ai_analyses
                       WHERE model_id=? AND status='complete'""",
                    (DEMO_AI_MODEL_ID,),
                ).fetchone()[0],
                3,
            )
            ai_result = json.loads(connection.execute(
                """SELECT result_json FROM ai_analyses aa
                   JOIN captures c ON c.id=aa.capture_id
                   WHERE aa.model_id=? AND c.stem='BEACH_0003'""",
                (DEMO_AI_MODEL_ID,),
            ).fetchone()[0])
            self.assertTrue(ai_result["quality_summary"].startswith("模拟结果："))

            inventory_path = seed_demo_equipment(settings.workspace)
            inventory_path.write_text(
                inventory_path.read_text(encoding="utf-8").replace(
                    "演示旅行三脚架", "我修改过的三脚架"
                ),
                encoding="utf-8",
            )
            seed_demo_equipment(settings.workspace)
            self.assertIn("我修改过的三脚架", inventory_path.read_text(encoding="utf-8"))
            project_root = Path(__file__).resolve().parents[1]
            equipment = build_equipment_catalog(
                connection,
                project_root / "equipment" / "profile.toml",
                project_root / "equipment" / "catalogs" / "fujifilm-x.toml",
                inventory_path,
            )
            self.assertEqual(equipment["summary"]["camera_count"], 1)
            self.assertGreaterEqual(equipment["summary"]["lens_count"], 3)
            self.assertEqual(equipment["summary"]["accessory_count"], 1)
            self.assertEqual(equipment["accessories"][0]["album_count"], 1)
            self.assertTrue(any(
                item["display_name"] == "我修改过的三脚架"
                for item in equipment["accessories"]
            ))
            connection.close()


if __name__ == "__main__":
    unittest.main()
