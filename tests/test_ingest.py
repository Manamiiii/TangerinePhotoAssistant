import json
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from tangerine_photo_assistant import album_archive, ingest
from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.inventory import scan_library
from tangerine_photo_assistant.queries.albums import query_albums
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.webapp import ScanTaskManager, create_app


class ImportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / 'card'
        self.source.mkdir()
        self.photos = self.root / 'photos'
        self.photos.mkdir()
        self.config = self.root / 'config.toml'
        write_safe_config(self.config, self.photos, self.root / 'workspace', self.root / 'cache')
        self.settings = Settings.load(self.config)
        self.db = connect(self.settings.database_path)
        self.addCleanup(self.db.close)
        Image.new('RGB', (12, 12), 'red').save(self.source / 'A.JPG')
        (self.source / 'A.RAF').write_bytes(b'fake-raw')
        (self.source / 'A.xmp').write_bytes(b'<original-sidecar/>')
        (self.source / 'B.MOV').write_bytes(b'video-original')
        (self.source / 'B.LRF').write_bytes(b'preview-original')
        (self.source / 'ignore.exe').write_bytes(b'never-copy')

    def preview(self, source=None):
        job = ingest.new_job(self.db, self.settings, str(source or self.source))
        ingest.inspect(self.db, self.settings, job, lambda *_: None)
        return job

    def copy_index(self, job, album_id=None):
        ingest.prepare(self.db, self.settings, job, album_id, 'Test album', '日常')
        ingest.copy_files(self.db, self.settings, job, lambda *_: None)
        ingest.index_files(self.db, self.settings, job, lambda *_: None)

    def test_complete_flow_preserves_sources_and_archives_video_sidecars(self):
        original = {p.name:p.read_bytes() for p in self.source.iterdir()}
        unrelated = self.photos / '待整理' / 'other' / 'untouched.JPG'
        unrelated.parent.mkdir(parents=True)
        Image.new('RGB', (16,16), 'blue').save(unrelated)
        job = self.preview()
        self.assertEqual(job['ignored'], ['ignore.exe'])
        self.copy_index(job)
        self.assertEqual(job['capture_count'], 1)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM files').fetchone()[0], 5)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM album_files').fetchone()[0], 5)
        plan = album_archive.preview(self.db, self.settings, job['album_id'])
        self.assertEqual(plan['attachment_count'], 3)
        album_archive.prepare(self.db,self.settings,plan['id'],'归档 Test album')
        album_archive.execute(self.db,self.settings,plan,lambda *_:None)
        self.assertEqual(original, {p.name:p.read_bytes() for p in self.source.iterdir()})
        for item in plan['items']:
            self.assertFalse(Path(item['source']).exists())
            self.assertEqual(Path(item['target']).read_bytes(), original[Path(item['target']).name])
        self.assertTrue(unrelated.exists())
        self.assertEqual(query_albums(self.settings.database_path,20,0)['items'][0]['archive_state'],'filed')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_duplicate_family_does_not_split_pair_and_reimport_skips(self):
        job = self.preview(); self.copy_index(job)
        again = self.preview()
        self.assertEqual(again['duplicate_count'],5)
        with self.assertRaises(ValueError):
            ingest.prepare(self.db,self.settings,again,None,'Other','日常')
        (self.source/'A.RAF').write_bytes(b'new RAW content')
        changed = self.preview()
        self.assertEqual(changed['duplicate_count'],2)
        self.assertTrue(all(not i['skip'] for i in changed['items'] if Path(i['source']).stem=='A'))

    def test_changed_source_and_foreign_target_block_and_resume(self):
        job=self.preview()
        ingest.prepare(self.db,self.settings,job,None,'Test album','日常')
        item=job['items'][0]; target=Path(item['target']);target.parent.mkdir(parents=True)
        target.write_bytes(b'foreign')
        with self.assertRaisesRegex(ValueError,'目标冲突'):
            ingest.copy_files(self.db,self.settings,job,lambda *_:None)
        self.assertEqual(target.read_bytes(),b'foreign')
        target.unlink()
        original=Path(item['source']).read_bytes()
        Path(item['source']).write_bytes(b'changed')
        with self.assertRaises(ValueError):
            ingest.copy_files(self.db,self.settings,job,lambda *_:None)
        Path(item['source']).write_bytes(original)
        import os
        os.utime(item['source'],ns=(item['mtime'],item['mtime']))
        ingest.copy_files(self.db,self.settings,job,lambda *_:None)
        restored=ingest.load(self.db,job['id'])
        ingest.index_files(self.db,self.settings,restored,lambda *_:None)
        count=self.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0]
        ingest.index_files(self.db,self.settings,restored,lambda *_:None)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM captures').fetchone()[0],count)

    def test_inbox_batch_can_be_adopted_without_copying(self):
        inbox=self.photos/'待整理'/'video-batch';inbox.mkdir(parents=True)
        (inbox/'clip.MOV').write_bytes(b'clip')
        job=self.preview(inbox);self.copy_index(job)
        self.assertEqual(job['destination'],str(inbox))
        self.assertEqual(job['capture_count'],0)
        self.assertEqual(query_albums(self.settings.database_path,20,0)['items'][0]['archive_state'],'inbox')
        plan=album_archive.preview(self.db,self.settings,job['album_id'])
        self.assertEqual(len(plan['items']),1)

    def test_paths_links_and_indexed_inbox_are_rejected(self):
        for path in [self.photos,self.photos/'待整理',self.settings.workspace,self.root]:
            path.mkdir(exist_ok=True)
            with self.assertRaises(ValueError): ingest.new_job(self.db,self.settings,str(path))
        with patch.object(Path,'is_junction',return_value=True), self.assertRaises(ValueError):
            self.preview()
        inbox=self.photos/'待整理'/'old';inbox.mkdir(parents=True)
        Image.new('RGB',(8,8)).save(inbox/'old.JPG')
        scan_library(self.db,self.settings)
        from tangerine_photo_assistant.pairing import rebuild_captures
        rebuild_captures(self.db)
        job=ingest.new_job(self.db,self.settings,str(inbox))
        with self.assertRaisesRegex(ValueError,'已有入库照片'):
            ingest.inspect(self.db,self.settings,job,lambda *_:None)

    def test_api_recovery_auth_and_write_exclusion(self):
        job=self.preview()
        ingest.prepare(self.db,self.settings,job,None,'Test album','日常')
        manager=ScanTaskManager(self.settings)
        self.assertEqual(manager.snapshot()['status'],'paused')
        with TestClient(create_app(self.config),base_url='http://127.0.0.1') as client:
            self.assertEqual(client.post('/api/imports/check',json={'source':str(self.source)}).status_code,403)
            session=client.get('/api/session').json();headers={session['header']:session['token']}
            self.assertEqual(client.post('/api/scan',json={'album_id':job['album_id']},headers=headers).status_code,409)
            self.assertEqual(client.post(f'/api/imports/{job["id"]}/start',json={'confirmed':False},headers=headers).status_code,422)
            response=client.post(f'/api/imports/{job["id"]}/start',json={'confirmed':True},headers=headers)
            self.assertEqual(response.status_code,202,response.text)
            for _ in range(100):
                state=client.get('/api/tasks/current').json()
                if state['status']!='running':break
                time.sleep(.05)
            self.assertEqual(state['status'],'complete',state)
            detail=client.get(f'/api/imports/{job["id"]}?limit=2').json()
            self.assertEqual(len(detail['items']),2)
            self.assertEqual(client.get(f'/api/albums/{job["album_id"]}/files').json()['count'],3)
            self.assertNotIn('capture_ids_before',detail)
            self.assertEqual(json.loads(self.db.execute('SELECT data_json FROM import_jobs').fetchone()[0])['state'],'ready')

    def test_scanned_unassigned_video_can_be_adopted_and_keeps_sources_after_rebuild(self):
        inbox = self.photos / '待整理' / 'old-video'
        inbox.mkdir(parents=True)
        video = inbox / 'clip.MOV'
        video.write_bytes(b'old video')
        scan_library(self.db, self.settings)
        video.write_bytes(b'updated unassigned video')
        job = self.preview(inbox)
        self.copy_index(job)
        row = self.db.execute('SELECT size_bytes FROM files WHERE path=?', (str(video),)).fetchone()
        self.assertEqual(row[0], video.stat().st_size)
        from tangerine_photo_assistant.structure import rebuild_structure
        rebuild_structure(self.db, self.settings.burst_time_gap_seconds)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM event_sources WHERE event_id=?',
                                        (job['album_id'],)).fetchone()[0], 1)
        self.assertEqual(len(album_archive.preview(self.db,self.settings,job['album_id'])['items']), 1)

    def test_moving_photo_moves_companions_without_moving_unrelated_video(self):
        from tangerine_photo_assistant.albums import assign_captures_to_album, create_album
        job = self.preview(); self.copy_index(job)
        other = create_album(self.db, 'Other album', '日常')
        capture = self.db.execute('SELECT capture_id FROM event_captures WHERE event_id=?',
                                  (job['album_id'],)).fetchone()[0]
        assign_captures_to_album(self.db, other['id'], [capture])
        source_plan = album_archive.preview(self.db, self.settings, job['album_id'])
        target_plan = album_archive.preview(self.db, self.settings, other['id'])
        self.assertEqual({Path(i['source']).name for i in source_plan['items']}, {'B.MOV','B.LRF'})
        self.assertEqual({Path(i['source']).name for i in target_plan['items']}, {'A.JPG','A.RAF','A.xmp'})
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])

    def test_append_to_filed_album_with_same_names_uses_distinct_batch_directory(self):
        first = self.preview(); self.copy_index(first)
        plan = album_archive.preview(self.db,self.settings,first['album_id'])
        album_archive.prepare(self.db,self.settings,plan['id'],'归档 Test album')
        album_archive.execute(self.db,self.settings,plan,lambda *_:None)
        (self.source/'A.RAF').write_bytes(b'second capture raw')
        second = self.preview(); self.copy_index(second, first['album_id'])
        next_plan = album_archive.preview(self.db,self.settings,first['album_id'])
        self.assertEqual(len(next_plan['items']), 3)
        self.assertFalse({i['target'] for i in plan['items']} & {i['target'] for i in next_plan['items']})
        album_archive.prepare(self.db,self.settings,next_plan['id'],'归档 Test album')
        album_archive.execute(self.db,self.settings,next_plan,lambda *_:None)
        self.assertEqual(query_albums(self.settings.database_path,20,0)['items'][0]['archive_state'],'filed')

    def test_worker_database_failure_does_not_leave_running_task(self):
        manager = ScanTaskManager(self.settings)
        with patch('tangerine_photo_assistant.ingest_tasks.connect', side_effect=OSError('disk unavailable')):
            manager._run_import_job('failed-open')
        self.assertEqual(manager.snapshot()['status'], 'paused')
        self.assertIn('disk unavailable', manager.snapshot()['message'])

    def test_resume_after_published_copy_and_index_commit_preserves_identity(self):
        job=self.preview()
        ingest.prepare(self.db,self.settings,job,None,'Test album','日常')
        ingest.copy_files(self.db,self.settings,job,lambda *_:None)
        # Simulate interruption after file indexing committed but before pairing.
        with patch('tangerine_photo_assistant.ingest.enrich_metadata',side_effect=OSError('interrupted')), self.assertRaises(OSError):
            ingest.index_files(self.db,self.settings,job,lambda *_:None)
        ids = {r[0] for r in self.db.execute('SELECT id FROM files')}
        restored = ingest.load(self.db,job['id'])
        ingest.index_files(self.db,self.settings,restored,lambda *_:None)
        self.assertEqual(ids,{r[0] for r in self.db.execute('SELECT id FROM files')})
        self.assertEqual(restored['capture_count'],1)
        self.assertEqual(len([i for i in restored['items'] if i.get('file_id')]),5)

    def test_raw_extension_sidecar_is_kept_with_new_family_and_moves_with_photo(self):
        from tangerine_photo_assistant.albums import assign_captures_to_album, create_album
        (self.source/'A.RAF.xmp').write_bytes(b'raw-sidecar')
        job = self.preview(); self.copy_index(job)
        (self.source/'A.RAF').write_bytes(b'new raw')
        again = self.preview()
        self.assertFalse(next(i for i in again['items'] if i['relative']=='A.RAF.xmp')['skip'])
        other = create_album(self.db,'Another album','日常')
        capture = self.db.execute('SELECT capture_id FROM event_captures WHERE event_id=?',(job['album_id'],)).fetchone()[0]
        assign_captures_to_album(self.db,other['id'],[capture])
        plan = album_archive.preview(self.db,self.settings,other['id'])
        self.assertIn('A.RAF.xmp',{Path(i['source']).name for i in plan['items']})
