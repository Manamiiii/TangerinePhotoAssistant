from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.metadata import MetadataResult
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import (
    CaptureRecord,
    _can_join_burst,
    rebuild_structure,
    structure_summary,
)


class MappingMetadataReader:
    def __init__(self, times: dict[str, str]) -> None:
        self.times = times

    def read(self, paths):
        for path in paths:
            yield MetadataResult(
                path=path,
                values={
                    "DateTimeOriginal": self.times[path.stem],
                    "Make": "FUJIFILM",
                    "Model": "X-S20",
                    "LensModel": "XF23mmF1.4 R LM WR",
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
        raw_extensions=(".raf",),
        exiftool=None,
        metadata_batch_size=8,
        burst_time_gap_seconds=3.0,
    )


class StructureTests(unittest.TestCase):
    def test_burst_sequence_requires_consecutive_matching_file_numbers(self) -> None:
        def capture(stem: str, second: int) -> CaptureRecord:
            return CaptureRecord(
                id=second, parent_relative="album", stem=stem,
                captured_at=f"2026-08-11T10:00:0{second}", camera_model="X-S20",
            )

        self.assertTrue(_can_join_burst(capture("DSCF0001", 0), capture("DSCF0002", 1), 3.0))
        self.assertFalse(_can_join_burst(capture("DSCF0001", 0), capture("DSCF0003", 1), 3.0))
        self.assertFalse(_can_join_burst(capture("DSCF0001", 0), capture("IMG_0002", 1), 3.0))
        self.assertTrue(_can_join_burst(capture("DSCF9999", 0), capture("DSCF0001", 1), 3.0))

    def test_merges_legacy_subject_folders_and_groups_bursts(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            sources = {
                "MyPhoto/宝贝/2025.11.2.长隆": ["DSCF0001", "DSCF0003"],
                "MyPhoto/风光/2025.11.2.长隆": ["DSCF0002"],
                "MyPhoto/家人": ["DSCF0100", "DSCF0101"],
                "素材/摄影教程/第1章": ["SAMPLE01"],
            }
            times = {
                "DSCF0001": "2025:11:02 10:00:00",
                "DSCF0002": "2025:11:02 10:00:01",
                "DSCF0003": "2025:11:02 10:00:02",
                "DSCF0100": "2025:12:01 09:00:00",
                "DSCF0101": "2025:12:02 09:00:00",
                "SAMPLE01": "2018:01:01 12:00:00",
            }
            for relative, stems in sources.items():
                folder = settings.originals / relative
                folder.mkdir(parents=True)
                for stem in stems:
                    (folder / f"{stem}.JPG").write_bytes(b"jpeg")
                    (folder / f"{stem}.RAF").write_bytes(b"raw")

            connection = connect(settings.database_path)
            scan_library(connection, settings, MappingMetadataReader(times))
            rebuild_captures(connection)
            result = rebuild_structure(connection, settings.burst_time_gap_seconds)
            summary = structure_summary(connection)

            event = connection.execute(
                "SELECT * FROM events WHERE proposed_name LIKE '%长隆%'"
            ).fetchone()
            source_count = connection.execute(
                "SELECT COUNT(*) FROM event_sources WHERE event_id = ?", (event["id"],)
            ).fetchone()[0]

            self.assertEqual(event["capture_count"], 3)
            self.assertEqual(source_count, 2)
            self.assertEqual(summary["event_count"], 3)
            self.assertEqual(result["excluded_reference_captures"], 1)
            self.assertEqual(result["candidate_bursts"], 1)
            self.assertEqual(result["largest_burst"], 3)
            connection.close()


if __name__ == "__main__":
    unittest.main()
