from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.task_incidents import (
    record_task_incident,
    resolve_task_incident,
    save_task_incident_state,
    task_incident_summary,
    task_incidents_page,
)
from tangerine_photo_assistant.webapp import ScanTaskManager


def _settings(root: Path) -> Settings:
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


class TaskIncidentTests(unittest.TestCase):
    def test_failures_converge_reappear_and_resolve(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            record_task_incident(connection, "quality", "OSError", "技术质量分析失败")
            record_task_incident(connection, "quality", "OSError", "技术质量分析失败")
            page = task_incidents_page(connection)
            self.assertEqual(page["count"], 1)
            self.assertEqual(page["items"][0]["workflow_status"], "new")
            self.assertEqual(page["items"][0]["occurrence_count"], 1)

            save_task_incident_state(connection, "quality", "confirmed")
            self.assertEqual(task_incident_summary(connection)["open_count"], 0)
            record_task_incident(connection, "quality", "OSError", "技术质量分析失败")
            item = task_incidents_page(connection, "reappeared")["items"][0]
            self.assertEqual(item["occurrence_count"], 2)
            self.assertEqual(item["workflow_status"], "reappeared")

            self.assertTrue(resolve_task_incident(connection, "quality"))
            self.assertEqual(task_incident_summary(connection)["open_count"], 0)
            self.assertEqual(task_incidents_page(connection, "resolved")["count"], 1)
            connection.close()

    def test_manager_persists_only_safe_error_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = ScanTaskManager(_settings(root))
            manager._state.status = "running"
            manager._state.stage = "indexing"
            manager._update(
                status="failed", stage="failed", message="扫描失败",
                error="cannot read D:/private/photo.jpg",
            )
            self.assertEqual(manager.snapshot()["error"], "TaskFailure")
            manager._flush_task_outcomes()
            connection = connect(manager.settings.database_path)
            row = connection.execute(
                "SELECT * FROM task_incidents WHERE task_kind='scan'"
            ).fetchone()
            self.assertIsNotNone(row)
            assert row is not None
            self.assertEqual(row["error_code"], "TaskFailure")
            self.assertNotIn("private", row["message"])

            manager._state.status = "running"
            manager._state.stage = "metadata"
            manager._update(status="complete", stage="complete", message="扫描完成")
            manager._flush_task_outcomes()
            status = connection.execute(
                "SELECT status FROM task_incidents WHERE task_kind='scan'"
            ).fetchone()[0]
            self.assertEqual(status, "resolved")
            connection.close()


if __name__ == "__main__":
    unittest.main()
