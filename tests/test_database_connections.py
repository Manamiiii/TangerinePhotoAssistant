import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tangerine_photo_assistant.database import connect


class DatabaseConnectionTests(unittest.TestCase):
    def test_current_schema_connection_does_not_run_schema_or_seed_writes(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'catalog.sqlite3'
            connect(database).close()
            statements = []
            original_connect = sqlite3.connect

            def traced(*args, **kwargs):
                connection = original_connect(*args, **kwargs)
                connection.set_trace_callback(statements.append)
                return connection

            with patch('tangerine_photo_assistant.database.sqlite3.connect', side_effect=traced):
                connection = connect(database)
                self.assertEqual(connection.execute('PRAGMA foreign_keys').fetchone()[0], 1)
                self.assertFalse(connection.in_transaction)
                connection.close()
            writes = ('CREATE ', 'ALTER ', 'INSERT ', 'UPDATE ', 'DELETE ')
            self.assertFalse(any(sql.lstrip().upper().startswith(writes) for sql in statements), statements)


if __name__ == '__main__':
    unittest.main()
