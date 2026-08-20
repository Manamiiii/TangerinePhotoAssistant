import tempfile
import unittest
from pathlib import Path

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.equipment import (
    build_equipment_catalog,
    delete_equipment_item,
    equipment_album_reference_count,
    save_equipment_item,
    save_equipment_ownership,
    set_equipment_visibility,
)


class EquipmentCatalogTests(unittest.TestCase):
    def test_empty_public_profile_does_not_seed_personal_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            connection = connect(root / "catalog.sqlite3")
            try:
                profile = root / "profile.toml"
                profile.write_text("schema_version = 1\n", encoding="utf-8")
                official = root / "official.toml"
                official.write_text(
                    'schema_version = 1\n[[lenses]]\nbrand = "Fujifilm"\nmodel = "XF35mmF2 R WR"\n',
                    encoding="utf-8",
                )
                catalog = build_equipment_catalog(connection, profile, official, root / "missing.json")
                self.assertEqual(catalog["summary"]["camera_count"], 0)
                self.assertEqual(catalog["summary"]["lens_count"], 0)
                self.assertEqual(catalog["summary"]["accessory_count"], 0)
                self.assertFalse(catalog["lenses"][0]["owned"])
            finally:
                connection.close()

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

                connection.execute(
                    """INSERT INTO events(
                           event_key, proposed_name, category, capture_count, status,
                           confidence, reason_json, created_at, updated_at
                       ) VALUES ('album:gear', '器材测试', '日常', 0, 'confirmed',
                                 1.0, '{}', '2026-01-01', '2026-01-01')"""
                )
                album_id = connection.execute(
                    "SELECT id FROM events WHERE event_key='album:gear'"
                ).fetchone()[0]
                connection.execute(
                    """INSERT INTO event_equipment(
                           event_id, equipment_kind, equipment_key, source, created_at
                       ) VALUES (?, 'accessory', 'filters:ND64', 'manual', '2026-01-01')""",
                    (album_id,),
                )
                connection.commit()

                catalog = build_equipment_catalog(connection, profile)

                self.assertEqual(catalog["summary"]["camera_count"], 1)
                self.assertEqual(catalog["summary"]["lens_count"], 1)
                self.assertEqual(catalog["summary"]["accessory_count"], 1)
                self.assertEqual(catalog["cameras"][0]["capture_count"], 1)
                self.assertEqual(catalog["lenses"][0]["capture_count"], 1)
                self.assertEqual(catalog["accessories"][0]["album_count"], 1)
                self.assertEqual(
                    equipment_album_reference_count(connection, "accessory", "filters:ND64"),
                    1,
                )
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
                    {"brand": "Test", "model": "C-2", "display_name": "改名机身", "notes": "备用", "image_path": str(root / "camera.png"), "owned": False},
                    custom_key,
                )
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                custom_camera = next(item for item in catalog["cameras"] if item["inventory_key"] == custom_key)
                self.assertEqual(custom_camera["model"], "C-2")
                self.assertEqual(custom_camera["notes"], "备用")
                self.assertEqual(custom_camera["image_path"], str(root / "camera.png"))
                self.assertFalse(custom_camera["owned"])

                delete_equipment_item(inventory, "camera", custom_key)
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertNotIn(custom_key, {item["inventory_key"] for item in catalog["cameras"]})

                with self.assertRaisesRegex(ValueError, "已存在"):
                    inventory_before_duplicate = inventory.read_bytes()
                    save_equipment_item(
                        inventory,
                        "lens",
                        {"brand": "Fujifilm", "model": "XF35mmF2 R WR"},
                        existing_items=catalog["lenses"],
                    )
                self.assertEqual(inventory.read_bytes(), inventory_before_duplicate)

                official_item = next(item for item in catalog["lenses"] if item["model"] == "XF35mmF2 R WR")
                save_equipment_item(
                    inventory,
                    "lens",
                    {"model": "不得覆盖型号", "display_name": "我的 35 定焦", "owned": True},
                    official_item["inventory_key"],
                    catalog["lenses"],
                )
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                official_item = next(item for item in catalog["lenses"] if item["inventory_key"] == official_item["inventory_key"])
                self.assertEqual(official_item["model"], "XF35mmF2 R WR")
                self.assertEqual(official_item["display_name"], "我的 35 定焦")
                inventory_before_protected_delete = inventory.read_bytes()
                with self.assertRaisesRegex(ValueError, "只能删除"):
                    delete_equipment_item(inventory, "lens", official_item["inventory_key"])
                self.assertEqual(inventory.read_bytes(), inventory_before_protected_delete)

                set_equipment_visibility(inventory, "lens", official_item["inventory_key"], False)
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertNotIn(official_item["inventory_key"], {item["inventory_key"] for item in catalog["lenses"]})
                self.assertEqual(catalog["hidden"]["lens"][0]["inventory_key"], official_item["inventory_key"])
                set_equipment_visibility(inventory, "lens", official_item["inventory_key"], True)
                catalog = build_equipment_catalog(connection, profile, official, inventory)
                self.assertIn(official_item["inventory_key"], {item["inventory_key"] for item in catalog["lenses"]})
                self.assertTrue(inventory.with_name("inventory.backup.json").is_file())
            finally:
                connection.close()


if __name__ == "__main__":
    unittest.main()
