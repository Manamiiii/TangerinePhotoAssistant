import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.portable_data import (
    RESTORE_CONFIRMATION,
    build_portable_backup,
    preflight_restore,
    restore_portable_backup,
)
from tangerine_photo_assistant.work_queue import save_work_item_state


class PortableDataTests(unittest.TestCase):
    def _catalog(self, path: Path):
        connection = connect(path)
        connection.execute("INSERT INTO captures(capture_key,parent_relative,stem,captured_at,pairing_status) VALUES ('album/IMG_1','album','IMG_1',NULL,'jpeg_only')")
        connection.commit()
        return connection

    def _add_ai_result(self, connection):
        capture_id = connection.execute("SELECT id FROM captures").fetchone()[0]
        connection.execute("""INSERT INTO ai_runs(
            id,mode,model_id,prompt_version,status,requested_count,completed_count,started_at
        ) VALUES (1,'benchmark','model','v1','complete',1,1,'now')""")
        connection.execute("""INSERT INTO ai_analyses(
            id,run_id,capture_id,model_id,prompt_version,status,selection_reason,result_json
        ) VALUES (1,1,?,'model','v1','complete','test','{}')""", (capture_id,))
        connection.commit()

    def test_backup_is_path_free_and_restore_is_preflighted(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._catalog(root / "source.sqlite3")
            capture_id = source.execute("SELECT id FROM captures").fetchone()[0]
            source.execute("INSERT INTO capture_reviews(capture_id,user_rating,user_pick,user_reject,user_note,selection_reason_json,updated_at) VALUES (?,5,1,0,'保留','[\"构图差异\"]','now')", (capture_id,))
            source.execute("INSERT INTO tag_definitions(dimension,name,built_in,sort_order,created_at) VALUES ('location','测试地点',0,100,'now')")
            tag_id = source.execute("SELECT id FROM tag_definitions WHERE name='测试地点'").fetchone()[0]
            source.execute("INSERT INTO capture_tags(capture_id,tag_id,source,created_at) VALUES (?,?,'manual','now')", (capture_id, tag_id))
            source.execute("INSERT INTO similarity_group_overrides(capture_id,action,created_at,updated_at,manual_batch_key,manual_group_key) VALUES (?,'exclude','now','now','batch','group')", (capture_id,))
            source.execute("INSERT INTO edit_recipe_revisions(capture_id,parameter_space,parameters_json,status,note,created_at) VALUES (?,'tangerine-preview-v2','{}','accepted','采用','now')", (capture_id,))
            source.commit()
            self._add_ai_result(source)
            source.execute(
                "INSERT INTO ai_audit_benchmark VALUES (?,1,'now','{}')",
                (capture_id,),
            )
            source.execute(
                "INSERT INTO ai_version_reviews VALUES ('v1','rejected','需优化','now')"
            )
            source.execute(
                """INSERT INTO similarity_review_batches(
                       id,mode,group_count,capture_count,before_json,after_json,
                       status,created_at)
                   VALUES (1,'low_risk_accept',1,1,?,?,'applied','now')""",
                (
                    json.dumps([{"capture_id": capture_id, "user_pick": None,
                                 "user_reject": 0}]),
                    json.dumps([{"capture_id": capture_id, "user_pick": 1,
                                 "user_reject": 0}]),
                ),
            )
            source.execute(
                """INSERT INTO similarity_review_batch_groups(
                       batch_id,representative_capture_id,capture_ids_json,
                       confidence,requires_audit,audit_status)
                   VALUES (1,?,?,'high',1,'confirmed')""",
                (capture_id, json.dumps([capture_id])),
            )
            source.commit()
            save_work_item_state(source, "ai", 1, "ignored")
            inventory = root / "inventory.json"
            inventory.write_text(json.dumps({"version": 2, "ownership": {"camera": {"X": True}, "lens": {}, "accessory": {}}}), encoding="utf-8")

            backup = build_portable_backup(source, inventory)
            serialized = json.dumps(backup, ensure_ascii=False)
            self.assertNotIn(str(root), serialized)
            self.assertFalse(backup["privacy"]["contains_gps"])
            self.assertFalse(backup["privacy"]["contains_model_results"])
            self.assertEqual(len(backup["ai_benchmark"]), 1)
            self.assertEqual(len(backup["ai_version_reviews"]), 1)
            self.assertEqual(len(backup["similarity_review_batches"]), 1)
            source.close()

            target = self._catalog(root / "target.sqlite3")
            self._add_ai_result(target)
            preflight = preflight_restore(target, backup)
            self.assertEqual(preflight["matched_captures"], 1)
            with self.assertRaises(ValueError):
                restore_portable_backup(target, backup, root / "target-inventory.json", root / "backups", "错误")
            result = restore_portable_backup(target, backup, root / "target-inventory.json", root / "backups", RESTORE_CONFIRMATION)
            self.assertTrue(result["restored"])
            self.assertEqual(target.execute("SELECT user_rating FROM capture_reviews").fetchone()[0], 5)
            self.assertEqual(target.execute("SELECT COUNT(*) FROM capture_tags").fetchone()[0], 1)
            self.assertEqual(target.execute("SELECT COUNT(*) FROM similarity_group_overrides").fetchone()[0], 1)
            self.assertEqual(target.execute("SELECT COUNT(*) FROM edit_recipe_revisions").fetchone()[0], 1)
            self.assertEqual(target.execute("SELECT status FROM work_item_states").fetchone()[0], "ignored")
            self.assertEqual(target.execute("SELECT COUNT(*) FROM ai_audit_benchmark").fetchone()[0], 1)
            self.assertEqual(target.execute("SELECT status FROM ai_version_reviews").fetchone()[0], "rejected")
            self.assertEqual(target.execute("SELECT COUNT(*) FROM similarity_review_batches").fetchone()[0], 1)
            self.assertEqual(target.execute("SELECT audit_status FROM similarity_review_batch_groups").fetchone()[0], "confirmed")
            self.assertEqual(len(list((root / "backups").glob("*.sqlite3"))), 1)
            self.assertEqual(json.loads((root / "target-inventory.json").read_text(encoding="utf-8"))["ownership"]["camera"]["X"], True)
            target.close()


if __name__ == "__main__":
    unittest.main()
