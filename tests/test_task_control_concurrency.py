import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from unittest.mock import patch

from fastapi.testclient import TestClient

from tangerine_photo_assistant.settings import write_safe_config
from tangerine_photo_assistant.webapp import create_app


class TaskControlConcurrencyTests(unittest.TestCase):
    def test_cancel_does_not_wait_for_slow_export_but_other_writes_do(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            photos = root / 'photos'
            photos.mkdir()
            config = root / 'config.toml'
            write_safe_config(config, photos, root / 'workspace', root / 'cache')
            started, release = Event(), Event()

            def slow_export(*args, **kwargs):
                started.set()
                if not release.wait(5):
                    raise RuntimeError('test export deadline')
                return {'filename': 'isolated.zip'}

            with (
                patch('tangerine_photo_assistant.webapp.write_photo_export', side_effect=slow_export),
                TestClient(create_app(config), base_url='http://127.0.0.1') as client,
                ThreadPoolExecutor(max_workers=3) as pool,
            ):
                session = client.get('/api/session').json()
                headers = {session['header']: session['token']}
                export = pool.submit(client.post, '/api/exports/photos', json={'capture_ids': [1]}, headers=headers)
                try:
                    self.assertTrue(started.wait(2))
                    other = pool.submit(client.post, '/api/albums', json={'name': 'new', 'category': '纪念'}, headers=headers)
                    cancel = pool.submit(client.post, '/api/tasks/current/cancel', headers=headers)
                    self.assertEqual(cancel.result(timeout=2).status_code, 409)
                    self.assertFalse(other.done())
                    self.assertEqual(client.post('/api/tasks/current/cancel').status_code, 403)
                finally:
                    release.set()
                self.assertEqual(export.result(timeout=2).status_code, 201)
                self.assertEqual(other.result(timeout=2).status_code, 201)


if __name__ == '__main__':
    unittest.main()
