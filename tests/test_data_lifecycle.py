import re
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import test_album_archive
from test_inventory import FakeMetadataReader, settings_for

from tangerine_photo_assistant import album_archive
from tangerine_photo_assistant.albums import assign_captures_to_album, create_album
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.portable_data import (
    RESTORE_CONFIRMATION,
    build_portable_backup,
    preflight_restore,
    restore_portable_backup,
)
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.tags import replace_manual_capture_tags
from tangerine_photo_assistant.webapp import ScanTaskManager, create_app


class DataLifecycleTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.settings = settings_for(self.root)
        self.photo = self.settings.originals / 'A.JPG'
        self.photo.write_bytes(b'isolated fixture')
        self.db = connect(self.settings.database_path)
        self.addCleanup(self.db.close)
        scan_library(self.db, self.settings, FakeMetadataReader())
        rebuild_captures(self.db)
        self.capture = self.db.execute('SELECT id FROM captures').fetchone()[0]

    def test_incomplete_scan_preserves_index_and_records_failure(self):
        before = [tuple(row) for row in self.db.execute('SELECT * FROM files')]

        def broken_walk(root, on_error):
            extra = root / 'new.JPG'
            extra.write_bytes(b'isolated new file')
            yield extra, extra.stat()
            on_error(root, PermissionError('injected inaccessible directory'))

        with patch('tangerine_photo_assistant.inventory.iter_files', broken_walk), self.assertRaisesRegex(OSError, '扫描不完整'):
            scan_library(self.db, self.settings)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM files')], before)
        self.assertEqual(self.db.execute('SELECT status FROM scan_runs ORDER BY id DESC').fetchone()[0], 'failed')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM scan_errors').fetchone()[0], 1)

    def test_missing_then_returned_photo_retains_id_tags_review_and_mapping(self):
        replace_manual_capture_tags(self.db, self.capture, [{'dimension': 'subject', 'name': 'fixture'}])
        self.db.execute("INSERT INTO capture_reviews(capture_id,user_rating,updated_at) VALUES (?,5,'now')", (self.capture,))
        self.db.commit()
        before = [tuple(row) for row in self.db.execute('SELECT * FROM capture_files')]
        hidden = self.photo.with_suffix('.hidden')
        self.photo.rename(hidden)
        scan_library(self.db, self.settings)
        rebuild_captures(self.db)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM capture_files')], before)
        hidden.rename(self.photo)
        scan_library(self.db, self.settings)
        rebuild_captures(self.db)
        self.assertEqual(self.db.execute('SELECT id FROM captures').fetchone()[0], self.capture)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT user_rating FROM capture_reviews').fetchone()[0], 5)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM capture_tags').fetchone()[0], 1)

    def test_missing_capture_with_only_tags_is_not_deleted(self):
        replace_manual_capture_tags(self.db, self.capture, [{'dimension': 'subject', 'name': 'fixture'}])
        self.photo.unlink()
        scan_library(self.db, self.settings)
        rebuild_captures(self.db)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM capture_tags').fetchone()[0], 1)
        self.assertEqual(self.db.execute('SELECT id FROM captures').fetchone()[0], self.capture)

    def test_new_raw_preserves_album_but_new_capture_enters_selected_album(self):
        original = create_album(self.db, 'original', '纪念')['id']
        target = create_album(self.db, 'target', '纪念')['id']
        assign_captures_to_album(self.db, original, [self.capture])
        self.photo.with_suffix('.RAF').write_bytes(b'isolated raw')
        (self.settings.originals / 'B.JPG').write_bytes(b'isolated new photo')
        manager = ScanTaskManager(self.settings)
        with patch('tangerine_photo_assistant.webapp.PillowMetadataReader', FakeMetadataReader):
            manager._run('fixture', target)
        self.assertEqual(manager.snapshot()['status'], 'complete')
        self.assertEqual(manager.snapshot()['result']['assigned_count'], 1)
        self.assertEqual(self.db.execute('SELECT event_id FROM event_captures WHERE capture_id=?', (self.capture,)).fetchone()[0], original)

    def test_invalid_startup_config_does_not_create_database_inside_photos(self):
        config = self.root / 'unsafe.toml'
        write_safe_config(config, self.settings.originals, self.root / 'safe', self.root / 'other-cache')
        text = config.read_text(encoding='utf-8')
        text = re.sub(r'^workspace = .+$', "workspace = '" + (self.settings.originals / 'unsafe').as_posix() + "'", text, flags=re.MULTILINE)
        config.write_text(text, encoding='utf-8')
        unsafe = Settings.load(config)
        with self.assertRaisesRegex(ValueError, 'Workspace must not'):
            create_app(config)
        self.assertFalse(unsafe.workspace.exists())

    def test_backup_from_before_filing_restores_after_filing(self):
        fixture = test_album_archive.AlbumArchiveTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        inventory = fixture.root / 'inventory.json'
        data = build_portable_backup(fixture.db, inventory)
        plan = fixture.prepare(fixture.plan())
        album_archive.execute(fixture.db, fixture.settings, plan, lambda *args: None)
        self.assertEqual(preflight_restore(fixture.db, data)['missing_captures'], 0)
        fixture.db.execute('UPDATE capture_reviews SET user_rating=1')
        fixture.db.commit()
        restore_portable_backup(fixture.db, data, inventory, fixture.root / 'backups', RESTORE_CONFIRMATION)
        self.assertEqual(fixture.db.execute('SELECT user_rating FROM capture_reviews').fetchone()[0], 5)

    def test_ambiguous_historical_key_blocks_restore_without_writes(self):
        replace_manual_capture_tags(self.db, self.capture, [{'dimension': 'subject', 'name': 'fixture'}])
        data = build_portable_backup(self.db, self.root / 'inventory.json')
        key = self.db.execute('SELECT capture_key FROM captures').fetchone()[0]
        self.db.execute("UPDATE captures SET capture_key='moved/a' WHERE id=?", (self.capture,))
        self.db.execute("INSERT INTO captures(capture_key,parent_relative,stem,pairing_status) VALUES (?,'new','A','jpeg_only')", (key,))
        self.db.commit()
        with self.assertRaisesRegex(ValueError, '多个拍摄单元'):
            restore_portable_backup(self.db, data, self.root / 'inventory.json', self.root / 'backups', RESTORE_CONFIRMATION)
        self.assertFalse((self.root / 'backups').exists())
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM capture_tags').fetchone()[0], 1)

    def test_aliases_are_transactional_and_exclude_temporary_rebuild_keys(self):
        before = [tuple(row) for row in self.db.execute('SELECT * FROM capture_key_aliases')]
        self.db.execute("UPDATE captures SET capture_key='uncommitted/a'")
        self.db.rollback()
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM capture_key_aliases')], before)
        rebuild_captures(self.db)
        self.assertEqual([tuple(row) for row in self.db.execute('SELECT * FROM capture_key_aliases')], before)

    def test_schema32_upgrade_seeds_aliases_and_backs_up_existing_data(self):
        replace_manual_capture_tags(self.db, self.capture, [{'dimension': 'subject', 'name': 'fixture'}])
        self.db.executescript('''DROP TRIGGER capture_key_alias_insert;
            DROP TRIGGER capture_key_alias_update;
            DROP TABLE capture_key_aliases;
            UPDATE schema_info SET version=32;''')
        upgraded = connect(self.settings.database_path)
        try:
            self.assertEqual(upgraded.execute('SELECT version FROM schema_info').fetchone()[0], 33)
            self.assertEqual(upgraded.execute('SELECT capture_id FROM capture_key_aliases').fetchone()[0], self.capture)
            self.assertEqual(upgraded.execute('SELECT COUNT(*) FROM capture_tags').fetchone()[0], 1)
            self.assertEqual(upgraded.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally:
            upgraded.close()
        backups = list(self.settings.workspace.rglob('*pre-schema33-from32*.sqlite3'))
        self.assertEqual(len(backups), 1)
        backup = sqlite3.connect(f'{backups[0].as_uri()}?mode=ro', uri=True)
        try:
            self.assertEqual(backup.execute('SELECT version FROM schema_info').fetchone()[0], 32)
            self.assertEqual(backup.execute('SELECT COUNT(*) FROM capture_tags').fetchone()[0], 1)
            self.assertEqual(backup.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        finally:
            backup.close()

    def test_effective_root_is_checked_before_schema_upgrade(self):
        config = self.root / 'config.toml'
        write_safe_config(config, self.settings.originals, self.settings.workspace, self.settings.cache_root)
        self.db.execute('''INSERT INTO library_state(id,archive_root,active_root,switched_at,status)
            VALUES(1,?,?, 'now','active')''', (str(self.settings.originals), str(self.settings.workspace)))
        self.db.execute('UPDATE schema_info SET version=32')
        self.db.commit()
        with self.assertRaises(ValueError):
            create_app(config)
        self.assertEqual(self.db.execute('SELECT version FROM schema_info').fetchone()[0], 32)
        self.assertFalse(list(self.settings.workspace.rglob('*pre-schema33*')))

    def test_pairing_collision_rolls_back_without_merging_capture_history(self):
        (self.settings.originals / 'B.RAF').write_bytes(b'isolated raw')
        scan_library(self.db, self.settings)
        rebuild_captures(self.db)
        self.db.execute("UPDATE files SET stem='A' WHERE extension='.raf'")
        self.db.commit()
        before = {table: [tuple(row) for row in self.db.execute(f'SELECT * FROM {table}')]
                  for table in ('captures', 'capture_files', 'capture_key_aliases')}
        with self.assertRaisesRegex(ValueError, '多个已有拍摄单元'):
            rebuild_captures(self.db)
        for table, rows in before.items():
            self.assertEqual([tuple(row) for row in self.db.execute(f'SELECT * FROM {table}')], rows)
