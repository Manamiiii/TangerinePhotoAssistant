import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.settings import Settings, write_safe_config


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

    def test_safe_config_is_portable_and_never_overwritten(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            originals = root / "photos"
            originals.mkdir()
            config = root / "config.toml"
            write_safe_config(config, originals, root / "workspace", root / "cache")
            settings = Settings.load(config)
            self.assertEqual(settings.validate(), [])
            self.assertEqual(settings.originals, originals.resolve())
            self.assertTrue(settings.read_only)
            self.assertTrue(settings.offline_only)
            self.assertFalse(settings.allow_move)
            self.assertFalse(settings.allow_delete)
            self.assertFalse(settings.allow_original_metadata_write)
            with self.assertRaises(FileExistsError):
                write_safe_config(config, originals, root / "other", root / "other-cache")


if __name__ == "__main__":
    unittest.main()
