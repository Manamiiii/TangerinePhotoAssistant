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

from check_windows_icons import verify_icons
from compile_windows_setup import compile_setup
from PIL import Image

from tangerine_photo_assistant.desktop import ServiceClient, prepare_default_config
from tangerine_photo_assistant.settings import write_safe_config

OPENER = build_opener(ProxyHandler({}))
FORMAL_NAME = 'TangerinePhotoAssistant'
FORMAL_KEY = '{551A03F7-2773-4A5E-962C-6BBDB8B28E08}'


def formal_locations():
    registry = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + FORMAL_KEY
    link = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs' / FORMAL_NAME / (FORMAL_NAME + '.lnk')
    return registry, link


def registration_exists(registry):
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY):
            return True
    except FileNotFoundError:
        return False


def check_formal_conflict(setup, report):
    """Exercise the shipped formal installer only when an existing shortcut protects it."""
    registry, link = formal_locations()
    if registration_exists(registry) or not link.is_file():
        raise RuntimeError('Conflict check requires an existing shortcut and no formal registration')
    before = link.read_bytes()
    with tempfile.TemporaryDirectory(prefix='tangerine-formal-conflict-') as directory:
        install = Path(directory) / 'NeverInstalled'
        result = run([setup, '/S', f'/D={install}'])
        assert result.returncode == 20, result.returncode
        assert not install.exists(), 'Refused Setup must not create the install root'
        assert not registration_exists(registry)
        assert link.read_bytes() == before, 'Existing shortcut changed'
    report.write_text(json.dumps({'formal_identity': 'existing shortcut conflict refused',
                                  'formal_lifecycle': 'not run on this account',
                                  'existing_shortcut_unchanged': True}, indent=2))


def run(command, **kwargs):
    return subprocess.run([str(x) for x in command], capture_output=True, timeout=300, check=False,
                          creationflags=subprocess.CREATE_NO_WINDOW, **kwargs)


def inspect_shortcut(link, executable, working_directory=None, arguments=''):
    command = ("[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TEST_LINK); "
               "@($s.TargetPath,$s.WorkingDirectory,$s.IconLocation,$s.Arguments) | ConvertTo-Json -Compress")
    result = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                 env={**os.environ, 'TEST_LINK': str(link)})
    assert result.returncode == 0
    target, cwd, icon, args = json.loads(result.stdout)
    image, index = icon.rsplit(',', 1)
    assert Path(target).samefile(executable) and Path(cwd).samefile(working_directory or executable.parent)
    assert Path(image).samefile(executable) and index.strip() == '0' and args == arguments


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


