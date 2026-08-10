from pathlib import Path
import sqlite3
import tempfile
import unittest

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.equipment import build_equipment_catalog


class EquipmentCatalogTests(unittest.TestCase):
    def test_profile_and_capture_usage_are_combined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root / "catalog.sqlite3")
            try:
                connection.execute(
                    "INSERT INTO scan_runs (root_path, started_at, status) VALUES (?, '2026-01-01', 'complete')",
                    (str(root),),
                )
                run_id = connection.execute("SELECT id FROM scan_runs").fetchone()["id"]
                connection.execute(
                    """INSERT INTO files
                       (path, relative_path, parent_relative, file_name, stem,
                        extension, size_bytes, modified_ns, media_kind,
                        first_seen_run_id, last_seen_run_id, present,
                        camera_model, lens_model)
                       VALUES (?, 'A.JPG', '', 'A.JPG', 'A', '.jpg', 1, 1,
                               'image', ?, ?, 1, 'X-S20',
                               'XF23mmF1.4 R LM WR')""",
                    (str(root / "A.JPG"), run_id, run_id),
                )
                file_id = connection.execute("SELECT id FROM files").fetchone()["id"]
                connection.execute(
                    "INSERT INTO captures (capture_key, stem, parent_relative, pairing_status) VALUES ('A', 'A', '', 'jpeg_only')"
                )
                capture_id = connection.execute("SELECT id FROM captures").fetchone()["id"]
                connection.execute(
                    "INSERT INTO capture_files (capture_id, file_id, role) VALUES (?, ?, 'jpeg')",
                    (capture_id, file_id),
                )
                connection.commit()
                profile = root / "profile.toml"
                profile.write_text(
                    """schema_version = 1
[camera]
brand = "Fujifilm"
model = "X-S20"
display_name = "富士 X-S20"
[[lenses]]
brand = "Fujifilm"
model = "XF23mmF1.4 R LM WR"
filter_thread_mm = 58
[[filters]]
brand = "Kase"
model = "ND64"
kind = "neutral_density"
""",
                    encoding="utf-8",
                )

                catalog = build_equipment_catalog(connection, profile)

                self.assertEqual(catalog["summary"]["camera_count"], 1)
                self.assertEqual(catalog["summary"]["lens_count"], 1)
                self.assertEqual(catalog["summary"]["accessory_count"], 1)
                self.assertEqual(catalog["cameras"][0]["capture_count"], 1)
                self.assertEqual(catalog["lenses"][0]["capture_count"], 1)
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
