"""Durable, scoped imports. Sources are read-only; only owned copies are published."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
from collections import defaultdict
from pathlib import Path
from uuid import uuid4

from .album_archive import _backup, _directory, _plain, _root
from .albums import assign_captures_to_album
from .database import transaction
from .inventory import IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, enrich_metadata, media_kind, utc_now
from .metadata import ExifToolMetadataReader, PillowMetadataReader
from .pairing import rebuild_captures
from .settings import Settings
from .structure import rebuild_structure

SIDECARS = {'.xmp', '.lrf', '.aae', '.thm', '.srt', '.wav'}
ACTIVE = {'checking', 'copying', 'indexing'}


def save(db: sqlite3.Connection, job: dict) -> None:
    job['updated_at'] = utc_now()
    db.execute('''INSERT INTO import_jobs VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
        state=excluded.state,updated_at=excluded.updated_at,data_json=excluded.data_json''',
        (job['id'], job['state'], job['created_at'], job['updated_at'], json.dumps(job, ensure_ascii=False)))
    db.commit()


def load(db: sqlite3.Connection, job_id: str) -> dict:
    row = db.execute('SELECT data_json FROM import_jobs WHERE id=?', (job_id,)).fetchone()
    if row is None:
        raise ValueError('导入批次不存在')
    return json.loads(row[0])


def active(db: sqlite3.Connection) -> dict | None:
    rows = db.execute("SELECT data_json FROM import_jobs WHERE state IN ('checking','copying','indexing')").fetchall()
    if len(rows) > 1:
        raise ValueError('存在多个未完成导入，请先核对记录')
    return json.loads(rows[0][0]) if rows else None


def plain(path: Path) -> None:
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('请输入完整本地目录路径')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('导入不支持符号链接或目录联接')


def source_path(settings: Settings, value: str) -> tuple[Path, bool]:
    path = Path(value)
    plain(path)
    path = path.resolve(strict=True)
    root = settings.originals.resolve()
    in_place = path.is_relative_to(root / '待整理')
    if root.is_relative_to(path) or (path.is_relative_to(root) and not in_place):
        raise ValueError('请选择存储卡来源或待整理中的单个批次目录，不要选择正式图库')
    if path == root / '待整理':
        raise ValueError('请选择待整理中的单个批次目录，避免混入其他活动')
    for protected in (settings.workspace, settings.cache_root):
        if not in_place and (path.is_relative_to(protected.resolve()) or protected.resolve().is_relative_to(path)):
            raise ValueError('不能将程序工作区或缓存作为来源')
    if not path.is_dir():
        raise ValueError('来源目录不存在或存储卡未连接')
    return path, in_place


def new_job(db: sqlite3.Connection, settings: Settings, source: str) -> dict:
    _root(db, settings)
    path, in_place = source_path(settings, source)
    if active(db):
        raise ValueError('请先继续未完成的导入')
    job = {'id': uuid4().hex, 'state': 'checking', 'created_at': utc_now(),
           'root': str(settings.originals.absolute()), 'source': str(path), 'in_place': in_place,
           'items': [], 'ignored': [], 'error': None, 'album_id': None}
    save(db, job)
    return job


def digest(path: Path, progress=lambda _: None) -> str:
    plain(path)
    h = hashlib.sha256()
    with path.open('rb') as inp:
        while block := inp.read(4 * 1024 * 1024):
            h.update(block)
            progress(len(block))
    return h.hexdigest()


def inspect(db: sqlite3.Connection, settings: Settings, job: dict, progress) -> None:
    source, _ = source_path(settings, job['source'])
    items, ignored = [], []
    allowed = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS | set(settings.raw_extensions) | SIDECARS
    for directory, dirs, names in os.walk(source, followlinks=False, onerror=lambda error: (_ for _ in ()).throw(error)):
        for name in dirs + names:
            plain(Path(directory) / name)
        for name in names:
            path = Path(directory) / name
            relative = str(path.relative_to(source))
            if path.suffix.lower() not in allowed:
                ignored.append(relative)
                continue
            stat = path.stat()
            if not path.is_file() or stat.st_size == 0:
                raise ValueError(f'文件为空或不可读：{relative}')
            items.append({'source': str(path), 'relative': relative, 'bytes': stat.st_size,
                          'mtime': stat.st_mtime_ns, 'kind': media_kind(path.suffix.lower(), settings.raw_extensions)})
            if len(items) > 10000:
                raise ValueError('单次导入最多 10000 个文件，请拆分来源目录')
    if not items:
        raise ValueError('没有支持的照片、视频或附属文件')
    items.sort(key=lambda item: item['relative'].casefold())
    paths = [i['relative'].casefold() for i in items]
    if len(set(paths)) != len(paths):
        raise ValueError('来源含大小写冲突的同名路径')
    done, total = 0, sum(i['bytes'] for i in items)
    cache = {}
    for index, item in enumerate(items):
        if job['in_place'] and db.execute('''SELECT 1 FROM files f WHERE f.path=? AND (
            EXISTS(SELECT 1 FROM capture_files cf WHERE cf.file_id=f.id) OR
            EXISTS(SELECT 1 FROM album_files af WHERE af.file_id=f.id))''', (item['source'],)).fetchone():
            raise ValueError('待整理批次已有入库照片或已关联文件；请从对应相册归档')
        def tick(size, index=index):
            nonlocal done
            done += size
            progress(index, len(items), '检查内容与重复', done, total)
        item['sha256'] = digest(Path(item['source']), tick)
        item['duplicate_path'] = None
        candidates = db.execute('''SELECT path FROM files f WHERE present=1 AND size_bytes=? AND (
            REPLACE(relative_path,char(92),'/') NOT LIKE '待整理/%'
            OR EXISTS(SELECT 1 FROM album_files af WHERE af.file_id=f.id)
            OR EXISTS(SELECT 1 FROM capture_files cf JOIN event_captures ec ON ec.capture_id=cf.capture_id
                      WHERE cf.file_id=f.id))''', (item['bytes'],)).fetchall()
        for row in candidates:
            candidate = Path(row['path'])
            if candidate == Path(item['source']) and job['in_place']:
                continue
            if not candidate.is_file():
                continue
            if str(candidate) not in cache:
                cache[str(candidate)] = digest(candidate)
            if cache[str(candidate)] == item['sha256']:
                item['duplicate_path'] = str(candidate)
                break
        stat = Path(item['source']).stat()
        if (stat.st_size, stat.st_mtime_ns) != (item['bytes'], item['mtime']):
            raise ValueError('来源在检查期间发生变化，请重新检查')
    # Never split a JPG/RAW/sidecar family merely because one member already exists.
    families = defaultdict(list)
    for item in items:
        path = Path(item['relative'])
        stem = Path(path.stem)
        family_stem = stem.stem if path.suffix.lower() in SIDECARS and stem.suffix.lower() in allowed - SIDECARS else path.stem
        families[(str(path.parent).casefold(), family_stem.casefold())].append(item)
    for family in families.values():
        skip = all(i['duplicate_path'] for i in family)
        for item in family:
            item['skip'] = skip
    job.update(state='preview', items=items, ignored=ignored, error=None,
               total_bytes=total, duplicate_count=sum(i['skip'] for i in items))
    save(db, job)
    progress(len(items), len(items), '来源检查完成', total, total)


def prepare(db: sqlite3.Connection, settings: Settings, job: dict,
            album_id: int | None, name: str, category: str) -> None:
    if job['state'] != 'preview':
        raise ValueError('请先完成来源检查')
    if not any(not i['skip'] for i in job['items']):
        raise ValueError('全部文件均已入库，无需再次导入')
    if job['root'] != str(_root(db, settings)):
        raise ValueError('活动图库已改变，请重新检查')
    if shutil.disk_usage(settings.originals).free < sum(i['bytes'] for i in job['items'] if not i['skip']) * 2:
        raise ValueError('空间不足，需预留导入和归档副本空间')
    # Reuse the existing verified backup facility; import ids cannot collide with archive plans.
    _directory(settings).mkdir(parents=True, exist_ok=True)
    _backup(settings, job)
    with transaction(db):
        if album_id is None:
            if not name.strip() or not db.execute('SELECT 1 FROM album_types WHERE name=?', (category,)).fetchone():
                raise ValueError('请填写相册名称并选择有效类型')
            album_id = db.execute('''INSERT INTO events(event_key,proposed_name,category,capture_count,
                status,confidence,reason_json,created_at,updated_at) VALUES(?,?,?,0,'confirmed',1,?,?,?)''',
                (f'manual-album:import-{job["id"]}', name.strip(), category,
                 json.dumps({'method':'manual-import'}), utc_now(), utc_now())).lastrowid
        album = db.execute('SELECT proposed_name FROM events WHERE id=? AND status!=?', (album_id, 'archived')).fetchone()
        if album is None:
            raise ValueError('目标相册不存在')
        job.update(album_id=album_id, album_name=album[0], state='copying', error=None)
        job['destination'] = job['source'] if job['in_place'] else str(settings.originals / '待整理' / f'导入-{job["id"]}')
        job['capture_ids_before'] = [r[0] for r in db.execute('SELECT id FROM captures')]
        for item in job['items']:
            item['target'] = str(Path(job['destination']) / item['relative'])
            # Keep camera numbering from separate batches from colliding at archive time.
            item['archive_relative'] = str(Path(f'导入-{job["id"][:12]}') / item['relative'])
        db.execute('UPDATE import_jobs SET state=?,data_json=?,updated_at=? WHERE id=?',
                   (job['state'], json.dumps(job, ensure_ascii=False), utc_now(), job['id']))


def copy_files(db: sqlite3.Connection, settings: Settings, job: dict, progress) -> None:
    if job['root'] != str(_root(db, settings)):
        raise ValueError('活动图库已改变')
    source_path(settings, job['source'])
    total = sum(i['bytes'] for i in job['items'] if not i['skip'])
    done = 0
    for index, item in enumerate(job['items']):
        source = Path(item['source'])
        stat = source.stat()
        if (stat.st_size, stat.st_mtime_ns) != (item['bytes'], item['mtime']):
            raise ValueError(f'来源已变化：{item["relative"]}；保留已复制文件')
        if digest(source) != item['sha256']:
            raise ValueError('来源内容变化，请保留资料并重新核对')
        if item['skip']:
            if digest(Path(item['duplicate_path'])) != item['sha256']:
                raise ValueError('已入库重复副本发生变化，不能跳过')
            continue
        target = Path(item['target'])
        _plain(target, settings.originals / '待整理')
        if target.exists():
            if not (job['in_place'] or item.get('publishing')) or digest(target) != item['sha256']:
                raise ValueError('目标冲突，未覆盖文件')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            _plain(target, settings.originals / '待整理')
            temporary = target.with_name(f'.{target.name}.import-{job["id"]}.part')
            plain(temporary)
            if temporary.exists():
                if not item.get('temporary_created') or temporary.stat().st_nlink != 1:
                    raise ValueError('临时文件不属于此批次')
                temporary.unlink()
            item['temporary_created'] = True
            save(db, job)
            h = hashlib.sha256()
            copied = 0
            with source.open('rb') as inp, temporary.open('xb') as out:
                while block := inp.read(4 * 1024 * 1024):
                    out.write(block)
                    h.update(block)
                    copied += len(block)
                    progress(index, len(job['items']), '复制到待整理', done + copied, total)
                out.flush()
                os.fsync(out.fileno())
            if h.hexdigest() != item['sha256'] or digest(temporary) != item['sha256']:
                raise ValueError('复制校验失败；原片保留')
            os.utime(temporary, ns=(stat.st_atime_ns, item['mtime']))
            item['publishing'] = True
            save(db, job)
            if os.name == 'nt':
                temporary.rename(target)
            else:
                os.link(temporary, target)
                temporary.unlink()
        done += item['bytes']
        progress(index + 1, len(job['items']), '复制校验', done, total)
    job['state'] = 'indexing'
    save(db, job)


def index_files(db: sqlite3.Connection, settings: Settings, job: dict, progress) -> None:
    # Scope indexing to the manifest: never mark unrelated files absent or import another batch.
    root = _root(db, settings)
    paths = [i for i in job['items'] if not i['skip']]
    file_ids = set()
    with transaction(db):
        run = db.execute("INSERT INTO scan_runs(started_at,root_path,status) VALUES (?,?,'running')",
                         (utc_now(), job['destination'])).lastrowid
        for item in paths:
            path = Path(item['target'])
            _plain(path, root / '待整理')
            if digest(path) != item['sha256']:
                raise ValueError('入库前目标校验失败')
            relative = path.relative_to(root)
            stat = path.stat()
            existing = db.execute('SELECT id FROM files WHERE path=?', (str(path),)).fetchone()
            if existing is None:
                db.execute('''INSERT INTO files(path,relative_path,parent_relative,file_name,stem,extension,
                    media_kind,size_bytes,modified_ns,first_seen_run_id,last_seen_run_id,metadata_status)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''', (str(path), str(relative), str(relative.parent), path.name,
                    path.stem, path.suffix.lower(), item['kind'], stat.st_size, stat.st_mtime_ns, run, run,
                    'not_applicable' if item['kind']=='other' else 'pending'))
            else:
                db.execute('''UPDATE files SET present=1,last_seen_run_id=?,size_bytes=?,modified_ns=?,
                    metadata_status=CASE WHEN size_bytes!=? OR modified_ns!=? THEN ? ELSE metadata_status END
                    WHERE id=?''', (run, stat.st_size, stat.st_mtime_ns, stat.st_size, stat.st_mtime_ns,
                    'not_applicable' if item['kind']=='other' else 'pending', existing[0]))
            file_id = db.execute('SELECT id FROM files WHERE path=?', (str(path),)).fetchone()[0]
            file_ids.add(file_id)
            item['file_id'] = file_id
            owner = db.execute('SELECT event_id FROM album_files WHERE file_id=?', (file_id,)).fetchone()
            if owner and owner[0] != job['album_id']:
                raise ValueError('文件已关联其他相册，请先核对归属')
            db.execute('INSERT INTO album_files VALUES (?,?,?) ON CONFLICT(file_id) DO NOTHING',
                       (file_id, job['album_id'], item['archive_relative']))
        db.execute("UPDATE scan_runs SET status='complete',finished_at=?,files_seen=? WHERE id=?",
                   (utc_now(), len(paths), run))
    progress(0, len(paths), '读取拍摄参数', 0, 0)
    tool = settings.find_exiftool()
    reader = ExifToolMetadataReader(tool, settings.metadata_batch_size) if tool else PillowMetadataReader()
    enrich_metadata(db, settings, reader, lambda n,t: progress(n,t,'读取拍摄参数',0,0), file_ids=file_ids)
    rebuild_captures(db)
    old = set(job['capture_ids_before'])
    captures = {r[0] for r in db.execute('SELECT capture_id,file_id FROM capture_files') if r[1] in file_ids and r[0] not in old}
    if captures:
        assign_captures_to_album(db, job['album_id'], list(captures))
    rebuild_structure(db, settings.burst_time_gap_seconds)
    with transaction(db):
        db.execute('''INSERT OR IGNORE INTO event_sources(event_id,parent_relative)
            SELECT af.event_id,f.parent_relative FROM album_files af JOIN files f ON f.id=af.file_id
            WHERE af.event_id=?''', (job['album_id'],))
    job.update(state='ready', error=None, capture_count=len(captures), file_count=len(paths),
               metadata_errors=sum(1 for r in db.execute("SELECT id FROM files WHERE metadata_status='error'") if r[0] in file_ids))
    save(db, job)


def summary(job: dict) -> dict:
    result = {k: v for k,v in job.items() if k not in {'items', 'capture_ids_before', 'ignored'}}
    result['file_count'] = len(job['items'])
    result['ignored_count'] = len(job.get('ignored', []))
    result['counts'] = {kind: sum(i['kind']==kind for i in job['items']) for kind in ('image','raw','video','other')}
    result['copy_count'] = sum(not i.get('skip',False) for i in job['items'])
    return result
