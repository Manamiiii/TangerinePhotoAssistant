import importlib.util
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi.testclient import TestClient

from tangerine_photo_assistant.app_paths import config_identity
from tangerine_photo_assistant.service_runtime import ServiceControl
from tangerine_photo_assistant.settings import write_safe_config
from tangerine_photo_assistant.webapp import create_app

spec = importlib.util.spec_from_file_location('desktop_delivery', Path(__file__).resolve().parents[1] / 'scripts/desktop_delivery.py')
delivery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(delivery)


class DesktopDeliveryTests(unittest.TestCase):
    def test_local_receipt_detects_changed_sources_and_pages(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            web = root / 'web'
            web.mkdir()
            (web / 'index.html').write_bytes(b'page')
            source = {'src/example.py': 'original'}
            receipt = {'format': 1, 'app_id': 'tangerine-photo-assistant',
                       'inputs': source, 'files': delivery.inventory(web)}
            with patch.object(delivery, 'inputs', return_value=source):
                self.assertTrue(delivery.verify_local(root, web, receipt))
                (web / 'index.html').write_bytes(b'stale page')
                self.assertFalse(delivery.verify_local(root, web, receipt))
                (web / 'index.html').write_bytes(b'page')
            with patch.object(delivery, 'inputs', return_value={'src/example.py': 'edited'}):
                self.assertFalse(delivery.verify_local(root, web, receipt))

    def test_running_service_checks_identity_revision_assets_and_instance(self):
        config = Path('synthetic.toml')
        identity = {'revision': 'reviewed-commit', 'version': '0.1.1', 'dirty': False}
        receipt = {'build': identity, 'files': {'index.html': delivery.digest(b'page'),
                                             'assets/lazy.js': delivery.digest(b'chunk')}}
        health = {'status': 'ok', 'mode': 'local-only', 'app_id': 'tangerine-photo-assistant',
                  'config_identity': config_identity(config), 'instance_id': 'one', 'build': identity}
        responses = {'/api/health': json.dumps(health).encode(),
                     '/api/tasks/current': b'{"status":"paused","private":"must not appear"}',
                     '/': b'page', '/assets/lazy.js': b'chunk'}
        report = delivery.inspect_service(8765, config, receipt, responses.__getitem__)
        self.assertTrue(report['updated'])
        self.assertEqual(report['task_status'], 'paused')
        self.assertNotIn('private', json.dumps(report))
        for modified in ({'revision': 'old'}, {'dirty': True}):
            responses['/api/health'] = json.dumps(health | {'build': identity | modified}).encode()
            self.assertFalse(delivery.inspect_service(8765, config, receipt, responses.__getitem__)['updated'])
        responses['/api/health'] = json.dumps(health).encode()
        responses['/assets/lazy.js'] = b'old chunk'
        self.assertFalse(delivery.inspect_service(8765, config, receipt, responses.__getitem__)['updated'])
        responses['/assets/lazy.js'] = b'chunk'
        calls = []

        def changed_instance(path):
            calls.append(path)
            if path == '/api/health' and len(calls) > 1:
                return json.dumps(health | {'instance_id': 'two'}).encode()
            return responses[path]

        self.assertFalse(delivery.inspect_service(8765, config, receipt, changed_instance)['updated'])
        responses['/api/health'] = json.dumps(health | {'config_identity': 'other'}).encode()
        calls.clear()

        def foreign(path):
            calls.append(path)
            return responses[path]

        self.assertEqual(delivery.inspect_service(8765, config, receipt, foreign)['state'], 'identity_unverified')
        self.assertEqual(calls, ['/api/health'])

    def test_audit_uses_real_static_routes_with_isolated_database(self):
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / 'config.toml'
            photos = root / 'empty-photos'
            photos.mkdir()
            write_safe_config(config, photos, root / 'workspace', root / 'cache')
            web = root / 'web'
            (web / 'assets').mkdir(parents=True)
            (web / 'index.html').write_bytes(b'<html>synthetic</html>')
            (web / 'assets/chunk.js').write_bytes(b'export default "synthetic";')
            identity = {'revision': 'isolated-build', 'version': '0.1.1', 'dirty': False}
            receipt = {'build': identity, 'files': delivery.inventory(web)}
            control = ServiceControl(config, 18765)
            with patch('tangerine_photo_assistant.service_runtime.build_info', return_value=identity), \
                    TestClient(create_app(config, web, control), base_url='http://127.0.0.1') as client:
                paths = []

                def get(path):
                    paths.append(path)
                    response = client.get(path)
                    response.raise_for_status()
                    return response.content

                self.assertTrue(delivery.inspect_service(18765, config, receipt, get)['updated'])
                self.assertEqual(set(paths), {'/api/health', '/api/tasks/current', '/', '/assets/chunk.js'})
