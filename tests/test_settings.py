import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.lightroom import lightroom_preflight
from tangerine_photo_assistant.settings import (
    Settings,
    editable_config,
    save_editable_config,
    write_safe_config,
)


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

    def test_editable_config_is_backed_up_validated_and_atomically_saved(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            originals = root / "photos"
            originals.mkdir()
            photo = originals / "sample.jpg"
            photo.write_bytes(b"unchanged-photo")
            before = (photo.read_bytes(), photo.stat().st_mtime_ns)
            config = root / "config.toml"
            write_safe_config(config, originals, root / "workspace", root / "cache")
            changes = editable_config(config)
            changes["cache"]["max_size_gb"] = 30
            changes["cache"]["thumbnail_max_size_gb"] = 6
            changes["analysis"]["raw_extensions"] = [".RAF", ".CR3"]
            changes["analysis"]["metadata_batch_size"] = 64
            changes["workflow"]["daily_review_budget"] = 20
            changes["lightroom"]["catalog_root"] = str(root / "Lightroom")
            changes["lightroom"]["catalog_backup_root"] = str(root / "LightroomBackups")
            backup = save_editable_config(config, changes)

            self.assertTrue(backup.is_file())
            self.assertEqual(Settings.load(config).cache_max_size_gb, 30)
            self.assertEqual(Settings.load(config).raw_extensions, (".raf", ".cr3"))
            self.assertEqual(editable_config(config)["analysis"]["metadata_batch_size"], 64)
            self.assertEqual(Settings.load(config).daily_review_budget, 20)
            self.assertEqual(
                Settings.load(config).lightroom_catalog_root, root / "Lightroom"
            )
            self.assertIn("max_size_gb = 20", backup.read_text(encoding="utf-8"))
            self.assertEqual((photo.read_bytes(), photo.stat().st_mtime_ns), before)

            invalid = editable_config(config)
            invalid["cache"]["thumbnail_max_size_gb"] = 40
            config_before_invalid_save = config.read_bytes()
            backups_before_invalid_save = set(root.glob("config.backup-*.toml"))
            with self.assertRaises(ValueError):
                save_editable_config(config, invalid)
            self.assertEqual(config.read_bytes(), config_before_invalid_save)
            self.assertEqual(
                set(root.glob("config.backup-*.toml")), backups_before_invalid_save
            )
            self.assertEqual(Settings.load(config).thumbnail_max_size_gb, 6)

            missing_library = editable_config(config)
            missing_library["library"]["originals"] = str(root / "missing-photos")
            with self.assertRaises(ValueError):
                save_editable_config(config, missing_library)
            self.assertEqual(config.read_bytes(), config_before_invalid_save)
            self.assertFalse((root / "missing-photos").exists())

            relative_lightroom = editable_config(config)
            relative_lightroom["lightroom"]["catalog_root"] = "relative/catalog"
            with self.assertRaises(ValueError):
                save_editable_config(config, relative_lightroom)

    def test_lightroom_preflight_only_observes_catalog_and_lock(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = self.make_settings(root)
            catalog_root = root / "Lightroom"
            backup_root = root / "LightroomBackups"
            catalog_root.mkdir()
            backup_root.mkdir()
            catalog = catalog_root / "Photos.lrcat"
            catalog.write_bytes(b"catalog-fixture")
            data = catalog_root / "Photos.lrcat-data"
            data.write_bytes(b"data-fixture")
            configured = replace(
                settings,
                lightroom_catalog_root=catalog_root,
                lightroom_catalog_backup_root=backup_root,
            )
            ready = lightroom_preflight(configured)
            self.assertEqual(ready["status"], "ready_for_review")
            self.assertTrue(ready["catalogs"][0]["data_companion"])
            self.assertFalse(ready["catalog_direct_write_supported"])
            before = (catalog.read_bytes(), data.read_bytes())
            lock = catalog_root / "Photos.lrcat.lock"
            lock.write_text("open", encoding="utf-8")
            opened = lightroom_preflight(configured)
            self.assertEqual(opened["status"], "catalog_open")
            self.assertEqual(opened["locked_count"], 1)
            self.assertEqual((catalog.read_bytes(), data.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
