from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
from dataclasses import replace
import hashlib
import time
import unittest
from unittest.mock import patch

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.archive import (
    create_archive_baseline,
    recorded_active_library_status,
    recorded_archive_status,
)
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.migration import (
    audit_migration_run,
    create_migration_plan,
    execute_migration_run,
    migration_preflight,
    prepare_migration_run,
    switch_active_library,
)
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.structure import rebuild_structure


def settings_for(root: Path) -> Settings:
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


class MigrationPlanTests(unittest.TestCase):
    def create_single_file_plan(self, root: Path, payload: bytes = b"photo-data"):
        settings = settings_for(root)
        source = settings.originals / "待整理" / "DSCF0001.JPG"
        source.parent.mkdir(parents=True)
        source.write_bytes(payload)
        connection = connect(settings.database_path)
        scan_library(connection, settings)
        rebuild_captures(connection)
        result = create_migration_plan(
            connection, settings.originals, settings.workspace / "Photos",
            settings.reports_path,
        )
        return settings, connection, source, result["plan"]

    def test_plan_is_read_only_and_excludes_reference_material(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            event = settings.originals / "MyPhoto" / "风光" / "2026.8.6_测试"
            event.mkdir(parents=True)
            (event / "DSCF0001.JPG").write_bytes(b"jpeg")
            (event / "DSCF0001.RAF").write_bytes(b"raw")
            (event / "clip.mp4").write_bytes(b"video")
            material = settings.originals / "素材"
            material.mkdir()
            (material / "reference.jpg").write_bytes(b"reference")

            connection = connect(settings.database_path)
            scan_library(connection, settings)
            connection.execute(
                "UPDATE files SET captured_at='2026-08-06T10:00:00' "
                "WHERE stem='DSCF0001'"
            )
            connection.commit()
            rebuild_captures(connection)
            rebuild_structure(connection, settings.burst_time_gap_seconds)
            before = {
                path.relative_to(settings.originals): path.read_bytes()
                for path in settings.originals.rglob("*") if path.is_file()
            }
            result = create_migration_plan(
                connection, settings.originals, settings.workspace / "Photos",
                settings.reports_path,
            )
            plan = result["plan"]
            self.assertEqual(plan["item_count"], 3)
            self.assertEqual(plan["excluded_count"], 1)
            self.assertEqual(plan["unassigned_count"], 1)
            self.assertFalse((settings.workspace / "Photos").exists())
            self.assertTrue((settings.reports_path / plan["csv_name"]).is_file())
            self.assertEqual(before, {
                path.relative_to(settings.originals): path.read_bytes()
                for path in settings.originals.rglob("*") if path.is_file()
            })
            connection.close()

    def test_safe_copy_hash_audit_and_switch_keep_stable_ids(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings, connection, source, plan = self.create_single_file_plan(root)
            capture_id = connection.execute("SELECT id FROM captures").fetchone()[0]
            file_id = connection.execute("SELECT id FROM files").fetchone()[0]
            connection.execute(
                """INSERT INTO capture_reviews(
                       capture_id, user_rating, user_pick, user_reject, updated_at
                   ) VALUES (?, 5, 1, 0, 'now')""",
                (capture_id,),
            )
            connection.commit()
            rebuild_captures(connection)
            self.assertEqual(connection.execute("SELECT id FROM captures").fetchone()[0], capture_id)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM capture_reviews WHERE capture_id=?", (capture_id,)
                ).fetchone()[0],
                1,
            )
            prepared = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}"
            )
            result = execute_migration_run(connection, prepared["run_id"])
            self.assertEqual(result["status"], "audited")
            item = connection.execute(
                "SELECT * FROM migration_items WHERE run_id=?", (prepared["run_id"],)
            ).fetchone()
            target = settings.workspace / "Photos" / Path(item["target_relative"])
            self.assertEqual(target.read_bytes(), source.read_bytes())
            self.assertEqual(item["source_sha256"], hashlib.sha256(source.read_bytes()).hexdigest())
            self.assertFalse(any(target.parent.glob("*.tangerine-part-*")))

            switched = switch_active_library(
                connection, prepared["run_id"],
                f"SWITCH TO ACTIVE LIBRARY PLAN {plan['id']}",
            )
            self.assertEqual(switched["status"], "switched")
            self.assertEqual(connection.execute("SELECT id FROM files").fetchone()[0], file_id)
            self.assertEqual(connection.execute("SELECT id FROM captures").fetchone()[0], capture_id)
            self.assertEqual(
                connection.execute(
                    "SELECT user_rating FROM capture_reviews WHERE capture_id=?", (capture_id,)
                ).fetchone()[0],
                5,
            )
            connection.close()

    def test_switch_excludes_archive_only_material_from_active_index(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            active_source = settings.originals / "待整理" / "DSCF0001.JPG"
            active_source.parent.mkdir(parents=True)
            active_source.write_bytes(b"active")
            material = settings.originals / "素材" / "reference.JPG"
            material.parent.mkdir()
            material.write_bytes(b"archive-only")
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            create_archive_baseline(connection, "original-before-switch")
            plan = create_migration_plan(
                connection, settings.originals, settings.workspace / "Photos",
                settings.reports_path,
            )["plan"]
            run_id = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}"
            )["run_id"]
            self.assertEqual(execute_migration_run(connection, run_id)["status"], "audited")
            switch_active_library(
                connection, run_id, f"SWITCH TO ACTIVE LIBRARY PLAN {plan['id']}"
            )
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM files WHERE present=1").fetchone()[0],
                1,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT present FROM files WHERE file_name='reference.JPG'"
                ).fetchone()[0],
                0,
            )
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM captures").fetchone()[0], 1)
            active_settings = replace(
                settings, originals=settings.workspace / "Photos"
            )
            scan_library(connection, active_settings)
            active = create_archive_baseline(
                connection, "active-after-switch", scope="active"
            )
            self.assertEqual(active["file_count"], 1)
            self.assertTrue(recorded_active_library_status(connection)["comparison"]["healthy"])
            self.assertTrue(recorded_archive_status(connection)["comparison"]["healthy"])
            with self.assertRaises(ValueError):
                create_archive_baseline(connection, "archive-after-switch")
            connection.close()

    def test_pause_cancel_and_resume_from_partial_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"0123456789abcdef" * (1024 * 1024)
            settings, connection, _, plan = self.create_single_file_plan(root, payload)
            run_id = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}"
            )["run_id"]
            pause = Event()
            copied = Event()
            outcome: dict[str, object] = {}

            def progress(values):
                if values.get("status") == "running" and not copied.is_set():
                    copied.set()
                    pause.set()

            def worker():
                worker_connection = connect(settings.database_path)
                try:
                    outcome.update(execute_migration_run(
                        worker_connection, run_id,
                        pause_requested=pause.is_set, progress=progress,
                    ))
                finally:
                    worker_connection.close()

            thread = Thread(target=worker)
            thread.start()
            self.assertTrue(copied.wait(5))
            deadline = time.time() + 5
            while time.time() < deadline:
                status = connection.execute(
                    "SELECT status FROM migration_runs WHERE id=?", (run_id,)
                ).fetchone()[0]
                if status == "paused":
                    break
                time.sleep(0.02)
            self.assertEqual(status, "paused")
            pause.clear()
            thread.join(15)
            self.assertFalse(thread.is_alive())
            self.assertEqual(outcome["status"], "audited")
            connection.close()

    def test_automatic_batches_persist_across_reopen(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings = settings_for(root)
            folder = settings.originals / "待整理"
            folder.mkdir(parents=True)
            for index in range(3):
                (folder / f"DSCF{index:04d}.JPG").write_bytes(f"photo-{index}".encode())
            connection = connect(settings.database_path)
            scan_library(connection, settings)
            rebuild_captures(connection)
            plan = create_migration_plan(
                connection, settings.originals, settings.workspace / "Photos",
                settings.reports_path,
            )["plan"]
            run_id = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}",
                batch_max_files=1, batch_max_bytes=1024**3, batch_max_seconds=3600,
            )["run_id"]

            first = execute_migration_run(connection, run_id)
            self.assertEqual(first["status"], "paused")
            self.assertEqual(first["batch_files"], 1)
            self.assertEqual(first["verified"], 1)
            connection.close()

            connection = connect(settings.database_path)
            second = execute_migration_run(connection, run_id)
            self.assertEqual(second["status"], "paused")
            self.assertEqual(second["verified"], 2)
            connection.close()

            connection = connect(settings.database_path)
            final = execute_migration_run(connection, run_id)
            self.assertEqual(final["status"], "audited")
            run = connection.execute(
                "SELECT completed_batches FROM migration_runs WHERE id=?", (run_id,)
            ).fetchone()
            self.assertEqual(run["completed_batches"], 2)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM migration_items WHERE run_id=? AND status='audited'",
                    (run_id,),
                ).fetchone()[0],
                3,
            )
            connection.close()

    def test_cancel_and_resume_from_partial_file(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            payload = b"cancel-resume" * (1024 * 1024)
            settings, connection, _, plan = self.create_single_file_plan(root, payload)
            run_id = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}"
            )["run_id"]
            cancel = Event()
            result = execute_migration_run(
                connection, run_id, cancel_requested=cancel.is_set,
                progress=lambda values: cancel.set() if values.get("status") == "running" else None,
            )
            self.assertEqual(result["status"], "cancelled")
            item = connection.execute(
                "SELECT copied_bytes, target_relative FROM migration_items WHERE run_id=?",
                (run_id,),
            ).fetchone()
            self.assertGreater(item["copied_bytes"], 0)
            resumed = execute_migration_run(connection, run_id)
            self.assertEqual(resumed["status"], "audited")
            connection.close()

    def test_conflict_source_change_and_hash_failure_are_safe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings, connection, source, plan = self.create_single_file_plan(root)
            item = connection.execute(
                "SELECT * FROM migration_items WHERE plan_id=?", (plan["id"],)
            ).fetchone()
            target = settings.workspace / "Photos" / Path(item["target_relative"])
            target.parent.mkdir(parents=True)
            target.write_bytes(b"existing")
            preflight = migration_preflight(connection, plan["id"])
            self.assertEqual(preflight["conflict_count"], 1)
            with self.assertRaises(ValueError):
                prepare_migration_run(connection, plan["id"], f"COPY PLAN {plan['id']}")
            self.assertEqual(target.read_bytes(), b"existing")
            connection.close()

    def test_full_audit_detects_target_corruption(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings, connection, _, plan = self.create_single_file_plan(root)
            run_id = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}"
            )["run_id"]
            copied = execute_migration_run(connection, run_id, auto_audit=False)
            self.assertEqual(copied["status"], "copied")
            item = connection.execute(
                "SELECT * FROM migration_items WHERE run_id=?", (run_id,)
            ).fetchone()
            target = settings.workspace / "Photos" / Path(item["target_relative"])
            target.write_bytes(b"corrupt")
            audited = audit_migration_run(connection, run_id)
            self.assertEqual(audited["status"], "audit_failed")
            self.assertEqual(audited["audit_failed"], 1)
            connection.close()

    def test_source_change_and_hash_failure_are_safe(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings, connection, source, plan = self.create_single_file_plan(root)
            source.write_bytes(b"changed-after-plan")
            preflight = migration_preflight(connection, plan["id"])
            self.assertEqual(preflight["changed_count"], 1)
            self.assertFalse((settings.workspace / "Photos").exists())
            connection.close()

        with TemporaryDirectory() as directory:
            root = Path(directory)
            settings, connection, source, plan = self.create_single_file_plan(root)
            run_id = prepare_migration_run(
                connection, plan["id"], f"COPY PLAN {plan['id']}"
            )["run_id"]
            real_hash = hashlib.sha256(source.read_bytes()).hexdigest()
            with patch(
                "tangerine_photo_assistant.migration._digest",
                side_effect=[real_hash, "0" * 64],
            ):
                result = execute_migration_run(connection, run_id)
            self.assertEqual(result["status"], "failed")
            item = connection.execute(
                "SELECT * FROM migration_items WHERE run_id=?", (run_id,)
            ).fetchone()
            target = settings.workspace / "Photos" / Path(item["target_relative"])
            self.assertFalse(target.exists())
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM migration_failures WHERE run_id=?", (run_id,)
                ).fetchone()[0],
                1,
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
