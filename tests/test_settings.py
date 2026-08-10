from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tangerine_photo_assistant.settings import Settings


class SettingsTests(unittest.TestCase):
    def make_settings(self, root: Path, *, offline_only: bool = True) -> Settings:
        originals = root / "originals"
        originals.mkdir()
        return Settings(
            originals=originals,
            workspace=root / "workspace",
            cache_root=root / "cache",
            cache_max_size_gb=40,
            offline_only=offline_only,
            read_only=True,
            allow_move=False,
            allow_delete=False,
            allow_original_metadata_write=False,
            raw_extensions=(".raf", ".dng"),
            exiftool=None,
            metadata_batch_size=32,
            burst_time_gap_seconds=3.0,
        )

    def test_safe_defaults_validate_existing_library(self) -> None:
        with TemporaryDirectory() as directory:
            settings = self.make_settings(Path(directory))
            self.assertEqual(settings.validate(), [])

    def test_online_analysis_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            settings = self.make_settings(Path(directory), offline_only=False)
            self.assertIn("Offline-only analysis must remain enabled", settings.validate())


if __name__ == "__main__":
    unittest.main()
