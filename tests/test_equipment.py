import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.equipment import (
    build_equipment_catalog,
    delete_equipment_item,
    save_equipment_item,
    save_equipment_ownership,
)


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

    def test_catalog_and_workspace_inventory_are_combined(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root / "catalog.sqlite3")
            try:
                profile = root / "profile.toml"
                profile.write_text(
                    'schema_version = 1\n[[lenses]]\nbrand = "Fujifilm"\nmodel = "XF23mmF2 R WR"\n',
                    encoding="utf-8",
                )
                official = root / "official.toml"
                official.write_text(
                    'schema_version = 1\nname = "test"\n[[lenses]]\nbrand = "Fujifilm"\nmodel = "XF23mmF2 R WR"\n[[lenses]]\nbrand = "Fujifilm"\nmodel = "XF35mmF2 R WR"\n',
                    encoding="utf-8",
                )
                inventory = root / "Equipment" / "inventory.json"

                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertEqual(catalog["summary"]["lens_count"], 1)
                self.assertEqual(catalog["summary"]["catalog_lens_count"], 2)
                self.assertFalse(catalog["lenses"][1]["owned"])

                save_equipment_ownership(inventory, "lens", "XF35mmF2 R WR", True)
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertEqual(catalog["summary"]["lens_count"], 2)
                self.assertTrue(catalog["lenses"][1]["owned"])

                save_equipment_ownership(inventory, "lens", "XF23mmF2 R WR", False)
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertFalse(catalog["lenses"][0]["owned"])
                self.assertEqual(catalog["summary"]["lens_count"], 1)

                custom_key = save_equipment_item(
                    inventory,
                    "camera",
                    {"brand": "Test", "model": "C-1", "display_name": "测试机身", "owned": True},
                )
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                custom_camera = next(item for item in catalog["cameras"] if item["inventory_key"] == custom_key)
                self.assertEqual(custom_camera["display_name"], "测试机身")

                save_equipment_item(
                    inventory,
                    "camera",
                    {"brand": "Test", "model": "C-2", "display_name": "改名机身", "notes": "备用", "owned": False},
                    custom_key,
                )
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                custom_camera = next(item for item in catalog["cameras"] if item["inventory_key"] == custom_key)
                self.assertEqual(custom_camera["model"], "C-2")
                self.assertEqual(custom_camera["notes"], "备用")
                self.assertFalse(custom_camera["owned"])

                delete_equipment_item(inventory, "camera", custom_key)
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertNotIn(custom_key, {item["inventory_key"] for item in catalog["cameras"]})
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
