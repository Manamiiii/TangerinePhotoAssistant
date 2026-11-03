"""Headless packaged-app and isolated NSIS lifecycle checks; never open native UI."""
import argparse
import hashlib
import json
import os
import socket
import subprocess
import tempfile
import time
import uuid
from contextlib import closing
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from compile_windows_setup import compile_setup
from PIL import Image

from tangerine_photo_assistant.desktop import ServiceClient
from tangerine_photo_assistant.settings import write_safe_config

OPENER = build_opener(ProxyHandler({}))


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], capture_output=True, timeout=300, check=False,
                          creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)


class Backend:
    def __init__(self, executable, config):
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        self.client = ServiceClient(config, port)
        assert self.client.health() is None and not self.client.port_open()
        self.process = subprocess.Popen([str(executable), '--backend', '--config', str(config),
                                         '--port', str(port)], creationflags=subprocess.CREATE_NO_WINDOW)
        for _ in range(120):
            if self.client.health():
                break
            assert self.process.poll() is None, 'Packaged backend exited before readiness'
            time.sleep(.5)
        else:
            raise RuntimeError('Packaged backend readiness timed out; no process was killed')
        assert self.get('/api/tasks/current')['status'] == 'idle'
        session = self.get('/api/session')
        self.headers = {session['header']: session['token'], 'Content-Type': 'application/json'}

    def raw(self, path, payload=None):
        request = Request(self.client.url + path, data=None if payload is None else json.dumps(payload).encode(),
                          headers=getattr(self, 'headers', {}))
        with OPENER.open(request, timeout=30) as response:
            return response.read()

    def get(self, path, payload=None):
        return json.loads(self.raw(path, payload))

    def task(self):
        for _ in range(120):
            state = self.get('/api/tasks/current')
            if state['status'] != 'running':
                assert state['status'] == 'complete', state
                return state['result']
            time.sleep(.25)
        raise RuntimeError('Temporary task timeout')

    def close(self):
        self.client.stop(lambda _: None)
        assert self.process.wait(timeout=35) == 0


def exercise(backend, root):
    assert b'<html' in backend.raw('/')
    assert backend.get('/api/library/captures')['count'] == 0
    card = root / 'SyntheticCard'
    card.mkdir()
    Image.new('RGB', (48, 32), 'orange').save(card / 'A.JPG')
    (card / 'A.xmp').write_bytes(b'<sidecar>fixture</sidecar>')
    (card / 'B.MOV').write_bytes(b'opaque video fixture; preserved without decoding')
    original = {p.name: p.read_bytes() for p in card.iterdir()}
    backend.get('/api/imports/check', {'source': str(card)})
    job = backend.task()['import_id']
    backend.get(f'/api/imports/{job}/start', {'confirmed': True, 'name': 'Fixture shoot', 'category': '日常'})
    album = backend.task()['album_id']
    capture = backend.get('/api/library/captures')['items'][0]
    assert backend.raw(capture['thumbnail_url']).startswith(b'\xff\xd8')
    assert backend.get(f'/api/albums/{album}/files')['count'] == 2
    plan = backend.get(f'/api/albums/{album}/archive/preview', {})
    backend.get(f'/api/albums/{album}/archive/execute',
                {'plan_id': plan['id'], 'confirmation': '归档 Fixture shoot'})
    backend.task()
    assert backend.get(f'/api/albums/{album}/archive/status')['inbox_count'] == 0
    assert original == {p.name: p.read_bytes() for p in card.iterdir()}
    exported = backend.get('/api/human-data/export', {})
    backup = backend.get(exported['download_url'])
    backend.get('/api/human-data/restore/preflight', backup)
    backend.get('/api/human-data/restore', {'backup': backup, 'confirmation': '恢复人工数据'})
    assert backend.get('/api/library/captures')['items'][0]['id'] == capture['id']
    return capture['id']


