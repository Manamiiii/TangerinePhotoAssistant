import json
import unittest
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import refresh_metadata_profile, scan_library
from tangerine_photo_assistant.metadata import (
    METADATA_PROFILE_VERSION,
    ExifToolMetadataReader,
    MetadataResult,
    PillowMetadataReader,
    _gps_coordinate,
    database_fields,
    normalize_datetime,
)
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


class CurrentProfileMetadataReader(FakeMetadataReader):
    profile_version = METADATA_PROFILE_VERSION

    def read(self, paths):
        for result in super().read(paths):
            yield MetadataResult(
                path=result.path,
                values={**(result.values or {}), "ShutterType": "Mechanical", "AFMode": "AF-C"},
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
    def test_vendor_snapshots_normalize_without_real_photos(self) -> None:
        fixture = Path(__file__).parent / "fixtures" / "metadata" / "vendor_snapshots.json"
        snapshots = json.loads(fixture.read_text(encoding="utf-8"))

        self.assertEqual(len(snapshots), 8)
        for snapshot in snapshots:
            with self.subTest(vendor=snapshot["vendor"]):
                fields = database_fields(snapshot["values"])
                for key, expected in snapshot["expected"].items():
                    self.assertEqual(fields[key], expected)

    def test_datetime_and_gps_normalization_reject_invalid_values(self) -> None:
        self.assertIsNone(normalize_datetime("2026:13:40 25:61:61"))
        self.assertEqual(
            normalize_datetime("2026:08:09 10:11:12", "+99:00"),
            "2026-08-09T10:11:12",
        )
        self.assertAlmostEqual(_gps_coordinate((31, 13, 30), "N") or 0, 31.225)
        self.assertAlmostEqual(_gps_coordinate((121, 28, 0), "W") or 0, -121.4666667)
        self.assertIsNone(_gps_coordinate((95, 0, 0), "N"))

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

    def test_pillow_reader_safely_handles_no_exif_and_corrupt_images(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            plain = root / "plain.jpg"
            corrupt = root / "corrupt.jpg"
            Image.new("RGB", (24, 16), "blue").save(plain)
            corrupt.write_bytes(b"not-a-jpeg")

            plain_result, corrupt_result = PillowMetadataReader().read([plain, corrupt])

            self.assertEqual(plain_result.values, {"ImageWidth": 24, "ImageHeight": 16})
            self.assertIsNone(plain_result.error)
            self.assertIsNone(corrupt_result.values)
            self.assertTrue(corrupt_result.error)

    def test_exiftool_partial_batch_keeps_file_errors_explicit(self) -> None:
        class FakeProcess:
            def __init__(self, output: str) -> None:
                self.stdin = StringIO()
                self.stdout = StringIO(output)

            def poll(self):
                return None

        with TemporaryDirectory() as directory:
            failed = Path(directory) / "broken.raw"
            missing = Path(directory) / "missing.raw"
            output = json.dumps({"SourceFile": str(failed), "Error": "Invalid file"})
            process = FakeProcess(f"[{output}]\n{{ready1}}\n")
            reader = ExifToolMetadataReader(Path("exiftool"))

            results = list(reader._read_batch(process, [failed, missing], 1))  # type: ignore[arg-type]

            self.assertEqual(results[0].error, "Invalid file")
            self.assertIsNone(results[0].values)
            self.assertEqual(results[1].error, "No ExifTool result")

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

    def test_current_metadata_profile_backfills_complete_files(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            photo = settings.originals / "DSCF0001.JPG"
            photo.write_bytes(b"photo")
            connection = connect(settings.database_path)
            scan_library(connection, settings, FakeMetadataReader())
            rebuild_captures(connection)

            result = refresh_metadata_profile(connection, CurrentProfileMetadataReader())

            row = connection.execute(
                "SELECT metadata_profile_version, exif_json FROM files WHERE file_name=?",
                (photo.name,),
            ).fetchone()
            self.assertEqual(result["metadata_updated"], 1)
            self.assertEqual(row["metadata_profile_version"], METADATA_PROFILE_VERSION)
            self.assertIn('"ShutterType": "Mechanical"', row["exif_json"])
            connection.close()


if __name__ == "__main__":
    unittest.main()
