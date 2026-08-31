import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tangerine_photo_assistant.database import connect, connect_readonly
from tangerine_photo_assistant.large_library_benchmark import generate_synthetic_catalog
from tangerine_photo_assistant.statistics import CAPTURE_CTE, build_statistics


def independent_breakdowns(connection, queries):
    # Reference implementation: each unchanged chart query performs its own joins.
    return {
        name: [dict(row) for row in connection.execute(CAPTURE_CTE + query.sql)]
        for name, query in queries.items()
    }


class StatisticsSnapshotTests(unittest.TestCase):
    def assert_breakdowns_unchanged(self, database):
        with closing(connect_readonly(database)) as connection:
            before = connection.total_changes
            result = build_statistics(connection)
            with patch("tangerine_photo_assistant.statistics._capture_breakdowns",
                       side_effect=independent_breakdowns):
                expected = build_statistics(connection)
            self.assertEqual(result, expected)
            self.assertEqual(connection.total_changes, before)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM sqlite_temp_master")
                             .fetchone()[0], 0)
            self.assertEqual(connection.execute("PRAGMA query_only").fetchone()[0], 1)
            return result

    def test_shared_snapshot_preserves_every_chart_and_fresh_reads(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            generate_synthetic_catalog(database, 200)
            before = self.assert_breakdowns_unchanged(database)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE files SET present=0 WHERE id%7=0")
                connection.execute("UPDATE files SET iso=NULL, lens_model=NULL WHERE id%9=0")
                connection.execute("UPDATE captures SET captured_at=NULL WHERE id%11=0")
                connection.execute("UPDATE capture_reviews SET user_rating=1, user_pick=0")
                connection.execute("UPDATE quality_metrics SET technical_score=50 WHERE capture_id%3=0")
            after = self.assert_breakdowns_unchanged(database)
            self.assertNotEqual(before, after)

    def test_empty_catalog_keeps_empty_charts(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            connect(database).close()
            result = self.assert_breakdowns_unchanged(database)
            self.assertEqual(result["months"], [])
            self.assertEqual(result["cameras"], [])
            self.assertEqual(result["growth_subjects"], [])


if __name__ == "__main__":
    unittest.main()
