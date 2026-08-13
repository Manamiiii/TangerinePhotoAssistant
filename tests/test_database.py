import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.database import SCHEMA_VERSION, connect


class DatabaseUpgradeTests(unittest.TestCase):
    def test_upgrade_creates_verified_backup_before_mutating_catalog(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "catalog.sqlite3"
            connection = connect(database)
            connection.execute("CREATE TABLE upgrade_marker(value TEXT)")
            connection.execute("INSERT INTO upgrade_marker VALUES ('before-upgrade')")
            connection.execute("DROP TABLE similarity_group_revision_captures")
            connection.execute("DROP TABLE similarity_group_revisions")
            previous_version = SCHEMA_VERSION - 1
            connection.execute("UPDATE schema_info SET version=?", (previous_version,))
            connection.commit()
            connection.close()

            upgraded = connect(database)
            self.assertEqual(
                upgraded.execute("SELECT version FROM schema_info").fetchone()[0],
                SCHEMA_VERSION,
            )
            plan = upgraded.execute(
                """EXPLAIN QUERY PLAN
                   SELECT capture_id FROM similarity_group_overrides
                   WHERE manual_batch_key='manual:test'"""
            ).fetchall()
            self.assertTrue(
                any("idx_similarity_group_overrides_batch" in row[3] for row in plan)
            )
            self.assertIsNotNone(
                upgraded.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='similarity_group_revisions'"
                ).fetchone()
            )
            upgraded.close()

            backups = list((database.parent / "SchemaBackups").glob("*.sqlite3"))
            self.assertEqual(len(backups), 1)
            backup = sqlite3.connect(backups[0])
            self.assertEqual(backup.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(
                backup.execute("SELECT version FROM schema_info").fetchone()[0],
                previous_version,
            )
            self.assertEqual(
                backup.execute("SELECT value FROM upgrade_marker").fetchone()[0],
                "before-upgrade",
            )
            backup.close()

    def test_future_schema_is_rejected_before_catalog_mutation(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "future.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE schema_info(version INTEGER NOT NULL)")
            connection.execute("INSERT INTO schema_info VALUES (?)", (SCHEMA_VERSION + 1,))
            connection.execute("CREATE TABLE future_only(value TEXT)")
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(RuntimeError, "Unsupported database schema"):
                connect(database)

            readonly = sqlite3.connect(database)
            tables = {
                row[0]
                for row in readonly.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            }
            readonly.close()
            self.assertEqual(tables, {"future_only", "schema_info"})

    def test_unversioned_existing_database_is_rejected(self) -> None:
        with TemporaryDirectory() as directory:
            database = Path(directory) / "unversioned.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute("CREATE TABLE unknown_data(value TEXT)")
            connection.commit()
            connection.close()

            with self.assertRaisesRegex(RuntimeError, "missing a readable schema_info"):
                connect(database)

            readonly = sqlite3.connect(database)
            tables = {
                row[0]
                for row in readonly.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
            }
            readonly.close()
            self.assertEqual(tables, {"unknown_data"})


if __name__ == "__main__":
    unittest.main()
