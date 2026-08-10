from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from tangerine_photo_assistant.sample_data import generate_demo_library


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


if __name__ == "__main__":
    unittest.main()
