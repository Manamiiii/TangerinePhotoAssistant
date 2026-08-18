from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from tangerine_photo_assistant import ai_worker


class PersistentLogPrivacyTests(unittest.TestCase):
    def test_ai_worker_stderr_only_emits_exception_category(self) -> None:
        secret = r"D:\Private\SECRET-PHOTO.JPG GPS=31.123 serial=SECRET-SERIAL"
        output = io.StringIO()
        with patch.object(sys, "argv", ["ai-worker", "--config", "config.toml", "--run-id", "7"]), patch.object(
            ai_worker, "run_worker", side_effect=RuntimeError(secret)
        ), redirect_stderr(output):
            self.assertEqual(ai_worker.main(), 1)
        self.assertEqual(output.getvalue(), "ERROR: RuntimeError\n")
        self.assertNotIn("SECRET", output.getvalue())

    def test_controller_logs_do_not_interpolate_raw_errors_or_process_commands(self) -> None:
        root = Path(__file__).resolve().parents[1]
        sources = [
            root / "scripts" / "post_quality_benchmark_controller.py",
            root / "scripts" / "migration_batch_controller.py",
            root / "scripts" / "ai_deadline_guard.py",
        ]
        combined = "\n".join(path.read_text(encoding="utf-8") for path in sources)
        self.assertNotIn("{exc}", combined)
        self.assertNotIn("task.get('error')", combined)
        self.assertNotIn('" | ".join(comfy)', combined)


if __name__ == "__main__":
    unittest.main()