def check(bundle, report, formal_setup=None):
    import winreg

    from tangerine_photo_assistant.database import connect_readonly
    from tangerine_photo_assistant.settings import Settings

    results = []
    if formal_setup:
        registry, link = formal_locations()
        if os.environ.get('GITHUB_ACTIONS') != 'true':
            raise RuntimeError('Full formal-identity lifecycle is restricted to an ephemeral CI runner')
        if registration_exists(registry) or link.exists():
            raise RuntimeError('Formal identity already exists; no existing registration/shortcut is touched')
        standard = Path(os.environ['LOCALAPPDATA']) / 'Programs'
        expected_default = Path(os.environ['LOCALAPPDATA']) / 'Tangerine/Apps' / FORMAL_NAME
        if any(p.exists() for p in (expected_default, standard / FORMAL_NAME, standard / 'Tangerine' / FORMAL_NAME)):
            raise RuntimeError('CI program directory already exists; refusing formal default path test')
    with tempfile.TemporaryDirectory(prefix='tangerine-installer-') as temporary:
        root = Path(temporary)
        previous = os.environ.get('LOCALAPPDATA')
        os.environ['LOCALAPPDATA'] = str(root / 'Profile')
        name = 'TangerinePhotoAssistantFixture-' + uuid.uuid4().hex[:12]
        key = '{' + str(uuid.uuid4()).upper() + '}'
        if formal_setup:
            name, key = FORMAL_NAME, FORMAL_KEY
        registry = 'Software\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\' + key
        programs = Path(os.environ['APPDATA']) / 'Microsoft/Windows/Start Menu/Programs' / name
        link = programs / (name + '.lnk')
        config = root / 'UserData/config.toml'
        config.parent.mkdir()
        (root / 'Inbox').mkdir()
        write_safe_config(config, root / 'Inbox', root / 'Workspace', root / 'Cache')
        owned_link = None
        try:
            executable = bundle / 'TangerinePhotoAssistant.exe'
            default_config = prepare_default_config()
            assert default_config == root / 'Profile/Tangerine/Data/TangerinePhotoAssistant/Config/config.toml'
            default_backend = Backend(executable, default_config)
            try:
                assert default_backend.get('/api/health')['status'] == 'ok'
                assert Settings.load(default_config).database_path.is_file()
            finally:
                default_backend.close()
            data_root = default_config.parent.parent
            assert list((data_root / 'Logs').glob('*/service.log'))
            assert list((data_root / 'Runtime').glob('*/backend.lock'))
            results.append('packaged centralized default workspace, runtime and logs')
            checked = run([executable, '--check', '--config', config, '--report', root / 'check.json'])
            assert checked.returncode == 0, checked.stderr
            results.append('packaged resources/config check')
            backend = Backend(executable, config)
            try:
                capture_id = exercise(backend, root)
            finally:
                backend.close()
            results.append('packaged import, JPG thumbnail, video/sidecar archive, JSON export/restore')
            install = root / 'Programs' / name
            older, current = root / 'old.exe', root / 'current.exe'
            compile_setup(bundle, older, '0.0.9', name, key)
            if formal_setup:
                current = formal_setup
            else:
                compile_setup(bundle, current, '0.1.1', name, key)

            def active():
                state = json.loads((install / '.tangerine-install.json').read_text())
                return install / state['active'] / 'TangerinePhotoAssistant.exe'

            def setup(path, success=True, *, default=False):
                nonlocal owned_link
                result = run([path, '/S'] if default else [path, '/S', f'/D={install}'])
                assert (result.returncode == 0) == success, (result.returncode, result.stdout, result.stderr)
                if success:
                    owned_link = link.read_bytes()

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
            prior = active()
            launch_args = f'--config "{config}" --port 18765'
            custom = run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
                          ('$s=(New-Object -ComObject WScript.Shell).CreateShortcut($env:TEST_LINK); '
                           '$s.Arguments=$env:TEST_ARGS; $s.WorkingDirectory=$env:TEST_CWD; $s.Save()')],
                         env={**os.environ, 'TEST_LINK': str(link), 'TEST_ARGS': launch_args, 'TEST_CWD': str(root)})
            assert custom.returncode == 0
            owned_link = link.read_bytes()
            setup(current, default=True)
            assert active().is_file() and active() != prior, 'Legacy root was not upgraded in place'
            inspect_shortcut(link, active(), root, launch_args)
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
            install = expected_default if formal_setup else root / 'Tangerine/Apps' / name
            sibling = install.parent / ('sibling-' + uuid.uuid4().hex)
            sibling.mkdir(parents=True)
            marker = sibling / 'keep.txt'
            marker.write_bytes(b'other tool')
            setup(current, default=bool(formal_setup))
            inspect_shortcut(link, active())
            verify_icons(bundle, current, active(), install / 'Uninstall.exe')
            backend = Backend(active(), config)
            try:
                assert backend.get('/api/library/captures')['items'][0]['id'] == capture_id
            finally:
                backend.close()
            uninstall(normal=True)
            assert marker.read_bytes() == b'other tool'
            marker.unlink()
            sibling.rmdir()
            with closing(connect_readonly(data)) as connection:
                assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                assert not connection.execute('PRAGMA foreign_key_check').fetchall()
            results.append(('formal identity' if formal_setup else 'fixture') +
                           ' install, upgrade, downgrade rejection, data-preserving uninstall/reinstall')
        finally:
            # Identity was absent at entry (formal mode is CI-only). Preserve any unexpected replacement.
            if owned_link is not None and link.exists() and link.read_bytes() == owned_link:
                link.unlink()
            if programs.exists() and not any(programs.iterdir()):
                programs.rmdir()
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, registry, 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as reg:
                    owned = Path(winreg.QueryValueEx(reg, 'InstallLocation')[0]).resolve() == install.resolve()
                if owned:
                    winreg.DeleteKeyEx(winreg.HKEY_CURRENT_USER, registry, winreg.KEY_WOW64_64KEY)
            except FileNotFoundError:
                pass
            if previous is None:
                os.environ.pop('LOCALAPPDATA', None)
            else:
                os.environ['LOCALAPPDATA'] = previous
    report.write_text(json.dumps({'passed': results, 'native_window': 'not tested',
                                  'formal_identity_install': 'passed silently on CI' if formal_setup else 'not tested',
                                  'clean_machine': 'not tested'}, indent=2))
    print(json.dumps(results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', required=True, type=Path)
    parser.add_argument('--report', required=True, type=Path)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--formal-setup', type=Path, help='CI only: test the shipped formal Setup in an unused identity')
    mode.add_argument('--formal-conflict-setup', type=Path, help='Test refusal without replacing an existing shortcut')
    arguments = parser.parse_args()
    if arguments.formal_conflict_setup:
        check_formal_conflict(arguments.formal_conflict_setup.resolve(), arguments.report.resolve())
    else:
        check(arguments.bundle.resolve(), arguments.report.resolve(),
              arguments.formal_setup.resolve() if arguments.formal_setup else None)
