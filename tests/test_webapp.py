from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pydantic import ValidationError

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.webapp import (
    AiStartRequest,
    _query_analysis_overview,
    _query_bursts,
    _query_duplicates,
    _query_events,
    _query_inbox,
    _query_overview,
    _query_quality,
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
        raw_extensions=(".raf",),
        exiftool=None,
        metadata_batch_size=8,
        burst_time_gap_seconds=3.0,
    )


class WebAppQueryTests(unittest.TestCase):
    def test_ai_batch_request_has_safe_bounds(self) -> None:
        request = AiStartRequest(mode="benchmark", limit=10)
        self.assertEqual(request.limit, 10)
        with self.assertRaises(ValidationError):
            AiStartRequest(mode="benchmark", limit=0)
        with self.assertRaises(ValidationError):
            AiStartRequest(mode="benchmark", limit=5001)
        with self.assertRaises(ValidationError):
            AiStartRequest(mode="unsupported", limit=10)

    def test_overview_and_inbox_use_real_catalog_data(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            event = settings.originals / "待整理" / "2026-08-06_测试"
            event.mkdir(parents=True)
            (event / "DSCF0001.JPG").write_bytes(b"jpeg")
            (event / "DSCF0001.RAF").write_bytes(b"raw")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            connection.close()

            overview = _query_overview(settings)
            inbox = _query_inbox(settings, 10)
            events = _query_events(settings, 10, 0)
            bursts = _query_bursts(settings, 10, 0)
            duplicates = _query_duplicates(settings, 10, 0)
            analysis = _query_analysis_overview(settings)
            quality = _query_quality(settings, 10, 0)

            self.assertEqual(overview["files"]["count"], 2)
            self.assertEqual(overview["capture_total"], 1)
            self.assertEqual(inbox["count"], 1)
            self.assertEqual(inbox["items"][0]["pairing_status"], "paired")
            self.assertEqual(events["count"], 1)
            self.assertEqual(events["items"][0]["category"], "旅行")
            self.assertEqual(bursts["count"], 0)
            self.assertEqual(overview["visual"]["fingerprint_count"], 0)
            self.assertEqual(duplicates["count"], 0)
            self.assertEqual(analysis["quality"]["analyzed"], 0)
            self.assertFalse(analysis["runtime"]["ready"])
            self.assertEqual(quality["count"], 0)


if __name__ == "__main__":
    unittest.main()
