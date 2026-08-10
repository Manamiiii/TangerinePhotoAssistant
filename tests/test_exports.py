from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.exports import write_phone_share_export
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.metadata import PillowMetadataReader
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings


def _settings(root: Path) -> Settings:
    originals = root / "photos"
    originals.mkdir()
    return Settings(
        originals=originals,
        workspace=root / "workspace",
        cache_root=root / "cache",
        cache_max_size_gb=2,
        thumbnail_max_size_gb=1,
        offline_only=True,
        read_only=True,
        allow_move=False,
        allow_delete=False,
        allow_original_metadata_write=False,
        raw_extensions=(".raf",),
        exiftool=None,
        metadata_batch_size=8,
        burst_time_gap_seconds=3.0,
    )


class PhoneShareExportTests(unittest.TestCase):
    def test_export_creates_resized_metadata_free_jpeg_zip(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = _settings(root)
            for index, color in enumerate(("orange", "blue"), 1):
                exif = Image.Exif()
                exif[271] = "TEST CAMERA"
                Image.new("RGB", (1600, 1200), color).save(
                    settings.originals / f"PHOTO_{index:04d}.JPG",
                    exif=exif,
                )
            connection = connect(settings.database_path)
            try:
                scan_library(connection, settings, PillowMetadataReader())
                rebuild_captures(connection)
                capture_ids = [row[0] for row in connection.execute("SELECT id FROM captures ORDER BY id")]

                result = write_phone_share_export(
                    connection,
                    settings.originals,
                    settings.reports_path,
                    capture_ids,
                    max_edge=1080,
                    quality=85,
                )

                archive_path = settings.reports_path / result["filename"]
                self.assertTrue(archive_path.is_file())
                self.assertEqual(result["photo_count"], 2)
                with ZipFile(archive_path) as archive:
                    jpeg_names = [name for name in archive.namelist() if name.endswith(".jpg")]
                    self.assertEqual(len(jpeg_names), 2)
                    with Image.open(BytesIO(archive.read(jpeg_names[0]))) as exported:
                        self.assertEqual(max(exported.size), 1080)
                        self.assertIsNone(exported.getexif().get(271))
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
