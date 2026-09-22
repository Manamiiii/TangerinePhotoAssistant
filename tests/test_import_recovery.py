import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from test_inventory import FakeMetadataReader, settings_for

from tangerine_photo_assistant.albums import assign_captures_to_album, create_album
from tangerine_photo_assistant.database import SCHEMA_VERSION, connect
from tangerine_photo_assistant.import_batch import begin_import, finish_import, pending_import
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.webapp import ScanTaskManager


class ImportRecoveryTests(unittest.TestCase):
    def test_restart_resumes_original_batch_after_each_preassignment_stage(self):
        for stage in ('enrich_metadata', 'rebuild_captures', 'finish_import'):
            with self.subTest(stage=stage), TemporaryDirectory() as directory:
                settings = settings_for(Path(directory))
                old = settings.originals / 'old.JPG'
                old.write_bytes(b'isolated')
                connection = connect(settings.database_path)
                try:
                    scan_library(connection, settings, FakeMetadataReader())
                    rebuild_captures(connection)
                    original = create_album(connection, 'original', '纪念')['id']
                    target = create_album(connection, 'target', '纪念')['id']
                    old_id = connection.execute('SELECT id FROM captures').fetchone()[0]
                    assign_captures_to_album(connection, original, [old_id])
                    old.with_suffix('.RAF').write_bytes(b'isolated raw')
                    (settings.originals / 'new.JPG').write_bytes(b'isolated new')
                    manager = ScanTaskManager(settings)
                    with (
                        patch('tangerine_photo_assistant.webapp.PillowMetadataReader', FakeMetadataReader),
                        patch(f'tangerine_photo_assistant.webapp.{stage}', side_effect=RuntimeError('interrupted')),
                    ):
                        manager._run('first', target)
                    self.assertEqual(manager.snapshot()['status'], 'failed')
                    self.assertEqual(pending_import(connection)['album_id'], target)
                    restarted = ScanTaskManager(settings)
                    self.assertEqual(restarted.snapshot()['stage'], 'import-recovery')
                    with self.assertRaisesRegex(ValueError, 'target'):
                        restarted.start(original)
                    with patch('tangerine_photo_assistant.webapp.PillowMetadataReader', FakeMetadataReader):
                        restarted._run('retry', target)
                    self.assertEqual(restarted.snapshot()['status'], 'complete', restarted.snapshot())
                    self.assertEqual(restarted.snapshot()['result']['assigned_count'], 1)
                    self.assertIsNone(pending_import(connection))
                    self.assertEqual(connection.execute('SELECT event_id FROM event_captures WHERE capture_id=?', (old_id,)).fetchone()[0], original)
                    self.assertEqual(connection.execute('SELECT c.stem FROM event_captures ec JOIN captures c ON c.id=ec.capture_id WHERE ec.event_id=?', (target,)).fetchone()[0], 'new')
                finally:
                    connection.close()

    def test_assignment_failure_keeps_retry_intent(self):
        with TemporaryDirectory() as directory:
            settings = settings_for(Path(directory))
            connection = connect(settings.database_path)
            try:
                target = create_album(connection, 'target', '纪念')['id']
                batch = begin_import(connection, target, settings.originals)
                (settings.originals / 'new.JPG').write_bytes(b'isolated')
                scan_library(connection, settings, FakeMetadataReader())
                rebuild_captures(connection)
                with (
                    patch('tangerine_photo_assistant.import_batch.assign_captures_to_album', side_effect=sqlite3.OperationalError('injected')),
                    self.assertRaisesRegex(sqlite3.OperationalError, 'injected'),
                ):
                    finish_import(connection, batch)
                self.assertEqual(pending_import(connection)['album_id'], target)
                self.assertEqual(finish_import(connection, batch), 1)
            finally:
                connection.close()

    def test_schema33_upgrade_adds_import_intent_without_changing_captures(self):
        with TemporaryDirectory() as directory:
            database = Path(directory) / 'catalog.sqlite3'
            connection = connect(database)
            connection.execute('DROP TABLE import_batch')
            connection.execute('UPDATE schema_info SET version=33')
            connection.commit()
            connection.close()
            upgraded = connect(database)
            try:
                self.assertEqual(upgraded.execute('SELECT version FROM schema_info').fetchone()[0], SCHEMA_VERSION)
                self.assertIsNone(pending_import(upgraded))
                self.assertEqual(upgraded.execute('PRAGMA foreign_key_check').fetchall(), [])
                self.assertEqual(len(list((Path(directory) / 'SchemaBackups').glob('*from33*'))), 1)
            finally:
                upgraded.close()


if __name__ == '__main__':
    unittest.main()
