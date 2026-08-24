import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.database import connect_readonly
from tangerine_photo_assistant.large_library_benchmark import (
    SCENARIOS,
    benchmark_scenario,
    generate_synthetic_catalog,
    run_benchmark_suite,
)


class LargeLibraryBenchmarkTests(unittest.TestCase):
    def test_metadata_only_catalog_exercises_all_scenarios(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "synthetic.sqlite3"
            generated = generate_synthetic_catalog(database, 200)

            self.assertEqual(generated["integrity_check"], "ok")
            self.assertEqual(generated["capture_count"], 200)
            self.assertEqual(generated["photos_created"], 0)
            self.assertTrue(database.with_suffix(".meta.json").is_file())
            self.assertFalse(any(root.rglob("*.jpg")))
            connection = connect_readonly(database)
            try:
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM files").fetchone()[0],
                    200,
                )
                self.assertEqual(
                    connection.execute("SELECT COUNT(*) FROM ai_analyses").fetchone()[0],
                    40,
                )
            finally:
                connection.close()

            for scenario in SCENARIOS:
                measured = benchmark_scenario(database, scenario, iterations=1)
                self.assertEqual(measured["scenario"], scenario)
                self.assertGreaterEqual(measured["p50_ms"], 0)
                self.assertGreater(measured["python_peak_bytes"], 0)
                self.assertTrue(measured["query_plans"])

    def test_generator_refuses_to_replace_an_existing_database(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "synthetic.sqlite3"
            generate_synthetic_catalog(database, 100)
            with self.assertRaises(FileExistsError):
                generate_synthetic_catalog(database, 100)

    def test_suite_refuses_a_nonempty_unmarked_workspace(self) -> None:
        with TemporaryDirectory() as temporary:
            workspace = Path(temporary)
            (workspace / "existing.txt").write_text("user data", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                run_benchmark_suite(workspace, [100], iterations=1)


if __name__ == "__main__":
    unittest.main()
