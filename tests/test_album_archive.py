import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from tangerine_photo_assistant import album_archive as archive
from tangerine_photo_assistant.albums import assign_captures_to_album, create_album
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.metadata import PillowMetadataReader
from tangerine_photo_assistant.pairing import rebuild_captures
from tangerine_photo_assistant.queries.albums import query_albums
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.structure import rebuild_structure
from tangerine_photo_assistant.webapp import ScanTaskManager, create_app


class AlbumArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        photos = self.root / 'photos'
        photos.mkdir()
        config = self.root / 'config.toml'
        write_safe_config(config, photos, self.root / 'workspace', self.root / 'cache')
        self.settings = Settings.load(config)
        self.source = photos / '待整理' / 'batch'
        self.source.mkdir(parents=True)
        for name in ('DSCF0001', 'DSCF0002'):
            Image.new('RGB', (16, 16), 'red').save(self.source / f'{name}.JPG')
            (self.source / f'{name}.RAF').write_bytes(b'isolated fake raw')
        self.db = connect(self.settings.database_path)
        self.addCleanup(self.db.close)
        scan_library(self.db, self.settings, PillowMetadataReader())
        rebuild_captures(self.db)
        rebuild_structure(self.db, 3)
        self.ids = [r[0] for r in self.db.execute('SELECT id FROM captures')]
        self.album = create_album(self.db, 'Birthday', '纪念')['id']
        assign_captures_to_album(self.db, self.album, self.ids)
        self.db.execute("INSERT INTO capture_reviews(capture_id,user_rating,user_pick,updated_at) VALUES (?,5,1,'now')", (self.ids[0],))
        self.db.commit()

    def plan(self):
        return archive.preview(self.db, self.settings, self.album)

    def prepare(self, plan):
        return archive.prepare(self.db, self.settings, plan['id'], '归档 Birthday')

    def run_plan(self, plan, progress=lambda *_: None):
        return archive.execute(self.db, self.settings, plan, progress)

    def test_archive_preserves_identity_reviews_pairs_after_rescan(self):
        extra = self.source / 'notes.txt'
        extra.write_text('keep me')
        plan = self.prepare(self.plan())
        progress = []
        result = self.run_plan(plan, lambda current, total, phase: progress.append((current, total, phase)))
        self.assertEqual(result['archived_count'], 2)
        self.assertEqual(list(dict.fromkeys(p[2] for p in progress)),
                         ['复制校验', '提交前复核', '更新图库路径', '清理待整理源文件'])
        self.assertEqual(progress[-1], (4, 4, '清理待整理源文件'))
        self.assertTrue(extra.exists())
        self.assertEqual(len(list(self.source.iterdir())), 1)
        self.assertEqual(len(list(Path(plan['target']).iterdir())), 4)
        scan_library(self.db, self.settings, PillowMetadataReader())
        rebuild_captures(self.db)
        rebuild_structure(self.db, 3)
        self.assertEqual([r[0] for r in self.db.execute('SELECT id FROM captures')], self.ids)
        self.assertEqual(self.db.execute('SELECT user_rating FROM capture_reviews').fetchone()[0], 5)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM captures WHERE pairing_status='paired'").fetchone()[0], 2)
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])
        self.assertIsNone(archive.pending(self.settings))

    def test_stale_preview_and_target_conflict_do_not_write_photos(self):
        plan = self.plan()
        target = Path(plan['items'][0]['target'])
        target.parent.mkdir(parents=True)
        target.write_bytes(b'untouchable')
        with self.assertRaises(ValueError):
            self.prepare(plan)
        self.assertEqual(target.read_bytes(), b'untouchable')
        self.assertEqual(len(list(self.source.iterdir())), 4)
        self.assertIsNone(archive.pending(self.settings))

    def test_changed_source_invalidates_preview(self):
        plan = self.plan()
        Path(plan['items'][0]['source']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            self.prepare(plan)
        self.assertFalse(Path(plan['target']).exists())

    def test_interrupted_copy_is_resumable_and_blocks_scan_after_restart(self):
        plan = self.prepare(self.plan())
        def interrupt(*_):
            raise RuntimeError('power interruption')
        with self.assertRaises(RuntimeError):
            self.run_plan(plan, interrupt)
        self.assertEqual(len(list(self.source.iterdir())), 4)
        manager = ScanTaskManager(self.settings)
        self.assertEqual(manager.snapshot()['status'], 'paused')
        with self.assertRaises(RuntimeError):
            manager.start(self.album)
        with self.assertRaises(ValueError):
            scan_library(self.db, self.settings, PillowMetadataReader())
        self.run_plan(archive.load(self.settings, plan['id']))
        self.assertFalse(self.source.exists())

    def test_cleanup_failure_retries_after_index_commit(self):
        plan = self.prepare(self.plan())
        original = Path.unlink
        def fail_source(path, *args, **kwargs):
            if path.parent == self.source:
                raise PermissionError('locked source')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_source), self.assertRaises(PermissionError):
            self.run_plan(plan)
        self.assertTrue(all(Path(r[0]).is_relative_to(Path(plan['target'])) for r in self.db.execute('SELECT path FROM files')))
        self.run_plan(archive.load(self.settings, plan['id']))
        self.assertFalse(self.source.exists())

    def test_corrupt_target_on_resume_preserves_source(self):
        plan = self.prepare(self.plan())
        with self.assertRaises(RuntimeError):
            self.run_plan(plan, lambda *_: (_ for _ in ()).throw(RuntimeError()))
        target = Path(plan['items'][0]['target'])
        target.write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            self.run_plan(archive.load(self.settings, plan['id']))
        self.assertEqual(len(list(self.source.iterdir())), 4)

    def test_index_commit_failure_keeps_sources_and_recovers(self):
        plan = self.prepare(self.plan())
        with patch.object(archive, 'transaction', side_effect=RuntimeError('commit failure')), self.assertRaises(RuntimeError):
            self.run_plan(plan)
        self.assertEqual(len(list(self.source.iterdir())), 4)
        self.assertTrue(all(Path(r[0]).parent == self.source for r in self.db.execute('SELECT path FROM files')))
        self.run_plan(archive.load(self.settings, plan['id']))
        self.assertFalse(self.source.exists())

    def test_plan_path_traversal_and_foreign_temporary_are_rejected(self):
        plan = self.prepare(self.plan())
        forged = json.loads(json.dumps(plan))
        forged['items'][0]['target'] = str(self.settings.originals / '..' / 'outside.JPG')
        with self.assertRaises(ValueError):
            self.run_plan(forged)
        target = Path(plan['items'][0]['target'])
        target.parent.mkdir(parents=True)
        temporary = target.with_name(f'.{target.name}.tangerine-part-{plan["id"]}')
        temporary.write_bytes(b'foreign file')
        with self.assertRaises(ValueError):
            self.run_plan(plan)
        self.assertEqual(temporary.read_bytes(), b'foreign file')

    def test_link_paths_and_outside_inbox_rejected(self):
        with patch.object(Path, 'is_junction', return_value=True), self.assertRaises(ValueError):
            self.plan()
        self.db.execute('UPDATE files SET path=? WHERE id=(SELECT MIN(id) FROM files)', (str(self.root / 'outside.JPG'),))
        self.db.commit()
        with self.assertRaises(ValueError):
            self.plan()

    def test_confirmation_and_plan_album_membership_are_bound(self):
        plan = self.plan()
        with self.assertRaises(ValueError):
            archive.prepare(self.db, self.settings, plan['id'], 'wrong')
        self.db.execute('UPDATE events SET proposed_name=? WHERE id=?', ('Changed', self.album))
        self.db.commit()
        with self.assertRaises(ValueError):
            self.prepare(plan)
        saved = json.loads((self.settings.workspace / 'AlbumArchive' / f"{plan['id']}.json").read_text(encoding='utf8'))
        self.assertEqual(saved['status'], 'preview')

    def test_album_list_distinguishes_inbox_mixed_filed_and_pending_cleanup(self):
        def state(pending_id=None):
            return next(item for item in query_albums(self.settings.database_path, 50, 0, pending_id)['items'] if item['id'] == self.album)
        self.assertEqual(state()['archive_state'], 'inbox')
        self.assertEqual(state()['inbox_capture_count'], 2)
        self.db.execute("UPDATE captures SET parent_relative='纪念/2026/Birthday' WHERE id=?", (self.ids[0],))
        self.db.commit()
        self.assertEqual(state()['archive_state'], 'mixed')
        self.db.execute("UPDATE captures SET parent_relative='纪念/2026/Birthday'")
        self.db.commit()
        self.assertEqual(state()['archive_state'], 'filed')
        self.assertEqual(state(self.album)['archive_state'], 'pending')

    def test_system_api_resumes_pending_blocks_other_writes_and_finishes(self):
        plan = self.prepare(self.plan())
        with TestClient(create_app(self.root / 'config.toml'), base_url='http://127.0.0.1') as client:
            session = client.get('/api/session').json()
            headers = {session['header']: session['token']}
            self.assertEqual(client.get('/api/tasks/current').json()['status'], 'paused')
            self.assertEqual(client.post('/api/scan', json={'album_id': self.album}, headers=headers).status_code, 409)
            self.assertEqual(client.post('/api/albums', json={'name': 'other', 'category': '纪念'}, headers=headers).status_code, 409)
            response = client.post(f'/api/albums/{self.album}/archive/execute',
                json={'plan_id': plan['id'], 'confirmation': '归档 Birthday'}, headers=headers)
            self.assertEqual(response.status_code, 202, response.text)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                status = client.get('/api/tasks/current').json()
                if status['status'] != 'running':
                    break
                time.sleep(.02)
            self.assertEqual(status['status'], 'complete', status)
            self.assertEqual(client.get(f'/api/albums/{self.album}/archive/status').json(),
                             {'file_count': 4, 'inbox_count': 0, 'pending': False})
