import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from tangerine_photo_assistant.database import connect
from tangerine_photo_assistant.service_runtime import CONTROL_HEADER, ServiceControl
from tangerine_photo_assistant.settings import Settings, write_safe_config
from tangerine_photo_assistant.webapp import create_app


class TaskControlConcurrencyTests(unittest.TestCase):
    def test_export_allows_reviews_and_cancel_but_protects_other_writes_and_shutdown(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / 'photos'
            photos.mkdir()
            config = root / 'config.toml'
            write_safe_config(config, photos, root / 'workspace', root / 'cache')
            connection = connect(Settings.load(config).database_path)
            connection.execute("INSERT INTO captures(capture_key,parent_relative,stem,pairing_status) VALUES ('one','', 'one','jpeg_only')")
            connection.commit()
            connection.close()
            control = ServiceControl(config, 8765)
            started, release = Event(), Event()

            def slow_export(*args, **kwargs):
                started.set()
                if not release.wait(5):
                    raise RuntimeError('test export deadline')
                return {'filename': 'isolated.zip'}

            with (
                patch('tangerine_photo_assistant.webapp.write_photo_export', side_effect=slow_export),
                TestClient(create_app(config, service_control=control), base_url='http://127.0.0.1') as client,
                ThreadPoolExecutor(max_workers=3) as pool,
            ):
                session = client.get('/api/session').json()
                headers = {session['header']: session['token']}
                export = pool.submit(client.post, '/api/exports/photos', json={'capture_ids': [1]}, headers=headers)
                try:
                    self.assertTrue(started.wait(2))
                    review = pool.submit(client.put, '/api/reviews/1', json={'user_rating': 5}, headers=headers)
                    cancel = pool.submit(client.post, '/api/tasks/current/cancel', headers=headers)
                    self.assertEqual(cancel.result(timeout=2).status_code, 409)
                    self.assertEqual(review.result(timeout=2).status_code, 200)
                    for path, payload in (
                        ('/api/albums', {'name': 'new', 'category': '纪念'}),
                        ('/api/exports/photos', {'capture_ids': [1]}),
                        ('/api/scan', {'album_id': 1}),
                        ('/api/albums/1/archive/execute', {'plan_id': 'a' * 32, 'confirmation': 'confirm'}),
                        ('/api/human-data/restore', {'backup': {}, 'confirmation': 'confirm'}),
                        ('/api/migration/switch', {}),
                    ):
                        response = client.post(path, json=payload, headers=headers)
                        self.assertEqual(response.status_code, 409, response.text)
                        self.assertIn('正在导出', response.json()['detail'])
                    shutdown = client.post('/api/system/desktop/shutdown', headers={**headers, CONTROL_HEADER: control.token})
                    self.assertEqual(shutdown.status_code, 409)
                    self.assertFalse(control.draining)
                    self.assertEqual(client.put('/api/reviews/1', json={'user_rating': 1}).status_code, 403)
                    self.assertEqual(client.post('/api/tasks/current/cancel').status_code, 403)
                finally:
                    release.set()
                self.assertEqual(export.result(timeout=2).status_code, 201)
                self.assertEqual(client.post('/api/albums', json={'name': 'new', 'category': '纪念'}, headers=headers).status_code, 201)

    def test_export_failure_or_invalid_payload_releases_registration(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'photos').mkdir()
            config = root / 'config.toml'
            write_safe_config(config, root / 'photos', root / 'workspace', root / 'cache')
            with TestClient(create_app(config), base_url='http://127.0.0.1') as client:
                session = client.get('/api/session').json()
                headers = {session['header']: session['token']}
                self.assertEqual(client.post('/api/exports/photos', json={}, headers=headers).status_code, 422)
                with patch('tangerine_photo_assistant.webapp.write_photo_export', side_effect=ValueError('bad source')):
                    self.assertEqual(client.post('/api/exports/photos', json={'capture_ids': [1]}, headers=headers).status_code, 422)
                with (
                    patch('tangerine_photo_assistant.webapp.write_photo_export', side_effect=RuntimeError('unexpected failure')),
                    self.assertRaisesRegex(RuntimeError, 'unexpected failure'),
                ):
                    client.post('/api/exports/photos', json={'capture_ids': [1]}, headers=headers)
                self.assertEqual(client.post('/api/albums', json={'name': 'after failure', 'category': '纪念'}, headers=headers).status_code, 201)

    def test_paused_migration_does_not_allow_export_to_start(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'photos').mkdir()
            config = root / 'config.toml'
            write_safe_config(config, root / 'photos', root / 'workspace', root / 'cache')
            with TestClient(create_app(config), base_url='http://127.0.0.1') as client:
                session = client.get('/api/session').json()
                headers = {session['header']: session['token']}
                with (
                    patch('tangerine_photo_assistant.webapp.ScanTaskManager.snapshot', return_value={'status': 'paused', 'stage': 'migration-batch-paused'}),
                    patch('tangerine_photo_assistant.webapp.write_photo_export') as export,
                ):
                    response = client.post('/api/exports/photos', json={'capture_ids': [1]}, headers=headers)
                    self.assertEqual(response.status_code, 409)
                    export.assert_not_called()


if __name__ == '__main__':
    unittest.main()
