import subprocess
import sys
import time
import unittest
from pathlib import Path

from tangerine_photo_assistant.metadata import ExifToolMetadataReader


class MetadataTimeoutTests(unittest.TestCase):
    def test_unresponsive_tool_is_terminated_and_files_report_failure(self):
        with subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as process:
            reader = ExifToolMetadataReader(Path(sys.executable), timeout_seconds=0.2)
            start = time.monotonic()
            results = list(reader._read_batch(process, [Path("one.raw"), Path("two.raw")], 1))
            process.wait(timeout=3)
            self.assertLess(time.monotonic() - start, 5)
            self.assertEqual(len(results), 2)
            self.assertTrue(all(result.values is None and "timed out" in result.error for result in results))

    def test_completed_batch_cancels_deadline(self):
        script = 'import sys,time; print("[]\\n{ready1}", flush=True); time.sleep(30)'
        with subprocess.Popen(
            [sys.executable, "-c", script],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ) as process:
            try:
                reader = ExifToolMetadataReader(Path(sys.executable), timeout_seconds=0.3)
                list(reader._read_batch(process, [Path("one.raw")], 1))
                time.sleep(0.4)
                self.assertIsNone(process.poll())
            finally:
                process.kill()
                process.wait(timeout=3)


if __name__ == "__main__":
    unittest.main()
