"""Explicit, recoverable inbox-to-album filing. Never operates on the frozen archive."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any
from uuid import uuid4

from .database import connect_readonly, transaction
from .migration import _safe_component, _year
from .settings import Settings


def _directory(settings: Settings) -> Path:
    return settings.workspace.absolute() / "AlbumArchive"


def _save(settings: Settings, plan: dict[str, Any]) -> None:
    folder = _directory(settings)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{plan['id']}.json"
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as out:
        json.dump(plan, out, ensure_ascii=False, indent=2)
        out.flush()
        os.fsync(out.fileno())
    temporary.replace(path)


def load(settings: Settings, plan_id: str) -> dict[str, Any]:
    if len(plan_id) != 32 or any(c not in '0123456789abcdef' for c in plan_id):
        raise ValueError('归档计划编号无效')
    return json.loads((_directory(settings) / f'{plan_id}.json').read_text(encoding='utf-8'))


def pending(settings: Settings) -> dict[str, Any] | None:
    for path in sorted(_directory(settings).glob('*.json')):
        plan = json.loads(path.read_text(encoding='utf-8'))
        if plan['status'] == 'pending':
            return plan
    return None


def _plain(path: Path, root: Path) -> None:
    """Reject links/junctions at every level, including the configured root."""
    if '..' in path.parts or not path.is_relative_to(root) or path == root:
        raise ValueError('归档路径越界')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('归档不支持符号链接或目录联接')


def _root(connection: sqlite3.Connection, settings: Settings) -> Path:
    root = settings.originals.absolute()
    state = connection.execute('SELECT * FROM library_state WHERE id=1').fetchone()
    if state and (root != Path(state['active_root']).absolute()
                  or root == Path(state['archive_root']).absolute()):
        raise ValueError('只能归档当前活动图库，不能操作历史原始档案')
    if str(root).replace('\\', '/').casefold().rstrip('/') == 'd:/photo':
        raise ValueError('不能操作历史原始档案')
    _plain(root / '待整理', root)
    return root


def _snapshot(connection: sqlite3.Connection, settings: Settings, album_id: int) -> dict:
    root = _root(connection, settings)
    album = connection.execute('SELECT * FROM events WHERE id=?', (album_id,)).fetchone()
    if album is None:
        raise ValueError('相册不存在')
    rows = connection.execute('''SELECT f.*, cf.capture_id FROM files f
        JOIN capture_files cf ON cf.file_id=f.id
        JOIN event_captures ec ON ec.capture_id=cf.capture_id
        WHERE ec.event_id=? ORDER BY f.id''', (album_id,)).fetchall()
    if not rows:
        raise ValueError('相册没有可归档照片')
    destination = root / _safe_component(album['category']) / _year(album['start_at']) / _safe_component(album['proposed_name'])
    _plain(destination, root)
    if destination.is_relative_to(root / '待整理'):
        raise ValueError('正式归档类型不能为待整理')
    items = []
    names: set[str] = set()
    for row in rows:
        source = Path(row['path']).absolute()
        if not source.is_relative_to(root / '待整理'):
            raise ValueError('本相册含已在正式目录的照片；仅支持全部照片仍在待整理的相册')
        _plain(source, root / '待整理')
        if not row['present'] or not source.is_file():
            raise ValueError('照片缺失，或相册含已归档照片；请先核对来源')
        stat = source.stat()
        if (stat.st_size, stat.st_mtime_ns) != (row['size_bytes'], row['modified_ns']):
            raise ValueError('照片自上次扫描后发生变化，请先更新图库')
        target = destination / source.name
        _plain(target, root)
        if target.exists() or source.name.casefold() in names:
            raise ValueError('目标有同名文件或组内文件名重复；不会覆盖或合并')
        names.add(source.name.casefold())
        if connection.execute('SELECT 1 FROM files WHERE path=? COLLATE NOCASE', (str(target),)).fetchone():
            raise ValueError('目标路径已有图库记录')
        items.append({'file_id': row['id'], 'capture_id': row['capture_id'],
                      'source': str(source), 'target': str(target),
                      'bytes': stat.st_size, 'mtime': stat.st_mtime_ns})
    return {'album_id': album_id, 'album_name': album['proposed_name'],
            'root': str(root), 'target': str(destination), 'items': items,
            'capture_count': len({r['capture_id'] for r in items}),
            'total_bytes': sum(r['bytes'] for r in items)}


def preview(connection: sqlite3.Connection, settings: Settings, album_id: int) -> dict:
    active = pending(settings)
    if active:
        if active['album_id'] != album_id:
            raise ValueError('请先继续处理另一相册未完成的归档')
        return active
    snapshot = _snapshot(connection, settings, album_id)
    if shutil.disk_usage(settings.originals).free < snapshot['total_bytes']:
        raise ValueError('活动图库空闲空间不足以保留校验副本')
    plan = {**snapshot, 'id': uuid4().hex, 'status': 'preview', 'error': None}
    _save(settings, plan)
    return plan


def prepare(connection: sqlite3.Connection, settings: Settings, plan_id: str, confirmation: str) -> dict:
    plan = load(settings, plan_id)
    if confirmation != f"归档 {plan['album_name']}":
        raise ValueError('请完整输入归档确认文字')
    active = pending(settings)
    if active and active['id'] != plan_id:
        raise ValueError('已有未完成的归档')
    if plan['status'] == 'complete':
        raise ValueError('该归档已完成')
    if plan['status'] == 'preview':
        snapshot = _snapshot(connection, settings, plan['album_id'])
        if any(plan[k] != v for k, v in snapshot.items()):
            raise ValueError('预览已经过期，请重新预览')
    plan['status'] = 'pending'
    _save(settings, plan)
    return plan


def _hash(path: Path) -> str:
    with path.open('rb') as inp:
        return hashlib.file_digest(inp, 'sha256').hexdigest()


def _backup(settings: Settings, plan: dict) -> None:
    path = _directory(settings) / f"{plan['id']}.sqlite3"
    if path.exists():
        with closing(sqlite3.connect(f'{path.as_uri()}?mode=ro', uri=True)) as db:
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('归档前备份不可用')
        return
    temporary = path.with_name(f'{path.name}.{uuid4().hex}.backup-part')
    with closing(connect_readonly(settings.database_path)) as source, closing(sqlite3.connect(temporary)) as target:
        source.backup(target)
        if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or target.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('归档前备份校验失败')
    temporary.rename(path)


def execute(connection: sqlite3.Connection, settings: Settings, plan: dict,
            progress: Callable[[int, int, str], None]) -> dict:
    root = _root(connection, settings)
    if str(root) != plan['root']:
        raise ValueError('活动图库已改变')
    _backup(settings, plan)
    items = plan['items']
    for index, item in enumerate(items):
        source, target = Path(item['source']), Path(item['target'])
        _plain(source, root / '待整理')
        _plain(target, root)
        if target.is_relative_to(root / '待整理'):
            raise ValueError('归档目标不能在待整理内')
        recorded = connection.execute('SELECT path FROM files WHERE id=?', (item['file_id'],)).fetchone()
        if recorded is None or recorded['path'] not in (str(source), str(target)):
            raise ValueError('图库记录与归档计划不一致')
        if 'sha256' not in item:
            stat = source.stat()
            if (stat.st_size, stat.st_mtime_ns) != (item['bytes'], item['mtime']):
                raise ValueError('源文件变化，已停止归档')
            item['sha256'] = _hash(source)
            _save(settings, plan)
        if target.exists():
            if not item.get('publishing') or _hash(target) != item['sha256']:
                raise ValueError('目标冲突或校验失败；未覆盖文件')
        else:
            if recorded['path'] == str(target):
                raise ValueError('已切换的目标丢失，请先恢复目标副本')
            if _hash(source) != item['sha256']:
                raise ValueError('源文件变化，已停止归档')
            target.parent.mkdir(parents=True, exist_ok=True)
            _plain(target, root)
            temporary = target.with_name(f'.{target.name}.tangerine-part-{plan["id"]}')
            _plain(temporary, root)
            # Only the exclusively named, journal-owned partial file may be retried.
            if temporary.exists():
                if not item.get('temporary_created') or temporary.stat().st_nlink != 1:
                    raise ValueError('临时文件不属于可恢复的归档副本')
                temporary.unlink()
            item['temporary_created'] = True
            _save(settings, plan)
            with source.open('rb') as inp, temporary.open('xb') as out:
                shutil.copyfileobj(inp, out, 4 * 1024 * 1024)
                out.flush()
                os.fsync(out.fileno())
            if _hash(temporary) != item['sha256'] or _hash(source) != item['sha256']:
                raise ValueError('复制校验失败，源文件保持原位')
            os.utime(temporary, ns=(source.stat().st_atime_ns, item['mtime']))
            item['publishing'] = True
            _save(settings, plan)
            if os.name == 'nt':
                temporary.rename(target)  # Windows refuses an existing destination.
            else:
                os.link(temporary, target)  # Exclusive publication; no POSIX overwrite.
                temporary.unlink()
        progress(index + 1, len(items), '复制校验')

    # All targets must be good before any index change or source cleanup.
    progress(0, len(items), '提交前复核')
    for index, item in enumerate(items):
        _plain(Path(item['target']), root)
        _plain(Path(item['source']), root / '待整理')
        if _hash(Path(item['target'])) != item['sha256']:
            raise ValueError('提交前目标校验失败')
        if Path(item['source']).exists() and _hash(Path(item['source'])) != item['sha256']:
            raise ValueError('提交前源文件变化')
        progress(index + 1, len(items), '提交前复核')
    progress(0, 1, '更新图库路径')
    with transaction(connection):
        for item in items:
            target = Path(item['target'])
            relative = target.relative_to(root)
            connection.execute('UPDATE files SET path=?, relative_path=?, parent_relative=?, modified_ns=? WHERE id=?',
                               (str(target), str(relative), str(relative.parent), target.stat().st_mtime_ns, item['file_id']))
        for capture_id in {i['capture_id'] for i in items}:
            row = connection.execute('''SELECT f.parent_relative, f.stem FROM files f
                JOIN capture_files cf ON cf.file_id=f.id WHERE cf.capture_id=? LIMIT 1''', (capture_id,)).fetchone()
            connection.execute('UPDATE captures SET parent_relative=?, capture_key=? WHERE id=?',
                               (row['parent_relative'], f"{row['parent_relative'].casefold()}/{row['stem'].casefold()}", capture_id))
        connection.execute('DELETE FROM event_sources WHERE event_id=?', (plan['album_id'],))
        connection.execute('''INSERT INTO event_sources(event_id,parent_relative)
            SELECT ?,c.parent_relative FROM captures c JOIN event_captures ec ON ec.capture_id=c.id
            WHERE ec.event_id=? GROUP BY c.parent_relative''', (plan['album_id'], plan['album_id']))
    progress(1, 1, '更新图库路径')
    progress(0, len(items), '清理待整理源文件')
    for index, item in enumerate(items):
        source, target = Path(item['source']), Path(item['target'])
        _plain(source, root / '待整理')
        _plain(target, root)
        if source.exists():
            if _hash(source) != item['sha256'] or _hash(target) != item['sha256']:
                raise ValueError('清理前校验失败；待整理源文件已保留')
            source.unlink()
        parent = source.parent
        while parent != root / '待整理':
            try:
                parent.rmdir()  # Empty folders only; unrelated files always remain.
            except OSError:
                break
            parent = parent.parent
        progress(index + 1, len(items), '清理待整理源文件')
    plan['status'] = 'complete'
    plan['error'] = None
    _save(settings, plan)
    return {'album_id': plan['album_id'], 'archived_count': plan['capture_count']}
