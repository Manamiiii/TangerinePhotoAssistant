import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from tangerine_photo_assistant.large_library_benchmark import generate_synthetic_catalog
from tangerine_photo_assistant.queries.selection import query_selected_captures
from tangerine_photo_assistant.settings import write_safe_config
from tangerine_photo_assistant.webapp import create_app


class SelectionTests(unittest.TestCase):
    def test_selection_preserves_order_and_unavailable_entries_without_writing(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            generate_synthetic_catalog(database, 100)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE files SET present=0 WHERE id IN "
                                   "(SELECT file_id FROM capture_files WHERE capture_id=2)")
            before = database.read_bytes()
            rows = query_selected_captures(database, [50, 2, 9999, 50])["items"]
            self.assertEqual([row["id"] for row in rows], [50, 2, 9999])
            self.assertTrue(rows[0]["stem"])
            self.assertIn("album_name", rows[0])
            self.assertEqual(rows[1]["jpeg_present"], 0)
            self.assertEqual(rows[2], {"id": 9999, "missing": True})
            self.assertEqual(database.read_bytes(), before)

    def test_selection_endpoint_validates_scope_and_supports_empty_catalog(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            originals = root / "originals"
            originals.mkdir()
            config = root / "config.toml"
            write_safe_config(config, originals, root / "workspace", root / "cache")
            with TestClient(create_app(config), base_url="http://localhost") as client:
                for params in [[], [("ids", "0")], [("ids", "bad")], [("ids", "1")] * 501]:
                    self.assertEqual(client.get("/api/library/selection", params=params).status_code, 422)
                response = client.get("/api/library/selection", params=[("ids", 5), ("ids", 1)])
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["items"], [
                    {"id": 5, "missing": True}, {"id": 1, "missing": True},
                ])
