from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import enrich_metadata, scan_library
from tangerine_photo_assistant.metadata import PillowMetadataReader
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.quality import analyze_quality
from tangerine_photo_assistant.sample_data import generate_demo_library, seed_demo_catalog
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
            self.assertEqual(first["sample_count"], 28)
            self.assertEqual(first["event_count"], 4)
            self.assertEqual(first["exact_duplicate_count"], 2)
            self.assertEqual(len(list(target.rglob("*.JPG"))), 28)
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
            connection = connect(settings.database_path)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capture_reviews WHERE user_pick=1").fetchone()[0],
                4,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM similarity_group_overrides").fetchone()[0],
                1,
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
