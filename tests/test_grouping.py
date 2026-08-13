import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.grouping import (
    SimilarityGroupingError,
    list_similarity_group_revisions,
    restore_similarity_grouping,
    restore_similarity_group_revision,
    save_manual_similarity_grouping,
)
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.visual import (
    build_visual_fingerprints,
    rebuild_similarity_groups,
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


class ManualGroupingTests(unittest.TestCase):
    def _catalog(self, root: Path):
        settings = settings_for(root)
        album = settings.originals / "2026-08-12_测试"
        album.mkdir()
        for index in range(1, 5):
            Image.new("RGB", (64, 48), "orange").save(album / f"DSCF{index:04d}.JPG")
        connection = connect(settings.database_path)
        scan_library(connection, settings)
        for index in range(1, 5):
            connection.execute(
                "UPDATE files SET captured_at=? WHERE stem=?",
                (f"2026-08-12T10:00:0{index}", f"DSCF{index:04d}"),
            )
        connection.commit()
        rebuild_captures(connection)
        rebuild_structure(connection, settings.burst_time_gap_seconds)
        build_visual_fingerprints(connection)
        rebuild_similarity_groups(connection)
        group_id = connection.execute("SELECT id FROM similarity_groups").fetchone()[0]
        capture_ids = [
            row[0]
            for row in connection.execute(
                "SELECT capture_id FROM similarity_group_captures WHERE group_id=? ORDER BY sequence_index",
                (group_id,),
            )
        ]
        return connection, group_id, capture_ids

    def test_confirmed_edit_persists_and_whole_batch_can_be_restored(self) -> None:
        with TemporaryDirectory() as directory:
            connection, group_id, capture_ids = self._catalog(Path(directory))
            result = save_manual_similarity_grouping(
                connection,
                group_id,
                [capture_ids[:2]],
                capture_ids[2:],
            )
            self.assertTrue(str(result["batch_key"]).startswith("manual:"))
            self.assertEqual(result["similarity_groups"], 1)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM similarity_group_overrides WHERE manual_batch_key=?",
                    (result["batch_key"],),
                ).fetchone()[0],
                4,
            )
            history = list_similarity_group_revisions(connection, capture_ids[0])
            self.assertEqual(history[0]["operation"], "manual_edit")
            self.assertFalse(history[0]["automatic"])
            album_id = connection.execute(
                "SELECT event_id FROM event_captures WHERE capture_id=?",
                (capture_ids[0],),
            ).fetchone()[0]
            global_history = list_similarity_group_revisions(connection, limit=20)
            self.assertEqual(global_history[0]["id"], result["revision_id"])
            self.assertEqual(global_history[0]["representative_capture_id"], capture_ids[0])
            self.assertTrue(global_history[0]["album_names"])
            self.assertEqual(
                list_similarity_group_revisions(
                    connection, limit=20, album_id=album_id
                )[0]["id"],
                result["revision_id"],
            )
            self.assertEqual(
                list_similarity_group_revisions(
                    connection, limit=20, album_id=album_id + 1000
                ),
                [],
            )
            restored = restore_similarity_grouping(connection, capture_ids[0])
            self.assertEqual(restored["restored_overrides"], 4)
            self.assertEqual(restored["similarity_groups"], 1)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM similarity_group_overrides").fetchone()[0],
                0,
            )
            self.assertTrue(
                list_similarity_group_revisions(connection, capture_ids[0])[0]["automatic"]
            )
            restored_revision = restore_similarity_group_revision(
                connection, result["revision_id"]
            )
            self.assertGreater(restored_revision["revision_id"], result["revision_id"])
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM similarity_group_overrides"
                ).fetchone()[0],
                4,
            )
            restore_similarity_group_revision(
                connection, result["revision_id"], use_before=True
            )
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM similarity_group_overrides"
                ).fetchone()[0],
                0,
            )
            connection.close()

    def test_invalid_edit_is_rejected_without_partial_writes(self) -> None:
        with TemporaryDirectory() as directory:
            connection, group_id, capture_ids = self._catalog(Path(directory))
            with self.assertRaises(SimilarityGroupingError):
                save_manual_similarity_grouping(
                    connection,
                    group_id,
                    [[capture_ids[0], capture_ids[1]]],
                    [capture_ids[1]],
                )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM similarity_group_overrides").fetchone()[0],
                0,
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
