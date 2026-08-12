import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.metadata import MetadataResult, PillowMetadataReader, database_fields
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.reporting import build_report
from tangerine_photo_assistant.settings import Settings


class FakeMetadataReader:
    def read(self, paths):
        for path in paths:
            yield MetadataResult(
                path=path,
                values={
                    "DateTimeOriginal": "2025:10:03 16:42:08",
                    "Make": "FUJIFILM",
                    "Model": "X-S20",
                    "LensModel": "XF23mmF1.4 R LM WR",
                    "ExposureTime": 0.004,
                    "FNumber": 1.4,
                    "ISO": 400,
                    "FocalLength": 23.0,
                },
            )


def settings_for(root: Path) -> Settings:
    originals = root / "originals"
    originals.mkdir()
    return Settings(
        originals=originals,
        workspace=root / "workspace",
        cache_root=root / "cache",
        cache_max_size_gb=40,
        offline_only=True,
        read_only=True,
        allow_move=False,
        allow_delete=False,
        allow_original_metadata_write=False,
        raw_extensions=(".raf", ".dng"),
        exiftool=None,
        metadata_batch_size=8,
        burst_time_gap_seconds=3.0,
    )


class InventoryTests(unittest.TestCase):
    def test_pillow_metadata_reader_reads_common_jpeg_exif(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "sample.jpg"
            exif = Image.Exif()
            exif[271] = "FUJIFILM"
            exif[272] = "X-S20"
            exif[306] = "2026:06:19 15:00:01"
            Image.new("RGB", (48, 32), "orange").save(path, exif=exif)

            result = next(PillowMetadataReader().read([path]))

            self.assertIsNone(result.error)
            self.assertIsNotNone(result.values)
            fields = database_fields(result.values or {})
            self.assertEqual(fields["captured_at"], "2026-06-19T15:00:01")
            self.assertEqual(fields["camera_model"], "X-S20")
            self.assertEqual(fields["width"], 48)
            self.assertEqual(fields["height"], 32)

    def test_scan_pairs_jpeg_and_raw_and_enriches_metadata(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            event = settings.originals / "旅行" / "2025-10-03_测试"
            event.mkdir(parents=True)
            for name in ("DSCF0001.JPG", "DSCF0001.RAF", "DSCF0002.JPG", "notes.txt"):
                (event / name).write_bytes(name.encode("utf-8"))

            connection = connect(settings.database_path)
            scan_library(connection, settings, FakeMetadataReader())
            pairing = rebuild_captures(connection)
            report = build_report(connection)

            self.assertEqual(report["files"]["count"], 4)
            self.assertEqual(pairing["paired"], 1)
            self.assertEqual(pairing["jpeg_only"], 1)
            metadata = connection.execute(
                "SELECT metadata_status, camera_model FROM files WHERE extension = '.raf'"
            ).fetchone()
            self.assertEqual(metadata["metadata_status"], "complete")
            self.assertEqual(metadata["camera_model"], "X-S20")
            captured_at = connection.execute(
                "SELECT captured_at FROM files WHERE extension = '.raf'"
            ).fetchone()["captured_at"]
            self.assertEqual(captured_at, "2025-10-03T16:42:08")
            note_status = connection.execute(
                "SELECT metadata_status FROM files WHERE extension = '.txt'"
            ).fetchone()["metadata_status"]
            self.assertEqual(note_status, "not_applicable")
            connection.close()

    def test_second_scan_marks_removed_file_missing(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            photo = settings.originals / "DSCF0001.JPG"
            photo.write_bytes(b"photo")
            connection = connect(settings.database_path)

            scan_library(connection, settings)
            photo.unlink()
            scan_library(connection, settings)

            row = connection.execute(
                "SELECT present FROM files WHERE file_name = 'DSCF0001.JPG'"
            ).fetchone()
            self.assertEqual(row["present"], 0)
            connection.close()


if __name__ == "__main__":
    unittest.main()
