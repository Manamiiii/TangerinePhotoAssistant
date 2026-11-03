"""A new user's CLI setup and HTTP import/archive flow, without optional tools."""

import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from tangerine_photo_assistant.database import connect_readonly
from tangerine_photo_assistant.settings import Settings
from tangerine_photo_assistant.webapp import create_app


class FirstUseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'config.toml'
        self.photos = self.root / 'Photos'
        self.photos.mkdir()

    def cli(self, *arguments):
        environment = {**os.environ, 'PYTHONUTF8': '1',
                       'PYTHONPATH': str(Path(__file__).resolve().parents[1] / 'src')}
        return subprocess.run(
            [sys.executable, '-m', 'tangerine_photo_assistant', *arguments],
            cwd=self.root, env=environment, capture_output=True, encoding='utf-8', timeout=30, check=False,
        )

    def initialize(self):
        result = self.cli('init', '--config', str(self.config), '--photos', str(self.photos),
                          '--workspace', str(self.root / 'Workspace'),
                          '--cache', str(self.root / 'Cache'))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def wait_for_task(self, client):
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            state = client.get('/api/tasks/current').json()
            if state['status'] != 'running':
                self.assertEqual(state['status'], 'complete', state)
                return state
            time.sleep(.05)
        self.fail('Temporary import/archive worker did not finish')

    def test_init_does_not_overwrite_and_missing_fields_have_actionable_error(self):
        self.initialize()
        before = self.config.read_bytes()
        result = self.cli('init', '--config', str(self.config), '--photos', str(self.photos),
                          '--workspace', str(self.root / 'Other'), '--cache', str(self.root / 'Cache'))
        self.assertEqual(result.returncode, 1)
        self.assertEqual(self.config.read_bytes(), before)
        self.config.write_text('[library]\n', encoding='utf-8')
        result = self.cli('doctor', '--config', str(self.config))
        self.assertEqual(result.returncode, 1)
        self.assertIn('library.originals', result.stdout)
        self.assertIn('tangerine-photo init', result.stdout)
        self.assertNotIn('Traceback', result.stderr)

    def test_empty_setup_to_import_preview_and_archive_without_exiftool_or_model(self):
        self.initialize()
        checked = self.cli('doctor', '--config', str(self.config))
        self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
        settings = Settings.load(self.config)
        self.assertIsNone(settings.ai_model_path)
        card = self.root / 'Card'
        card.mkdir()
        Image.new('RGB', (24, 16), 'orange').save(card / 'A.JPG')
        (card / 'A.xmp').write_bytes(b'<sidecar>keep unchanged</sidecar>')
        (card / 'B.MOV').write_bytes(b'opaque video preserved, never decoded')
        original = {path.name: path.read_bytes() for path in card.iterdir()}

        with patch.object(Settings, 'find_exiftool', return_value=None), \
                TestClient(create_app(self.config), base_url='http://127.0.0.1') as client:
            self.assertEqual(client.get('/api/library/captures').json()['count'], 0)
            session = client.get('/api/session').json()
            headers = {session['header']: session['token']}
            checked = client.post('/api/imports/check', json={'source': str(card)}, headers=headers)
            self.assertEqual(checked.status_code, 202, checked.text)
            job_id = self.wait_for_task(client)['result']['import_id']
            self.assertEqual(list(self.photos.iterdir()), [])
            response = client.post(f'/api/imports/{job_id}/start', headers=headers,
                                   json={'confirmed': True, 'name': 'First shoot', 'category': '日常'})
            self.assertEqual(response.status_code, 202, response.text)
            album_id = self.wait_for_task(client)['result']['album_id']
            library = client.get('/api/library/captures').json()
            self.assertEqual(library['count'], 1)
            thumbnail = client.get(library['items'][0]['thumbnail_url'])
            self.assertEqual(thumbnail.status_code, 200)
            self.assertEqual(thumbnail.headers['content-type'], 'image/jpeg')
            self.assertEqual(client.get(f'/api/albums/{album_id}/files').json()['count'], 2)
            response = client.post(f'/api/albums/{album_id}/archive/preview', headers=headers)
            self.assertEqual(response.status_code, 200, response.text)
            plan = response.json()
            response = client.post(f'/api/albums/{album_id}/archive/execute', headers=headers,
                                   json={'plan_id': plan['id'], 'confirmation': '归档 First shoot'})
            self.assertEqual(response.status_code, 202, response.text)
            self.wait_for_task(client)
            self.assertEqual(client.get(f'/api/albums/{album_id}/archive/status').json()['inbox_count'], 0)
            self.assertEqual(client.get('/api/imports').json()['items'][0]['remaining_files'], 0)
            self.assertEqual(client.get('/api/library/captures').json()['items'][0]['id'], library['items'][0]['id'])
            for item in plan['items']:
                self.assertFalse(Path(item['source']).exists())
                self.assertEqual(Path(item['target']).read_bytes(), original[Path(item['target']).name])

        self.assertEqual(original, {path.name: path.read_bytes() for path in card.iterdir()})
        connection = connect_readonly(settings.database_path)
        try:
            self.assertEqual(connection.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
            self.assertEqual(connection.execute('PRAGMA foreign_key_check').fetchall(), [])
        finally:
            connection.close()
