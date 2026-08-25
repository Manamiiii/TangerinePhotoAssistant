from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tangerine_photo_assistant.ai_analysis import (
    AUDIT_VISIBLE_PROBLEMS,
    ai_results_page,
    create_ai_run,
)
from tangerine_photo_assistant.ai_audit import (
    ai_audit_facets,
    create_fixed_benchmark,
    fixed_benchmark_summary,
    save_ai_version_review,
)
from tangerine_photo_assistant.database import connect


class AiAuditTests(unittest.TestCase):
    def test_fixed_stratified_benchmark_filters_coverage_and_gate(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            connection.executemany(
                """INSERT INTO events(
                       id,event_key,proposed_name,category,capture_count,status,
                       confidence,reason_json,created_at,updated_at
                   ) VALUES (?, ?, ?, ?, 6, 'confirmed', 1, '{}', 'now', 'now')""",
                [
                    (1, "album-1", "旅行", "风景"),
                    (2, "album-2", "城市", "建筑"),
                ],
            )
            subject_ids = {
                row["name"]: int(row["id"])
                for row in connection.execute(
                    """SELECT id,name FROM tag_definitions
                       WHERE dimension='subject' AND name IN ('风景','建筑')"""
                )
            }
            connection.execute(
                """INSERT INTO ai_runs(
                       id,mode,model_id,prompt_version,status,requested_count,
                       completed_count,started_at,finished_at
                   ) VALUES (1,'benchmark','model','audit-v1','complete',12,12,'now','now')"""
            )
            for capture_id in range(1, 13):
                album_id = 1 if capture_id <= 6 else 2
                subject_id = subject_ids["风景" if album_id == 1 else "建筑"]
                month = "2026-01" if capture_id % 2 else "2026-02"
                confidence = 0.4 if capture_id == 1 else 0.85
                bits = AUDIT_VISIBLE_PROBLEMS if capture_id == 2 else 0
                connection.execute(
                    """INSERT INTO captures(
                           id,capture_key,parent_relative,stem,pairing_status,captured_at
                       ) VALUES (?, ?, '', ?, 'jpeg_only', ?)""",
                    (
                        capture_id, f"capture:{capture_id}", f"PHOTO_{capture_id}",
                        f"{month}-01T10:00:00",
                    ),
                )
                connection.execute(
                    "INSERT INTO event_captures VALUES (?, ?, ?)",
                    (album_id, capture_id, capture_id),
                )
                connection.execute(
                    "INSERT INTO capture_tags VALUES (?, ?, 'analysis', 0.9, 'now')",
                    (capture_id, subject_id),
                )
                connection.execute(
                    """INSERT INTO ai_analyses(
                           id,run_id,capture_id,model_id,prompt_version,status,
                           selection_reason,result_json,user_verdict,reviewed_at,
                           audit_flags_json,audit_bits,audit_confidence,
                           audit_visible_problem_count
                       ) VALUES (?,1,?,'model','audit-v1','complete','test',?,
                                 'accurate','now','[]',?,?,?)""",
                    (
                        capture_id, capture_id,
                        json.dumps({
                            "overall_confidence": confidence,
                            "subject_type": "测试",
                            "quality_summary": "测试结果",
                            "visible_problems": ["问题"] if bits else [],
                        }, ensure_ascii=False),
                        bits, confidence, 1 if bits else 0,
                    ),
                )
            connection.commit()

            benchmark = create_fixed_benchmark(connection, 10)
            self.assertEqual(benchmark["capture_count"], 10)
            self.assertEqual(benchmark["added_count"], 10)
            self.assertEqual(benchmark["coverage"]["album"], 2)
            self.assertEqual(create_fixed_benchmark(connection, 10)["added_count"], 0)
            gate = fixed_benchmark_summary(connection)["versions"][0]
            self.assertTrue(gate["eligible_for_expansion"])
            self.assertEqual(gate["analysis_coverage"], 100.0)
            with patch(
                "tangerine_photo_assistant.ai_analysis.PROMPT_VERSION", "audit-v1"
            ), self.assertRaisesRegex(ValueError, "质量门禁"):
                create_ai_run(connection, Path("model"), "recommended", 10)
            saved = save_ai_version_review(
                connection, "audit-v1", "approved", "基准复核通过"
            )
            self.assertEqual(saved["status"], "approved")

            self.assertEqual(
                ai_results_page(connection, audit="benchmark")["count"], 10
            )
            self.assertEqual(
                ai_results_page(connection, album_id=1)["count"], 6
            )
            self.assertEqual(
                ai_results_page(connection, subject="建筑")["count"], 6
            )
            self.assertEqual(
                ai_results_page(connection, month="2026-01")["count"], 6
            )
            self.assertEqual(
                ai_results_page(connection, confidence="low")["count"], 1
            )
            self.assertEqual(
                ai_results_page(connection, problem="visible")["count"], 1
            )
            facets = ai_audit_facets(connection)
            self.assertEqual(len(facets["albums"]), 2)
            self.assertEqual(len(facets["subjects"]), 2)
            self.assertEqual(len(facets["months"]), 2)
            connection.close()


if __name__ == "__main__":
    unittest.main()
