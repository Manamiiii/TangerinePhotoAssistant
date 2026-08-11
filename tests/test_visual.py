from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from PIL import Image

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.visual import (
    build_visual_fingerprints,
    find_exact_duplicates,
    fingerprint_image,
    hamming_distance,
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


def save_image(path: Path, color: tuple[int, int, int], accent: int = 0) -> None:
    image = Image.new("RGB", (64, 48), color)
    for x in range(8 + accent, 28 + accent):
        for y in range(10, 38):
            image.putpixel((x, y), (245, 245, 245))
    image.save(path, quality=95)


class VisualAnalysisTests(unittest.TestCase):
    def test_fingerprint_is_stable_and_distinguishes_changed_composition(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            first = root / "first.jpg"
            copy = root / "copy.jpg"
            changed = root / "changed.jpg"
            save_image(first, (20, 30, 40))
            copy.write_bytes(first.read_bytes())
            save_image(changed, (20, 30, 40), accent=25)
            left = fingerprint_image(first)
            self.assertEqual(left, fingerprint_image(copy))
            self.assertGreater(hamming_distance(left.dhash64, fingerprint_image(changed).dhash64), 0)

    def test_duplicates_and_burst_similarity_are_persisted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            first_dir = settings.originals / "MyPhoto" / "宝贝" / "2026.8.6_测试"
            second_dir = settings.originals / "MyPhoto" / "风光" / "2026.8.6_测试"
            first_dir.mkdir(parents=True)
            second_dir.mkdir(parents=True)
            for index, accent in enumerate((0, 1, 2), 1):
                save_image(first_dir / f"DSCF{index:04d}.JPG", (30, 80, 120), accent)
            duplicate = first_dir / "DSCF0001.JPG"
            (second_dir / "DSCF0001.JPG").write_bytes(duplicate.read_bytes())

            connection = connect(settings.database_path)
            scan_library(connection, settings)
            for index in range(1, 4):
                connection.execute(
                    "UPDATE files SET captured_at = ? WHERE parent_relative LIKE ? AND stem = ?",
                    (f"2026-08-06T10:00:0{index}", "%宝贝%", f"DSCF{index:04d}"),
                )
            connection.commit()
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)

            duplicate_result = find_exact_duplicates(connection)
            fingerprint_result = build_visual_fingerprints(connection)
            similarity_result = rebuild_similarity_groups(connection)

            self.assertEqual(duplicate_result["duplicate_groups"], 1)
            self.assertEqual(duplicate_result["duplicate_files"], 2)
            self.assertEqual(fingerprint_result["fingerprint_errors"], 0)
            self.assertGreaterEqual(similarity_result["similarity_groups"], 1)
            ordered_capture_ids = [
                row[0] for row in connection.execute(
                    "SELECT capture_id FROM similarity_group_captures ORDER BY sequence_index"
                )
            ]
            middle_capture_id = ordered_capture_ids[1]
            connection.execute(
                """INSERT INTO similarity_group_overrides(
                       capture_id, action, created_at, updated_at
                   ) VALUES (?, 'split_before', 'now', 'now')""",
                (middle_capture_id,),
            )
            connection.commit()
            split_result = rebuild_similarity_groups(connection)
            self.assertEqual(split_result["similarity_groups"], 1)
            split_members = [
                row[0] for row in connection.execute(
                    "SELECT capture_id FROM similarity_group_captures ORDER BY sequence_index"
                )
            ]
            self.assertEqual(split_members, ordered_capture_ids[1:])
            connection.execute(
                "UPDATE similarity_group_overrides SET action='exclude' WHERE capture_id=?",
                (middle_capture_id,),
            )
            connection.commit()
            excluded_result = rebuild_similarity_groups(connection)
            self.assertEqual(excluded_result["similarity_groups"], 0)
            connection.execute(
                "DELETE FROM similarity_group_overrides WHERE capture_id=?",
                (middle_capture_id,),
            )
            connection.commit()
            restored_result = rebuild_similarity_groups(connection)
            self.assertEqual(restored_result["similarity_groups"], 1)
            event_ids = {
                row[0] for row in connection.execute("SELECT id FROM events")
            }
            burst_ids = {
                row[0] for row in connection.execute("SELECT id FROM bursts")
            }
            similarity_ids = {
                row[0] for row in connection.execute("SELECT id FROM similarity_groups")
            }
            capture_id = connection.execute(
                "SELECT id FROM captures ORDER BY id LIMIT 1"
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO capture_reviews(
                       capture_id, user_rating, user_pick, user_reject, updated_at
                   ) VALUES (?, 5, 1, 0, 'now')""",
                (capture_id,),
            )
            connection.commit()

            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)

            self.assertEqual(
                event_ids, {row[0] for row in connection.execute("SELECT id FROM events")}
            )
            self.assertEqual(
                burst_ids, {row[0] for row in connection.execute("SELECT id FROM bursts")}
            )
            self.assertEqual(
                similarity_ids,
                {row[0] for row in connection.execute("SELECT id FROM similarity_groups")},
            )
            self.assertEqual(
                connection.execute(
                    "SELECT user_rating FROM capture_reviews WHERE capture_id=?", (capture_id,)
                ).fetchone()[0],
                5,
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
