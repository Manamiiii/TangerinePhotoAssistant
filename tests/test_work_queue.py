from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import SCHEMA_VERSION, connect
from tangerine_photo_assistant.queries.details import query_capture_detail
from tangerine_photo_assistant.queries.quality import query_quality
from tangerine_photo_assistant.work_queue import (
    save_work_item_state,
    save_work_item_states,
    work_queue_summary,
)


class WorkQueueTests(unittest.TestCase):
    def test_quality_read_error_is_reviewable_without_exposing_raw_error(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            connection = connect(database)
            connection.execute(
                "INSERT INTO scan_runs(id,started_at,root_path,status) VALUES (1,'now','TEST','complete')"
            )
            connection.execute(
                """INSERT INTO files(
                       id,path,relative_path,parent_relative,file_name,stem,extension,
                       media_kind,size_bytes,modified_ns,first_seen_run_id,last_seen_run_id
                   ) VALUES (1,'TEST:a.jpg','a.jpg','','a.jpg','a','.jpg','jpeg',1,1,1,1)"""
            )
            connection.execute(
                "INSERT INTO captures(id,capture_key,parent_relative,stem,pairing_status) VALUES (1,'a','','a','jpeg_only')"
            )
            connection.execute("INSERT INTO capture_files VALUES (1,1,'jpeg')")
            connection.execute(
                """INSERT INTO events(
                       id,event_key,proposed_name,category,capture_count,status,
                       confidence,reason_json,created_at,updated_at
                   ) VALUES (1,'e','测试相册','日常',1,'confirmed',1,'{}','now','now')"""
            )
            connection.execute("INSERT INTO event_captures VALUES (1,1,0)")
            connection.execute(
                """INSERT INTO quality_metrics(
                       capture_id,source_file_id,algorithm_version,technical_score,
                       issue_json,size_bytes,modified_ns,computed_at,error
                   ) VALUES (1,1,'v1',0,'[]',1,1,'2020-01-01T00:00:00+00:00',
                             'cannot read D:/private/photo.jpg')"""
            )
            connection.commit()

            summary = work_queue_summary(connection)
            self.assertEqual(summary["quality"]["open_count"], 1)
            self.assertEqual(summary["quality"]["error_count"], 1)
            self.assertGreater(summary["oldest_age_days"], 1000)
            connection.close()

            page = query_quality(
                database, 20, 0, review_filter="errors", workflow_filter="open"
            )
            self.assertEqual(page["count"], 1)
            self.assertTrue(page["items"][0]["has_error"])
            self.assertNotIn("error", page["items"][0])
            self.assertGreater(page["items"][0]["workflow_age_days"], 1000)
            detail = query_capture_detail(database, 1)
            self.assertTrue(detail["has_quality_error"])
            self.assertNotIn("error", detail)

            connection = connect(database)
            saved = save_work_item_state(connection, "quality", 1, "confirmed")
            fingerprint = connection.execute(
                "SELECT fingerprint FROM work_item_states WHERE source_kind='quality' AND subject_id=1"
            ).fetchone()[0]
            self.assertNotIn("private", fingerprint)
            self.assertEqual(saved["status"], "confirmed")
            self.assertEqual(work_queue_summary(connection)["open_count"], 0)
            connection.execute(
                "UPDATE quality_metrics SET modified_ns=2 WHERE capture_id=1"
            )
            connection.commit()
            self.assertEqual(work_queue_summary(connection)["quality"]["reappeared_count"], 1)
            connection.close()
            self.assertEqual(
                query_quality(database, 20, 0, workflow_filter="reappeared")["count"],
                1,
            )

    def test_quality_findings_converge_and_changed_finding_reappears(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            connection = connect(database)
            self.assertEqual(SCHEMA_VERSION, 32)
            connection.execute(
                "INSERT INTO scan_runs(id,started_at,root_path,status) VALUES (1,'now','TEST','complete')"
            )
            connection.execute(
                """INSERT INTO files(
                       id,path,relative_path,parent_relative,file_name,stem,extension,
                       media_kind,size_bytes,modified_ns,first_seen_run_id,last_seen_run_id
                   ) VALUES (1,'TEST:a.jpg','a.jpg','','a.jpg','a','.jpg','jpeg',1,1,1,1)"""
            )
            connection.execute(
                "INSERT INTO captures(id,capture_key,parent_relative,stem,pairing_status) VALUES (1,'a','','a','jpeg_only')"
            )
            connection.execute("INSERT INTO capture_files VALUES (1,1,'jpeg')")
            connection.execute(
                """INSERT INTO events(
                       id,event_key,proposed_name,category,capture_count,status,
                       confidence,reason_json,created_at,updated_at
                   ) VALUES (1,'e','测试相册','日常',1,'confirmed',1,'{}','now','now')"""
            )
            connection.execute("INSERT INTO event_captures VALUES (1,1,0)")
            issue = json.dumps([{"code": "blur", "severity": "medium", "message": "需复核"}], ensure_ascii=False)
            connection.execute(
                """INSERT INTO quality_metrics(
                       capture_id,source_file_id,algorithm_version,technical_score,
                       issue_json,size_bytes,modified_ns,computed_at
                   ) VALUES (1,1,'v1',60,?,1,1,'now')""",
                (issue,),
            )
            connection.commit()

            self.assertEqual(work_queue_summary(connection)["quality"]["open_count"], 1)
            connection.close()
            self.assertEqual(query_quality(database, 20, 0, workflow_filter="open")["count"], 1)

            connection = connect(database)
            save_work_item_state(connection, "quality", 1, "confirmed")
            self.assertEqual(work_queue_summary(connection)["quality"]["open_count"], 0)
            connection.execute(
                "UPDATE quality_metrics SET issue_json=? WHERE capture_id=1",
                (json.dumps([{"code": "exposure", "severity": "high", "message": "新问题"}], ensure_ascii=False),),
            )
            connection.commit()
            summary = work_queue_summary(connection)
            self.assertEqual(summary["quality"]["open_count"], 1)
            self.assertEqual(summary["quality"]["reappeared_count"], 1)
            connection.close()
            page = query_quality(database, 20, 0, workflow_filter="reappeared")
            self.assertEqual(page["items"][0]["workflow_status"], "reappeared")

            connection = connect(database)
            save_work_item_state(connection, "quality", 1, "snoozed", snooze_days=7)
            self.assertEqual(work_queue_summary(connection)["quality"]["open_count"], 0)
            with self.assertRaises(ValueError):
                save_work_item_states(connection, "quality", [1, 999], "confirmed")
            state = connection.execute(
                "SELECT status FROM work_item_states WHERE source_kind='quality' AND subject_id=1"
            ).fetchone()[0]
            self.assertEqual(state, "snoozed")
            result = save_work_item_states(connection, "quality", [1, 1], "pending")
            self.assertEqual(result["affected_count"], 1)
            self.assertEqual(work_queue_summary(connection)["quality"]["open_count"], 1)
            connection.close()

    def test_risky_ai_result_leaves_queue_after_review(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            connection = connect(database)
            connection.execute(
                "INSERT INTO captures(id,capture_key,parent_relative,stem,pairing_status) VALUES (1,'a','','a','jpeg_only')"
            )
            connection.execute(
                """INSERT INTO ai_runs(
                       id,mode,model_id,prompt_version,status,requested_count,
                       completed_count,started_at
                   ) VALUES (1,'benchmark','model','v1','complete',1,1,'now')"""
            )
            connection.execute(
                """INSERT INTO ai_analyses(
                       id,run_id,capture_id,model_id,prompt_version,status,
                       selection_reason,result_json,audit_flags_json,audit_bits
                   ) VALUES (1,1,1,'model','v1','complete','test','{}','[\"低置信度\"]',512)"""
            )
            connection.commit()
            self.assertEqual(work_queue_summary(connection)["ai"]["open_count"], 1)
            save_work_item_state(connection, "ai", 1, "ignored")
            self.assertEqual(work_queue_summary(connection)["ai"]["open_count"], 0)
            connection.close()


if __name__ == "__main__":
    unittest.main()
