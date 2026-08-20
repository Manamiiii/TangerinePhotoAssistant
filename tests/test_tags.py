import json
import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.ai_analysis import update_ai_review
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.queries.details import query_capture_detail
from tangerine_photo_assistant.tags import (
    analysis_subject_tag_status,
    clear_analysis_subject_tags,
    CaptureTagError,
    CaptureTagNotFoundError,
    create_tag_definition,
    delete_tag_definition,
    list_tag_definitions,
    replace_manual_capture_tags,
    sync_analysis_subject_tags,
    update_tag_definition,
    update_manual_tag_for_captures,
)


class CaptureTagTests(unittest.TestCase):
    def test_definition_management_preserves_used_and_builtin_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            created = create_tag_definition(connection, "subject", "街头")
            renamed = update_tag_definition(
                connection, created["id"], name="街头摄影", active=False
            )
            self.assertEqual(renamed["name"], "街头摄影")
            self.assertFalse(renamed["active"])
            restored = create_tag_definition(connection, "subject", "街头摄影")
            self.assertTrue(restored["active"])
            delete_tag_definition(connection, created["id"])
            self.assertNotIn("街头摄影", {item["name"] for item in list_tag_definitions(connection)})

            built_in = next(
                item for item in list_tag_definitions(connection)
                if item["dimension"] == "subject" and item["built_in"]
            )
            with self.assertRaisesRegex(CaptureTagError, "不能改名"):
                update_tag_definition(connection, built_in["id"], name="新名称")
            with self.assertRaisesRegex(CaptureTagError, "不能删除"):
                delete_tag_definition(connection, built_in["id"])

            connection.execute(
                """INSERT INTO captures(capture_key,stem,parent_relative,pairing_status)
                   VALUES ('used','used','','jpeg_only')"""
            )
            capture_id = int(connection.execute("SELECT last_insert_rowid()").fetchone()[0])
            connection.commit()
            used = create_tag_definition(connection, "location", "常用地点")
            replace_manual_capture_tags(
                connection, capture_id, [{"dimension": "location", "name": "常用地点"}]
            )
            with self.assertRaisesRegex(CaptureTagError, "正在被照片使用"):
                delete_tag_definition(connection, used["id"])
            update_tag_definition(connection, used["id"], active=False)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM capture_tags").fetchone()[0], 1
            )
            connection.close()

    def test_analysis_subject_sync_is_repeatable_and_preserves_manual_tags(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            connection.executemany(
                """INSERT INTO captures(capture_key, stem, parent_relative, pairing_status)
                   VALUES (?, ?, '', 'jpeg_only')""",
                (("A", "A"), ("B", "B")),
            )
            first_id, second_id = [row[0] for row in connection.execute(
                "SELECT id FROM captures ORDER BY id"
            )]
            connection.commit()
            replace_manual_capture_tags(
                connection, first_id, [{"dimension": "subject", "name": "旅行"}]
            )
            connection.execute(
                """INSERT INTO ai_runs(mode, model_id, prompt_version, status,
                       requested_count, completed_count, started_at)
                   VALUES ('benchmark', 'test', 'v4', 'complete', 2, 2, 'now')"""
            )
            run_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
            results = (
                {"subject_type": "人像", "overall_confidence": 0.8},
                {"subject_tags": [
                    {"name": "建筑", "confidence": 0.7}, "旅行", "建筑",
                ], "overall_confidence": 0.6},
            )
            connection.executemany(
                """INSERT INTO ai_analyses(
                       run_id, capture_id, model_id, prompt_version, status,
                       selection_reason, result_json, finished_at)
                   VALUES (?, ?, 'test', 'v4', 'complete', 'test', ?, 'now')""",
                ((run_id, first_id, json.dumps(results[0], ensure_ascii=False)),
                 (run_id, second_id, json.dumps(results[1], ensure_ascii=False))),
            )
            connection.commit()

            synced = sync_analysis_subject_tags(connection)
            self.assertEqual(synced["synchronized_captures"], 2)
            self.assertEqual(synced["tag_links"], 3)
            self.assertEqual(analysis_subject_tag_status(connection), {
                "eligible_captures": 2, "tagged_captures": 2,
                "subject_count": 3, "tag_links": 3,
            })
            first_tags = connection.execute(
                """SELECT td.name, ct.source FROM capture_tags ct
                   JOIN tag_definitions td ON td.id=ct.tag_id
                   WHERE ct.capture_id=? ORDER BY ct.source, td.name""",
                (first_id,),
            ).fetchall()
            self.assertEqual(
                {tuple(row) for row in first_tags},
                {("人像", "analysis"), ("旅行", "manual")},
            )
            self.assertEqual(sync_analysis_subject_tags(connection)["tag_links"], 3)
            first_analysis_id = connection.execute(
                "SELECT id FROM ai_analyses WHERE capture_id=?", (first_id,)
            ).fetchone()[0]
            update_ai_review(connection, first_analysis_id, "inaccurate", "题材判断错误")
            self.assertEqual(analysis_subject_tag_status(connection), {
                "eligible_captures": 1, "tagged_captures": 1,
                "subject_count": 2, "tag_links": 2,
            })
            self.assertEqual(clear_analysis_subject_tags(connection), 2)
            self.assertEqual(analysis_subject_tag_status(connection)["tagged_captures"], 0)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM capture_tags WHERE source='manual'"
                ).fetchone()[0],
                1,
            )
            connection.close()

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
