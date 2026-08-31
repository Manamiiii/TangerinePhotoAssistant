import sqlite3
import tracemalloc
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tangerine_photo_assistant.database import connect_readonly
from tangerine_photo_assistant.large_library_benchmark import (
    SCENARIOS,
    _scenario_context,
    benchmark_existing_catalog,
    benchmark_scenario,
    generate_synthetic_catalog,
    run_benchmark_suite,
)


class LargeLibraryBenchmarkTests(unittest.TestCase):
    def test_context_uses_largest_visible_album_and_existing_model_problem(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            generate_synthetic_catalog(database, 200)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE event_captures SET event_id=2 WHERE event_id=1")
                connection.execute("UPDATE files SET present=0 WHERE id=199")
                connection.execute(
                    "UPDATE ai_analyses SET result_json=replace(result_json, '噪点', '现存问题')"
                )
            context = _scenario_context(database)
            self.assertEqual(context["visible_capture_count"], 199)
            self.assertEqual(context["album_id"], 2)
            self.assertEqual(context["album_capture_count"], 80)
            self.assertEqual(context["model_problem"], "现存问题")
            measured = benchmark_scenario(database, "model-problem-filter", iterations=1)
            self.assertGreater(measured["result_count"], 0)

    def test_missing_scenario_data_is_skipped_not_measured_as_fast_empty_query(self) -> None:
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            generate_synthetic_catalog(database, 100)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE files SET present=0")
            for name in ("collapsed-large-album", "model-problem-filter"):
                result = benchmark_scenario(database, name, iterations=1)
                self.assertEqual(result["status"], "skipped")
                self.assertIsNone(result["p95_ms"])

    def test_timed_passes_exclude_allocation_and_sql_tracing(self) -> None:
        calls = []

        def scenario(database, name, trace=None, context=None):
            def run():
                calls.append((tracemalloc.is_tracing(), trace is not None))
                return {"count": 4}
            return run

        module = "tangerine_photo_assistant.large_library_benchmark"
        with patch(f"{module}._scenario_context", return_value={}), \
                patch(f"{module}._scenario", side_effect=scenario), \
                patch(f"{module}._query_plans", return_value=[]):
            result = benchmark_scenario(Path("unused"), "library-first-page", iterations=3)
        self.assertEqual(calls, [(False, False)] * 4 + [(True, False), (False, True)])
        self.assertEqual(result["timing_instrumentation"], "none")
        self.assertFalse(tracemalloc.is_tracing())

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

    def test_existing_catalog_benchmark_is_read_only_and_non_overwriting(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "catalog.sqlite3"
            output = root / "formal-baseline.json"
            generate_synthetic_catalog(database, 200)
            before = database.stat().st_mtime_ns

            report = benchmark_existing_catalog(
                database, output, iterations=1,
                scenarios=("library-first-page",),
            )

            self.assertEqual(report["catalog"]["capture_count"], 200)
            self.assertEqual(report["source_photos_read"], 0)
            self.assertEqual(report["source_photos_written"], 0)
            self.assertEqual(database.stat().st_mtime_ns, before)
            self.assertTrue(output.is_file())
            with self.assertRaises(FileExistsError):
                benchmark_existing_catalog(
                    database, output, iterations=1,
                    scenarios=("library-first-page",),
                )

    def test_existing_catalog_benchmark_rejects_an_old_schema(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            database = root / "catalog.sqlite3"
            output = root / "formal-baseline.json"
            generate_synthetic_catalog(database, 100)
            connection = sqlite3.connect(database)
            try:
                connection.execute("UPDATE schema_info SET version=version-1")
                connection.commit()
            finally:
                connection.close()

            with self.assertRaisesRegex(RuntimeError, "expected"):
                benchmark_existing_catalog(
                    database, output, iterations=1,
                    scenarios=("library-first-page",),
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
