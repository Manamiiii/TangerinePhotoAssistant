"""Build source-launcher pages separately; audit disk and HTTP identity without starting services."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from urllib.request import ProxyHandler, Request, build_opener

import tangerine_photo_assistant
from tangerine_photo_assistant.app_paths import config_identity
from tangerine_photo_assistant.build_info import build_info

ROOT = Path(__file__).resolve().parents[1]
MAX_RESPONSE = 16 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def inventory(directory: Path) -> dict[str, str]:
    result = {}
    for path in sorted(directory.rglob('*')):
        if path.is_symlink() or path.is_junction():
            raise ValueError('Delivery inputs must not contain filesystem links')
        if path.is_file():
            result[path.relative_to(directory).as_posix()] = digest(path.read_bytes())
    return result


def inputs(root: Path) -> dict[str, str]:
    paths = list((root / 'src/tangerine_photo_assistant').rglob('*.py'))
    for folder in ('web/src', 'web/public'):
        paths.extend(p for p in (root / folder).rglob('*') if p.is_file())
    paths.extend(p for pattern in ('web/*.json', 'web/*.ts', 'web/*.html', 'web/.env*')
                 for p in root.glob(pattern) if p.is_file())
    paths.extend(root / name for name in (
        'pyproject.toml', 'requirements-tested.txt', 'LICENSE',
        'TangerinePhotoAssistant.vbs', 'start-photo-assistant.cmd', 'scripts/windows_launcher.ps1'))
    return {p.relative_to(root).as_posix(): digest(p.read_bytes()) for p in sorted(set(paths))}


def verify_local(root: Path, web: Path, receipt: dict) -> bool:
    return (receipt.get('format') == 1 and receipt.get('app_id') == 'tangerine-photo-assistant'
            and bool(receipt.get('files', {}).get('index.html'))
            and inputs(root) == receipt.get('inputs') and inventory(web) == receipt.get('files'))


def build(output: Path) -> None:
    output = output.resolve()
    if not output.is_relative_to(ROOT / 'runtime/desktop-delivery'):
        raise ValueError('Choose a new directory under runtime/desktop-delivery')
    output.mkdir(parents=True, exist_ok=False)
    before = inputs(ROOT)
    identity = build_info()
    # Vite writes only to this new directory, never the pages used by a service.
    subprocess.run(['npm.cmd' if os.name == 'nt' else 'npm', 'run', 'build', '--',
                    '--outDir', str(output / 'web')], cwd=ROOT / 'web', check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if inputs(ROOT) != before:
        raise ValueError('Sources changed during build; output is not ready for delivery')
    files = inventory(output / 'web')
    if 'index.html' not in files:
        raise ValueError('Build did not produce an entry page')
    receipt = {'format': 1, 'app_id': 'tangerine-photo-assistant', 'build': identity,
               'created_at': datetime.now(UTC).isoformat(), 'inputs': before, 'files': files}
    with (output / 'receipt.json').open('x', encoding='utf-8') as target:
        json.dump(receipt, target, indent=2)


def inspect_service(port: int, config: Path, receipt: dict, get) -> dict:
    """Only report public version and task status; never keep task payloads or tokens."""
    health = json.loads(get('/api/health'))
    if (health.get('status') != 'ok' or health.get('mode') != 'local-only'
            or health.get('app_id') != 'tangerine-photo-assistant'
            or health.get('config_identity') != config_identity(config)):
        return {'state': 'identity_unverified', 'updated': False}
    task = json.loads(get('/api/tasks/current'))
    live = health.get('build', {})
    expected = receipt['build']
    source_matches = (bool(live.get('revision')) and live.get('revision') == expected.get('revision')
                      and live.get('version') == expected.get('version')
                      and live.get('dirty') is False and expected.get('dirty') is False)
    files_match = True
    for name, checksum in receipt['files'].items():
        # The existing application serves only index and assets, not arbitrary paths.
        if name != 'index.html' and not name.startswith('assets/'):
            files_match = False
            continue
        if '..' in Path(name).parts or '\\' in name or name.startswith('/'):
            raise ValueError('Unsafe delivery resource path')
        path = '/' if name == 'index.html' else '/' + quote(name, safe='/')
        files_match = digest(get(path)) == checksum and files_match
    # Verify the process identity stayed stable while fetching resources.
    after = json.loads(get('/api/health'))
    stable = bool(health.get('instance_id')) and after.get('instance_id') == health['instance_id']
    return {'state': 'running', 'updated': source_matches and files_match and stable,
            'backend_build': {key: live[key] for key in ('version', 'revision', 'dirty', 'schema_version', 'built_at') if key in live},
            'page_files_match': files_match, 'instance_stable': stable,
            'task_status': task.get('status', 'unknown'), 'port': port}


def audit(web: Path, receipt_path: Path, config: Path, port: int) -> dict:
    if not 1024 <= port <= 65535:
        raise ValueError('Invalid port')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    module_matches = Path(tangerine_photo_assistant.__file__).resolve() == (
        ROOT / 'src/tangerine_photo_assistant/__init__.py').resolve()
    expected_python = ROOT / ('.venv/Scripts/python.exe' if os.name == 'nt' else '.venv/bin/python')
    interpreter_matches = Path(sys.executable).absolute() == expected_python.absolute()
    local = module_matches and interpreter_matches and verify_local(ROOT, web, receipt)
    result = {'disk_ready': local and receipt['build'].get('dirty') is False,
              'module_from_checkout': module_matches,
              'project_interpreter': interpreter_matches, 'source_now': build_info(),
              'page_build': receipt['build'], 'receipt_sha256': digest(receipt_path.read_bytes()),
              'index_sha256': receipt['files']['index.html']}
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=4):
            pass
    except ConnectionRefusedError:
        result['instance'] = {'state': 'not_running', 'updated': False}
        return result
    except OSError:
        result['instance'] = {'state': 'unreachable_unknown', 'updated': False}
        return result
    opener = build_opener(ProxyHandler({}))

    def get(path):
        request = Request(f'http://127.0.0.1:{port}{path}', headers={'Cache-Control': 'no-cache'})
        with opener.open(request, timeout=3) as response:
            content = response.read(MAX_RESPONSE + 1)
        if len(content) > MAX_RESPONSE:
            raise ValueError('Response too large')
        return content

    try:
        result['instance'] = inspect_service(port, config, receipt, get)
        result['instance']['updated'] = result['instance']['updated'] and local
    except Exception as exc:
        result['instance'] = {'state': 'unverified', 'updated': False, 'error_type': type(exc).__name__}
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    create = sub.add_parser('build')
    create.add_argument('--output', type=Path, required=True)
    check = sub.add_parser('audit')
    check.add_argument('--web-dir', type=Path, default=ROOT / 'web/dist')
    check.add_argument('--receipt', type=Path, required=True)
    check.add_argument('--config', type=Path, default=ROOT / 'config.toml')
    check.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.command == 'build':
        build(args.output)
        return 0
    result = audit(args.web_dir, args.receipt, args.config, args.port)
    print(json.dumps(result, indent=2))
    # Disk readiness never means a running instance has loaded the new version.
    return 0 if result['disk_ready'] and (
        result['instance']['state'] == 'not_running' or result['instance']['updated']) else 1


if __name__ == '__main__':
    raise SystemExit(main())
