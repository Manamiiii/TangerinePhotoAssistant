import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.albums import (
    AlbumConflictError,
    AlbumError,
    assign_captures_to_album,
    create_album,
    create_album_type,
    delete_album_type,
    rename_album_type,
    update_album,
)
from tangerine_photo_assistant.database import connect


class AlbumServiceTests(unittest.TestCase):
    def test_album_crud_and_assignment_failures_are_atomic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            connection = connect(Path(temporary) / "catalog.sqlite3")
            built_in = connection.execute(
                "SELECT name FROM album_types WHERE built_in=1 ORDER BY sort_order LIMIT 1"
            ).fetchone()[0]
            create_album_type(connection, "测试类型")
            source = create_album(connection, "来源相册", "测试类型")
            target = create_album(connection, "目标相册", "测试类型")
            connection.executemany(
                """INSERT INTO captures(capture_key, stem, parent_relative, pairing_status)
                   VALUES (?, ?, '测试来源', 'jpeg_only')""",
                (("A", "A"), ("B", "B")),
            )
            capture_ids = [row[0] for row in connection.execute("SELECT id FROM captures")]
            connection.executemany(
                "INSERT INTO event_captures(event_id, capture_id, sequence_index) VALUES (?, ?, ?)",
                ((source["id"], capture_ids[0], 0), (source["id"], capture_ids[1], 1)),
            )
            connection.execute(
                "UPDATE events SET capture_count=2 WHERE id=?", (source["id"],)
            )
            connection.commit()

            with self.assertRaisesRegex(AlbumError, "不存在的照片"):
                assign_captures_to_album(
                    connection, int(target["id"]), [capture_ids[0], max(capture_ids) + 1000]
                )
            self.assertEqual(
                [row[0] for row in connection.execute(
                    "SELECT capture_id FROM event_captures WHERE event_id=? ORDER BY capture_id",
                    (source["id"],),
                )],
                capture_ids,
            )

            self.assertEqual(
                assign_captures_to_album(connection, int(target["id"]), capture_ids), 2
            )
            self.assertEqual(
                connection.execute(
                    "SELECT capture_count FROM events WHERE id=?", (target["id"],)
                ).fetchone()[0],
                2,
            )
            self.assertEqual(
                connection.execute(
                    "SELECT capture_count FROM events WHERE id=?", (source["id"],)
                ).fetchone()[0],
                0,
            )

            rename_album_type(connection, "测试类型", "整理类型")
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM events WHERE category='整理类型'"
                ).fetchone()[0],
                2,
            )
            with self.assertRaises(AlbumConflictError):
                delete_album_type(connection, "整理类型")
            with self.assertRaises(AlbumConflictError):
                rename_album_type(connection, built_in, "内置改名")
            with self.assertRaises(AlbumConflictError):
                create_album_type(connection, "整理类型")

            update_album(connection, int(source["id"]), "来源相册", built_in, "confirmed")
            update_album(connection, int(target["id"]), "目标相册", built_in, "confirmed")
            update_album(
                connection, int(target["id"]), "目标相册", built_in, "confirmed",
                ["filters:ND64", "supports:tripod"],
            )
            self.assertEqual(
                [row[0] for row in connection.execute(
                    "SELECT equipment_key FROM event_equipment WHERE event_id=? ORDER BY equipment_key",
                    (target["id"],),
                )],
                ["filters:ND64", "supports:tripod"],
            )
            update_album(connection, int(target["id"]), "保留附件", built_in, "confirmed")
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM event_equipment WHERE event_id=?", (target["id"],)
                ).fetchone()[0], 2,
            )
            update_album(connection, int(target["id"]), "清空附件", built_in, "confirmed", [])
            self.assertEqual(
                connection.execute(
                    "SELECT COUNT(*) FROM event_equipment WHERE event_id=?", (target["id"],)
                ).fetchone()[0], 0,
            )
            self.assertEqual(delete_album_type(connection, "整理类型")["status"], "deleted")
            connection.close()


if __name__ == "__main__":
    unittest.main()
