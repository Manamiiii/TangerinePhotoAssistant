import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.reviews import (
    CaptureReviewError,
    CaptureReviewNotFoundError,
    save_capture_review,
)


class CaptureReviewTests(unittest.TestCase):
    def test_review_upsert_and_validation_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            connection.execute(
                """INSERT INTO captures(capture_key, stem, parent_relative, pairing_status)
                   VALUES ('A', 'A', '', 'jpeg_only')"""
            )
            capture_id = connection.execute("SELECT id FROM captures").fetchone()[0]
            connection.commit()

            save_capture_review(
                connection,
                capture_id,
                user_rating=4,
                user_pick=True,
                user_reject=False,
                user_note="首选",
                selection_reasons=["表情差异", "关键瞬间"],
            )
            reasons = connection.execute(
                "SELECT selection_reason_json FROM capture_reviews"
            ).fetchone()[0]
            self.assertEqual(reasons, '["表情差异", "关键瞬间"]')
            save_capture_review(
                connection,
                capture_id,
                user_rating=5,
                user_pick=False,
                user_reject=False,
                user_note="复核后调整",
            )
            row = connection.execute(
                "SELECT user_rating, user_pick, user_reject, user_note FROM capture_reviews"
            ).fetchone()
            self.assertEqual(tuple(row), (5, 0, 0, "复核后调整"))
            self.assertEqual(
                connection.execute(
                    "SELECT selection_reason_json FROM capture_reviews"
                ).fetchone()[0],
                "[]",
            )

            with self.assertRaises(CaptureReviewError):
                save_capture_review(
                    connection,
                    capture_id,
                    user_rating=5,
                    user_pick=True,
                    user_reject=False,
                    user_note=None,
                    selection_reasons=["技术分高"],
                )

            with self.assertRaises(CaptureReviewError):
                save_capture_review(
                    connection,
                    capture_id,
                    user_rating=6,
                    user_pick=False,
                    user_reject=False,
                    user_note=None,
                )
            with self.assertRaises(CaptureReviewError):
                save_capture_review(
                    connection,
                    capture_id,
                    user_rating=5,
                    user_pick=True,
                    user_reject=True,
                    user_note=None,
                )
            self.assertEqual(
                tuple(connection.execute(
                    "SELECT user_rating, user_pick, user_reject, user_note FROM capture_reviews"
                ).fetchone()),
                (5, 0, 0, "复核后调整"),
            )
            with self.assertRaises(CaptureReviewNotFoundError):
                save_capture_review(
                    connection,
                    capture_id + 1000,
                    user_rating=None,
                    user_pick=False,
                    user_reject=False,
                    user_note=None,
                )
            connection.close()


if __name__ == "__main__":
    unittest.main()
