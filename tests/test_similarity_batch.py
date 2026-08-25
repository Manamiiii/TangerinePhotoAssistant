from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.queries.similarity import query_similarity_groups
from tangerine_photo_assistant.similarity_batch import (
    apply_low_risk_batch,
    list_audit_groups,
    list_review_batches,
    low_risk_preview,
    save_audit_result,
    undo_review_batch,
)


class SimilarityBatchTests(unittest.TestCase):
    def test_preview_apply_audit_and_safe_undo(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            database_path = Path(temporary) / "catalog.sqlite3"
            connection = connect(database_path)
            connection.execute(
                "INSERT INTO scan_runs(id,started_at,root_path,status) "
                "VALUES (1,'now','test','complete')"
            )
            connection.execute(
                """INSERT INTO events(
                       id,event_key,proposed_name,category,capture_count,status,
                       confidence,reason_json,created_at,updated_at)
                   VALUES (1,'album','测试相册','风景',4,'confirmed',1,'{}','now','now')"""
            )
            connection.execute(
                """INSERT INTO bursts(
                       id,event_id,burst_key,start_at,end_at,capture_count,
                       grouping_method)
                   VALUES (1,1,'burst','2026-01-01T10:00:00',
                           '2026-01-01T10:00:03',4,'time')"""
            )
            for capture_id in range(1, 5):
                connection.execute(
                    """INSERT INTO files(
                           id,path,relative_path,parent_relative,file_name,stem,
                           extension,media_kind,size_bytes,modified_ns,
                           first_seen_run_id,last_seen_run_id)
                       VALUES (?, ?, ?, '', ?, ?, '.jpg','jpeg',1,1,1,1)""",
                    (
                        capture_id, f"test/{capture_id}.jpg", f"{capture_id}.jpg",
                        f"{capture_id}.jpg", f"PHOTO_{capture_id}",
                    ),
                )
                connection.execute(
                    """INSERT INTO captures(
                           id,capture_key,parent_relative,stem,captured_at,pairing_status)
                       VALUES (?, ?, '', ?, '2026-01-01T10:00:00','jpeg_only')""",
                    (capture_id, f"capture:{capture_id}", f"PHOTO_{capture_id}"),
                )
                connection.execute(
                    "INSERT INTO burst_captures VALUES (1,?,?,?)",
                    (capture_id, capture_id - 1, capture_id * 100),
                )
                connection.execute(
                    """INSERT INTO quality_metrics(
                           capture_id,source_file_id,algorithm_version,technical_score,
                           issue_json,size_bytes,modified_ns,computed_at)
                       VALUES (?,?,'test',?,'[]',1,1,'now')""",
                    (capture_id, capture_id, 90 - capture_id * 5),
                )
                connection.execute(
                    """INSERT INTO capture_reviews(
                           capture_id,auto_pick,similarity_rank,user_reject,updated_at)
                       VALUES (?,?,?,?, 'now')""",
                    (capture_id, 1 if capture_id == 1 else 0, capture_id, 0),
                )
            connection.execute(
                """INSERT INTO similarity_groups(
                       id,burst_id,group_key,capture_count,max_adjacent_hamming)
                   VALUES (1,1,'group',4,6)"""
            )
            connection.executemany(
                "INSERT INTO similarity_group_captures VALUES (1,?,?,?)",
                [(capture_id, capture_id - 1, 4 if capture_id > 1 else None)
                 for capture_id in range(1, 5)],
            )
            connection.commit()

            groups = query_similarity_groups(
                database_path, 20, 0, "pending", confidence_filter="high"
            )
            self.assertEqual(groups["count"], 1)
            self.assertEqual(groups["confidence_counts"]["high"], 1)
            self.assertEqual(groups["items"][0]["confidence_level"], "high")
            preview = low_risk_preview(connection)
            self.assertEqual(preview["group_count"], 1)
            self.assertEqual(preview["audit_count"], 1)
            applied = apply_low_risk_batch(connection, [1], album_id=1)
            self.assertEqual(applied["group_count"], 1)
            self.assertEqual(
                connection.execute(
                    "SELECT user_pick FROM capture_reviews WHERE capture_id=1"
                ).fetchone()[0],
                1,
            )
            batch = list_review_batches(connection)["items"][0]
            self.assertTrue(batch["can_undo"])
            audit = list_audit_groups(connection)["items"][0]
            self.assertEqual(audit["group_id"], 1)
            save_audit_result(connection, applied["batch_id"], 1, "confirmed")
            self.assertEqual(
                list_audit_groups(connection)["items"][0]["audit_status"],
                "confirmed",
            )
            undone = undo_review_batch(connection, applied["batch_id"])
            self.assertEqual(undone["restored_count"], 1)
            self.assertIsNone(
                connection.execute(
                    "SELECT user_pick FROM capture_reviews WHERE capture_id=1"
                ).fetchone()[0]
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