def check(bundle, report):
    import winreg

    from tangerine_photo_assistant.database import connect_readonly
    from tangerine_photo_assistant.settings import Settings

    results = []
    with tempfile.TemporaryDirectory(prefix='tangerine-installer-') as temporary:
        root = Path(temporary)
        previous = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = str(root / 'Profile')
        name = 'TangerinePhotoAssistantFixture-' + uuid.uuid4().hex[:12]
        key = '{' + str(uuid.uuid4()).upper() + '}'
        registry = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + key
        programs = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs' / name
        link = programs / (name + '.lnk')
        config = root / 'UserData/config.toml'
        config.parent.mkdir()
        (root / 'Inbox').mkdir()
        write_safe_config(config, root / 'Inbox', root / 'Workspace', root / 'Cache')
        try:
            executable = bundle / 'TangerinePhotoAssistant.exe'
            checked = run([executable, '--check', '--config', config, '--report', root / 'check.json'])
            assert checked.returncode == 0, checked.stderr
            results.append('packaged resources/config check')
            backend = Backend(executable, config)
            try:
                capture_id = exercise(backend, root)
            finally:
                backend.close()
            results.append('packaged import, JPG thumbnail, video/sidecar archive, JSON export/restore')
            install = root / 'Program'
            older, current = root / 'old.exe', root / 'current.exe'
            compile_setup(bundle, older, '0.0.9', name, key)
            compile_setup(bundle, current, '0.1.0', name, key)

            def active():
                state = json.loads((install / '.tangerine-install.json').read_text())
                return install / state['active'] / 'TangerinePhotoAssistant.exe'

            def setup(path, success=True):
                result = run([path, '/S', f'/D={install}'])
                assert (result.returncode == 0) == success, (result.returncode, result.stdout, result.stderr)

            def uninstall(success=True, normal=False):
                if normal:
                    result = run([install / 'Uninstall.exe', '/S'])
                    assert result.returncode == 0
                    for _ in range(120):
                        if not (install / 'Uninstall.exe').exists():
                            return
                        time.sleep(.5)
                    raise RuntimeError('Normal NSIS uninstaller did not finish')
                # NSIS normally relocates itself to TEMP. Do that explicitly so
                # the harness waits for the real uninstaller process/exit code.
                temporary_uninstaller = root / 'uninstall-fixture.exe'
                temporary_uninstaller.write_bytes((install / 'Uninstall.exe').read_bytes())
                result = run([temporary_uninstaller, '/S', f'_?={install}'])
                assert (result.returncode == 0) == success, result.returncode

            setup(older)
            assert link.is_file(), 'Start Menu shortcut missing'
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as reg:
                assert winreg.QueryValueEx(reg, 'DisplayVersion')[0] == '0.0.9'
                assert Path(winreg.QueryValueEx(reg, 'InstallLocation')[0]).samefile(install)
            sentinel = install / 'user-added.txt'
            sentinel.write_text('preserve me')
            backend = Backend(active(), config)
            try:
                assert backend.get('/api/library/captures')['items'][0]['id'] == capture_id
                setup(current, False)
                uninstall(False)
                assert backend.process.poll() is None
                assert backend.get('/api/health')['status'] == 'ok'
            finally:
                backend.close()
            results.append('running backend blocks Setup and uninstall without termination')
            setup(current)
            setup(older, False)
            backend = Backend(active(), config)
            try:
                assert backend.get('/api/library/captures')['items'][0]['id'] == capture_id
            finally:
                backend.close()
            data = Settings.load(config).database_path
            digest = hashlib.sha256(data.read_bytes()).hexdigest()
            uninstall()
            assert not link.exists()
            try:
                registration = winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY)
            except FileNotFoundError:
                pass
            else:
                registration.Close()
                raise AssertionError('Uninstall registration was not removed')
            assert hashlib.sha256(data.read_bytes()).hexdigest() == digest
            assert sentinel.read_text() == 'preserve me'
            setup(current)
            backend = Backend(active(), config)
            try:
                assert backend.get('/api/library/captures')['items'][0]['id'] == capture_id
            finally:
                backend.close()
            uninstall(normal=True)
            with closing(connect_readonly(data)) as connection:
                assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert not connection.execute('PRAGMA foreign_key_check').fetchall()
            results.append('fixture install, upgrade, downgrade rejection, data-preserving uninstall/reinstall')
        finally:
            # Only the unique fixture identity is cleaned; no formal application registration is touched.
            link.unlink(missing_ok=True)
            if programs.exists():
                programs.rmdir()
            try:
                winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, registry, winreg.KEY_WOW64_64KEY)
            except FileNotFoundError:
                pass
            if previous is None:
                os.environ.pop('LOCALAPPDATA', None)
            else:
                os.environ['LOCALAPPDATA'] = previous
    report.write_text(json.dumps({'passed': results, 'native_window': 'not tested',
                                  'formal_identity_install': 'not tested', 'clean_machine': 'not tested'}, indent=2))
    print(json.dumps(results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    arguments = parser.parse_args()
    check(arguments.bundle.resolve(), arguments.report.resolve())
