import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.queries.details import query_capture_detail
from tangerine_photo_assistant.tags import (
    CaptureTagError,
    CaptureTagNotFoundError,
    replace_manual_capture_tags,
)


class CaptureTagTests(unittest.TestCase):
    def test_manual_tags_replace_atomically_and_preserve_analysis_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            connection.execute(
                """INSERT INTO captures(capture_key, stem, parent_relative, pairing_status)
                   VALUES ('A', 'A', '', 'paired')"""
            )
            capture_id = connection.execute("SELECT id FROM captures").fetchone()[0]
            analysis_tag = connection.execute(
                "SELECT id FROM tag_definitions WHERE dimension='problem' AND name='失焦'"
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO capture_tags(capture_id, tag_id, source, confidence, created_at)
                   VALUES (?, ?, 'analysis', 0.8, CURRENT_TIMESTAMP)""",
                (capture_id, analysis_tag),
            )
            connection.commit()

            saved = replace_manual_capture_tags(connection, capture_id, [
                {"dimension": "subject", "name": "风景"},
                {"dimension": "status", "name": "待修"},
                {"dimension": "location", "name": "上海"},
                {"dimension": "subject", "name": "风景"},
            ])
            self.assertEqual(
                {(item["dimension"], item["name"], item["source"]) for item in saved},
                {
                    ("subject", "风景", "manual"),
                    ("status", "待修", "manual"),
                    ("location", "上海", "manual"),
                    ("problem", "失焦", "analysis"),
                },
            )

            with self.assertRaises(CaptureTagError):
                replace_manual_capture_tags(connection, capture_id, [
                    {"dimension": "status", "name": "待修"},
                    {"dimension": "status", "name": "已修"},
                ])
            remaining = connection.execute(
                """SELECT td.dimension, td.name, ct.source
                   FROM capture_tags ct JOIN tag_definitions td ON td.id=ct.tag_id
                   WHERE ct.capture_id=?""",
                (capture_id,),
            ).fetchall()
            self.assertEqual(len(remaining), 4)

            database_path = Path(temporary) / "catalog.sqlite3"
            connection.close()
            detail = query_capture_detail(database_path, capture_id)
            self.assertIn("tag_catalog", detail)
            self.assertEqual(
                {(tag["dimension"], tag["name"]) for tag in detail["tags"]},
                {
                    ("subject", "风景"),
                    ("status", "待修"),
                    ("location", "上海"),
                    ("problem", "失焦"),
                },
            )

            connection = connect(database_path)
            with self.assertRaises(CaptureTagNotFoundError):
                replace_manual_capture_tags(connection, capture_id + 1, [])
            connection.close()


if __name__ == "__main__":
    unittest.main()
