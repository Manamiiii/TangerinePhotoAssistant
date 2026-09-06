from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
    def test_paused_task_rejects_new_tasks_and_unrelated_resumes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = ScanTaskManager(_settings(root))
            manager._state.status = "paused"
            manager._state.stage = "detail-metadata"
            manager._state.id = "preserved-task"
            manager._pause.set()
            before = manager.snapshot()
            actions = [
                lambda: manager.start(1), manager.start_visual, manager.start_quality,
                manager.start_detail_backfill,
                lambda: manager.start_ai("benchmark", 1, root / "config.toml"),
                lambda: manager.retry_ai_failures(7, root / "config.toml"),
                lambda: manager.resume_ai(7, root / "config.toml"),
                lambda: manager.start_migration(7, "unused", 1, 1, 1),
                lambda: manager.resume_migration(7),
            ]
            with (
                patch.object(Settings, "find_exiftool", return_value=root / "exiftool"),
                patch("tangerine_photo_assistant.webapp.ai_preflight",
                      return_value={"ready": True}),
                patch("tangerine_photo_assistant.webapp.Thread") as thread,
                patch("tangerine_photo_assistant.webapp.connect") as database,
            ):
                for action in actions:
                    with self.subTest(action=actions.index(action)):
                        with self.assertRaises(RuntimeError):
                            action()
                        self.assertEqual(manager.snapshot(), before)
                        self.assertTrue(manager._pause.is_set())
                thread.assert_not_called()
                database.assert_not_called()
            resumed = manager.resume_detail_backfill()
            self.assertEqual(resumed["id"], "preserved-task")
            self.assertEqual(resumed["status"], "running")
            self.assertFalse(manager._pause.is_set())

    def test_resume_requires_matching_paused_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = ScanTaskManager(_settings(root))
            manager._state.status = "paused"
            manager._state.stage = "migration-copy"
            manager._migration_run_id = 7
            manager._migration_thread_active = True
            manager._pause.set()
            with self.assertRaises(RuntimeError):
                manager.resume_migration(8)
            self.assertTrue(manager._pause.is_set())
            self.assertEqual(manager.resume_migration(7)["status"], "running")
            self.assertFalse(manager._pause.is_set())
            manager._state.status = "paused"
            manager._state.stage = "ai-paused"
            manager._ai_run_id = 7
            with (
                patch("tangerine_photo_assistant.webapp.ai_preflight",
                      return_value={"ready": True}),
                patch("tangerine_photo_assistant.webapp.Thread") as thread,
            ):
                with self.assertRaises(RuntimeError):
                    manager.resume_ai(8, root / "config.toml")
                thread.assert_not_called()
                self.assertEqual(manager.resume_ai(7, root / "config.toml")["status"],
                                 "running")
                thread.return_value.start.assert_called_once()

    def test_worker_connection_failure_always_finishes_task(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            settings = _settings(root)
            workers = [
                ("_run", ("task", 1)), ("_run_visual", ("task",)),
                ("_run_quality", ("task",)),
                ("_run_detail_backfill", ("task", root / "exiftool")),
                ("_run_migration", (7,)),
                ("_run_ai", ("task", "benchmark", 1, root / "config.toml", None)),
                ("_monitor_attached_ai", (7,)),
            ]
            for name, args in workers:
                for error in [PermissionError("private path"), sqlite3.OperationalError("locked")]:
                    with self.subTest(worker=name, error=type(error).__name__):
                        manager = ScanTaskManager(settings)
                        manager._state.status = "running"
                        manager._state.stage = "ai-preparing" if "ai" in name else "quality"
                        manager._state.pausable = True
                        manager._migration_thread_active = name == "_run_migration"
                        with patch("tangerine_photo_assistant.webapp.connect", side_effect=error):
                            getattr(manager, name)(*args)
                        result = manager.snapshot()
                        self.assertEqual(result["status"], "failed")
                        self.assertFalse(result["pausable"])
                        self.assertNotIn("private", str(result))
                        self.assertFalse(manager._migration_thread_active)
                        self.assertIsNone(manager._process)

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
