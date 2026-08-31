import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory

from tangerine_photo_assistant.large_library_benchmark import generate_synthetic_catalog
from tangerine_photo_assistant.queries.library import query_library_captures


class LibraryPaginationTests(unittest.TestCase):
    def test_page_hydration_preserves_order_filters_counts_and_fields(self):
        with TemporaryDirectory() as temporary:
            database = Path(temporary) / "catalog.sqlite3"
            generate_synthetic_catalog(database, 200)
            with closing(sqlite3.connect(database)) as connection, connection:
                connection.execute("UPDATE files SET present=0 WHERE id%17=0")
                connection.execute("UPDATE captures SET captured_at=NULL WHERE id%11=0")
            for sort in ("newest", "oldest", "name", "rating"):
                for filters in ({}, {"album_id": 1}, {"model_problem": "噪点"},
                                {"rating": 4}, {"quality": "low"},
                                {"search": "IMG_00000"}, {"selection": "picked"}):
                    with self.subTest(sort=sort, filters=filters):
                        whole = query_library_captures(database, 300, 0, sort=sort, **filters)
                        for offset in (0, 7, max(0, whole["count"]-4), whole["count"]+1):
                            page = query_library_captures(database, 7, offset, sort=sort, **filters)
                            self.assertEqual(page["count"], whole["count"])
                            self.assertEqual(page["items"], whole["items"][offset:offset+7])


if __name__ == "__main__":
    unittest.main()
