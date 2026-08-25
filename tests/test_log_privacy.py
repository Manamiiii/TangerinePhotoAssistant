from __future__ import annotations

import io
import sys
import unittest
from contextlib import redirect_stderr
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

if __name__ == "__main__":
    unittest.main()
