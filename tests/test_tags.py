import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.queries.details import query_capture_detail
from tangerine_photo_assistant.tags import (
    CaptureTagError,
    CaptureTagNotFoundError,
    replace_manual_capture_tags,
    update_manual_tag_for_captures,
)


class CaptureTagTests(unittest.TestCase):
    def test_manual_tags_replace_atomically_and_preserve_analysis_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            connection.execute(
                """INSERT INTO captures(capture_key, stem, parent_relative, pairing_status)
                   VALUES ('A', 'A', '', 'paired')"""
            )
            connection.executemany(
                """INSERT INTO tag_definitions(
                       dimension, name, built_in, active, sort_order, created_at
                   ) VALUES ('status', ?, 1, 0, 500, CURRENT_TIMESTAMP)""",
                (("精选",), ("待淘汰",)),
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
            self.assertNotIn(
                "精选",
                {tag["name"] for tag in detail["tag_catalog"] if tag["dimension"] == "status"},
            )
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
            connection.execute(
                """INSERT INTO captures(capture_key, stem, parent_relative, pairing_status)
                   VALUES ('B', 'B', '', 'jpeg_only')"""
            )
            second_id = connection.execute(
                "SELECT id FROM captures WHERE capture_key='B'"
            ).fetchone()[0]
            connection.commit()
            with self.assertRaisesRegex(CaptureTagError, "选片入选/排除"):
                update_manual_tag_for_captures(
                    connection, [second_id], dimension="status", name="精选", action="add",
                )
            with self.assertRaisesRegex(CaptureTagError, "选片入选/排除"):
                replace_manual_capture_tags(
                    connection, second_id, [{"dimension": "status", "name": "待淘汰"}],
                )
            self.assertEqual(
                update_manual_tag_for_captures(
                    connection, [capture_id, second_id],
                    dimension="status", name="已修", action="add",
                ),
                2,
            )
            statuses = connection.execute(
                """SELECT ct.capture_id, td.name FROM capture_tags ct
                   JOIN tag_definitions td ON td.id=ct.tag_id
                   WHERE td.dimension='status' AND ct.source='manual'
                   ORDER BY ct.capture_id"""
            ).fetchall()
            self.assertEqual([tuple(row) for row in statuses], [(capture_id, "已修"), (second_id, "已修")])
            legacy_tag_id = connection.execute(
                "SELECT id FROM tag_definitions WHERE dimension='status' AND name='精选'"
            ).fetchone()[0]
            connection.execute(
                "DELETE FROM capture_tags WHERE capture_id=? AND source='manual'", (second_id,)
            )
            connection.execute(
                """INSERT INTO capture_tags(capture_id, tag_id, source, created_at)
                   VALUES (?, ?, 'manual', CURRENT_TIMESTAMP)""",
                (second_id, legacy_tag_id),
            )
            connection.commit()
            preserved = replace_manual_capture_tags(
                connection, second_id, [{"dimension": "status", "name": "精选"}],
            )
            self.assertIn("精选", {tag["name"] for tag in preserved})
            self.assertEqual(
                update_manual_tag_for_captures(
                    connection, [capture_id],
                    dimension="status", name="已修", action="remove",
                ),
                1,
            )
            definitions_before = connection.execute(
                "SELECT COUNT(*) FROM tag_definitions"
            ).fetchone()[0]
            self.assertEqual(
                update_manual_tag_for_captures(
                    connection, [second_id],
                    dimension="location", name="不存在的地点", action="remove",
                ),
                0,
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM tag_definitions").fetchone()[0],
                definitions_before,
            )
            with self.assertRaises(CaptureTagNotFoundError):
                replace_manual_capture_tags(connection, capture_id + 1000, [])
            connection.close()


if __name__ == "__main__":
    unittest.main()
