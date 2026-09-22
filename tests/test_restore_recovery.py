import json
import os
import sqlite3
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.testclient import TestClient

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.equipment import _write_inventory
from tangerine_photo_assistant.restore_recovery import (
    pending_restore_path,
    prepare_inventory_restore,
    recover_inventory_restore,
)
from tangerine_photo_assistant.service_runtime import CONTROL_HEADER, ServiceControl
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.webapp import create_app

CHILD = """
import os, sys
from pathlib import Path
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant import portable_data as p
root=Path(sys.argv[1]); stage=sys.argv[2]
c=connect(root/'catalog.sqlite3'); inventory=root/'inventory.json'
data=p.build_portable_backup(c,inventory)
data['reviews']=[{'capture_key':'one','user_rating':5}]
data['equipment']={'ownership':{'camera':{'new':True}}}
write=p._write_inventory
def interrupted(path, content):
    if stage == 'before_inventory': os._exit(19)
    write(path, content)
    os._exit(19)
if stage == 'after_commit':
    p.recover_inventory_restore=lambda *args: os._exit(19)
else:
    p._write_inventory=interrupted
p.restore_portable_backup(c,data,inventory,root/'backups',p.RESTORE_CONFIRMATION)
"""


class RestoreRecoveryTests(unittest.TestCase):
    def test_startup_recovers_uncommitted_inventory_and_later_pending_record_blocks_writes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "photos").mkdir()
            config = root / "config.toml"
            write_safe_config(config, root / "photos", root / "workspace", root / "cache")
            settings = Settings.load(config)
            inventory = settings.workspace / "Equipment" / "inventory.json"
            inventory.parent.mkdir(parents=True)
            previous = b'{"ownership":{"camera":{"old":true}}}'
            inventory.write_bytes(previous)
            connection = connect(settings.database_path)
            try:
                connection.execute("BEGIN")
                prepare_inventory_restore(
                    connection, inventory, previous, {"ownership": {"camera": {"new": True}}}
                )
                _write_inventory(inventory, {"ownership": {"camera": {"new": True}}})
                connection.rollback()
            finally:
                connection.close()
            with TestClient(create_app(config), base_url="http://localhost") as client:
                self.assertEqual(inventory.read_bytes(), previous)
                self.assertFalse(pending_restore_path(inventory).exists())
                session = client.get("/api/session").json()
                headers = {session["header"]: session["token"]}
                self.assertEqual(
                    client.post(
                        "/api/albums", json={"name": "ok", "category": "纪念"}, headers=headers
                    ).status_code,
                    201,
                )
                pending_restore_path(inventory).write_text("{}", encoding="utf-8")
                self.assertEqual(
                    client.post(
                        "/api/albums", json={"name": "blocked", "category": "纪念"}, headers=headers
                    ).status_code,
                    409,
                )

    def test_corrupt_digest_and_database_binding_are_rejected_without_overwrite(self):
        for field, value in [("following_sha256", "bad"), ("database", "different.sqlite3")]:
            with self.subTest(field=field), TemporaryDirectory() as directory:
                root = Path(directory)
                connection = connect(root / "catalog.sqlite3")
                inventory = root / "inventory.json"
                try:
                    connection.execute("BEGIN")
                    prepare_inventory_restore(connection, inventory, None, {})
                    connection.rollback()
                    path = pending_restore_path(inventory)
                    record = json.loads(path.read_bytes())
                    record[field] = value
                    path.write_text(json.dumps(record), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "无法核对"):
                        recover_inventory_restore(connection, inventory)
                    self.assertFalse(inventory.exists())
                    self.assertTrue(path.exists())
                finally:
                    connection.close()

    def test_real_process_exit_recovers_before_and_after_database_commit(self):
        for existing in (False, True):
            for stage in ("before_inventory", "after_inventory", "after_commit"):
                with (
                    self.subTest(existing=existing, stage=stage),
                    TemporaryDirectory() as directory,
                ):
                    root = Path(directory)
                    inventory = root / "inventory.json"
                    old = b'{"ownership":{"camera":{"old":true}}}'
                    if existing:
                        inventory.write_bytes(old)
                    connection = connect(root / "catalog.sqlite3")
                    connection.execute(
                        "INSERT INTO captures(capture_key,parent_relative,stem,pairing_status) VALUES ('one','','one','jpeg_only')"
                    )
                    connection.commit()
                    connection.close()
                    child = subprocess.run(
                        [sys.executable, "-c", CHILD, str(root), stage],
                        capture_output=True,
                        timeout=15,
                        check=False,
                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                    )
                    self.assertEqual(child.returncode, 19, child.stderr.decode(errors="replace"))
                    self.assertTrue(pending_restore_path(inventory).exists())
                    connection = connect(root / "catalog.sqlite3")
                    try:
                        self.assertTrue(recover_inventory_restore(connection, inventory))
                        self.assertFalse(recover_inventory_restore(connection, inventory))
                        reviews = connection.execute(
                            "SELECT user_rating FROM capture_reviews"
                        ).fetchall()
                        if stage == "after_commit":
                            self.assertEqual(reviews[0][0], 5)
                            self.assertEqual(
                                json.loads(inventory.read_bytes())["ownership"]["camera"],
                                {"new": True},
                            )
                        else:
                            self.assertEqual(reviews, [])
                            self.assertEqual(
                                inventory.read_bytes() if inventory.exists() else None,
                                old if existing else None,
                            )
                        self.assertEqual(
                            connection.execute("PRAGMA integrity_check").fetchone()[0], "ok"
                        )
                        self.assertEqual(
                            connection.execute("PRAGMA foreign_key_check").fetchall(), []
                        )
                    finally:
                        connection.close()

    def test_external_inventory_change_is_not_overwritten(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            connection = connect(root / "catalog.sqlite3")
            connection.close()
            child = subprocess.run(
                [sys.executable, "-c", CHILD, str(root), "after_commit"],
                capture_output=True,
                timeout=15,
                check=False,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            self.assertEqual(child.returncode, 19, child.stderr.decode(errors="replace"))
            inventory = root / "inventory.json"
            inventory.write_bytes(b'{"external":true}')
            connection = connect(root / "catalog.sqlite3")
            try:
                with self.assertRaisesRegex(ValueError, "不一致"):
                    recover_inventory_restore(connection, inventory)
                self.assertEqual(inventory.read_bytes(), b'{"external":true}')
                self.assertTrue(pending_restore_path(inventory).exists())
            finally:
                connection.close()

    def test_bad_recovery_record_keeps_reads_available_and_blocks_writes(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "photos").mkdir()
            config = root / "config.toml"
            write_safe_config(config, root / "photos", root / "workspace", root / "cache")
            settings = Settings.load(config)
            inventory = settings.workspace / "Equipment" / "inventory.json"
            inventory.parent.mkdir(parents=True)
            marker = pending_restore_path(inventory)
            marker.write_text("{broken", encoding="utf-8")
            control = ServiceControl(config, 8765)
            with TestClient(
                create_app(config, service_control=control), base_url="http://localhost"
            ) as client:
                session = client.get("/api/session").json()
                headers = {session["header"]: session["token"]}
                self.assertEqual(client.get("/api/health").status_code, 200)
                self.assertEqual(client.get("/api/albums").status_code, 200)
                self.assertEqual(
                    client.get("/api/tasks/current").json()["stage"], "human-data-recovery"
                )
                self.assertEqual(
                    client.post(
                        "/api/albums", json={"name": "blocked", "category": "纪念"}, headers=headers
                    ).status_code,
                    409,
                )
                self.assertEqual(marker.read_text(encoding="utf-8"), "{broken")
                self.assertEqual(
                    client.post(
                        "/api/system/desktop/shutdown",
                        headers={**headers, CONTROL_HEADER: control.token},
                    ).status_code,
                    200,
                )

    def test_schema34_upgrade_keeps_verified_backup_without_commit_table(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / "catalog.sqlite3"
            connection = connect(path)
            connection.execute("DROP TABLE human_restore_commits")
            connection.execute("UPDATE schema_info SET version=34")
            connection.commit()
            connection.close()
            connection = connect(path)
            self.assertEqual(
                connection.execute("SELECT COUNT(*) FROM human_restore_commits").fetchone()[0], 0
            )
            connection.close()
            backup = next((root / "SchemaBackups").glob("*from34*"))
            with sqlite3.connect(backup) as saved:
                self.assertEqual(saved.execute("PRAGMA integrity_check").fetchone()[0], "ok")
                self.assertEqual(saved.execute("SELECT version FROM schema_info").fetchone()[0], 34)
                self.assertIsNone(
                    saved.execute(
                        "SELECT name FROM sqlite_master WHERE name='human_restore_commits'"
                    ).fetchone()
                )
            saved.close()
