import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from tangerine_photo_assistant.ai_safety import (
    ai_preflight,
    create_pre_ai_database_backup,
    discover_pre_ai_database_backups,
    gpu_status,
)
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.settings import Settings


def settings_for(root: Path) -> Settings:
    originals = root / "originals"
    originals.mkdir()
    model = root / "model"
    model.mkdir()
    (model / "config.json").write_text("{}", encoding="utf-8")
    (model / "model.safetensors").write_bytes(b"weights")
    python = root / "python.exe"
    python.write_bytes(b"")
    workspace = root / "workspace"
    (workspace / "Backups").mkdir(parents=True)
    return Settings(
        originals=originals,
        workspace=workspace,
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
        ai_model_path=model,
        ai_python=python,
        ai_quantization="int8",
    )


class AiSafetyTests(unittest.TestCase):
    @patch("tangerine_photo_assistant.ai_safety.subprocess.run")
    def test_gpu_status_parses_nvidia_smi(self, run: Mock) -> None:
        run.return_value = Mock(
            returncode=0,
            stdout="NVIDIA GeForce RTX 5080, 72, 15000, 16303, 46\n",
        )
        status = gpu_status()
        self.assertTrue(status["available"])
        self.assertEqual(status["memory_used_mb"], 15000)
        self.assertEqual(status["utilization_percent"], 72)
        self.assertEqual(run.call_args.kwargs["encoding"], "utf-8")
        self.assertEqual(run.call_args.kwargs["errors"], "replace")

    def test_preflight_detects_complete_and_incomplete_models(self) -> None:
        with TemporaryDirectory() as directory:
            settings = settings_for(Path(directory))
            connection = connect(settings.database_path)
            connection.close()
            result = ai_preflight(settings, check_competing_processes=False)
            self.assertTrue(result["ready"])
            incomplete = settings.ai_model_path / "download.incomplete"  # type: ignore[operator]
            incomplete.write_bytes(b"")
            result = ai_preflight(settings, check_competing_processes=False)
            self.assertFalse(result["ready"])
            self.assertEqual(result["incomplete_files"], ["download.incomplete"])

    def test_database_backup_is_complete_and_independent(self) -> None:
        with TemporaryDirectory() as directory:
            settings = settings_for(Path(directory))
            connection = connect(settings.database_path)
            connection.execute(
                "INSERT INTO schema_info(version) SELECT 10 WHERE NOT EXISTS "
                "(SELECT 1 FROM schema_info)"
            )
            connection.commit()
            connection.close()
            backup = create_pre_ai_database_backup(settings, 7)
            self.assertTrue(backup.is_file())
            copied = sqlite3.connect(backup)
            try:
                self.assertEqual(copied.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                copied.close()
            connection = connect(settings.database_path)
            connection.execute(
                """
                INSERT INTO ai_runs(
                    id, mode, model_id, prompt_version, status,
                    requested_count, started_at
                ) VALUES (7, 'benchmark', 'test', 'test', 'complete', 1, ?)
                """,
                ("2026-08-10T00:00:00+00:00",),
            )
            connection.commit()
            self.assertEqual(discover_pre_ai_database_backups(settings, connection), 1)
            self.assertEqual(discover_pre_ai_database_backups(settings, connection), 0)
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM ai_run_backups WHERE run_id=7"
                ).fetchone()[0],
                1,
            )
            connection.close()


if __name__ == "__main__":
    unittest.main()
