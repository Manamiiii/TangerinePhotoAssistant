import json
from contextlib import closing

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import ingest
from .database import connect_readonly


class ImportCheck(BaseModel):
    source: str = Field(min_length=1, max_length=2048)


class ImportStart(BaseModel):
    album_id: int | None = Field(default=None, ge=1)
    name: str = Field(default='', max_length=180)
    category: str = Field(default='日常', max_length=40)
    confirmed: bool = False


def create_import_router(get_settings, manager):
    router = APIRouter()

    @router.get('/api/albums/{album_id}/files')
    def album_files(album_id: int, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        with closing(connect_readonly(get_settings().database_path)) as db:
            where = '''FROM album_files af JOIN files f ON f.id=af.file_id WHERE af.event_id=?
                AND NOT EXISTS(SELECT 1 FROM capture_files cf WHERE cf.file_id=f.id)'''
            count = db.execute('SELECT COUNT(*) ' + where, (album_id,)).fetchone()[0]
            rows = db.execute('SELECT f.id,f.file_name,f.path,f.relative_path,f.media_kind,f.size_bytes,f.present ' + where +
                              ' ORDER BY f.file_name,f.id LIMIT ? OFFSET ?', (album_id,limit,offset)).fetchall()
            return {'count':count, 'items':[dict(r) for r in rows]}

    @router.get('/api/imports')
    def imports(limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
        with closing(connect_readonly(get_settings().database_path)) as db:
            rows = db.execute('''SELECT data_json FROM import_jobs ORDER BY
                CASE WHEN state IN ('checking','copying','indexing') THEN 0 ELSE 1 END,
                created_at DESC,id DESC LIMIT ? OFFSET ?''',
                              (limit, offset)).fetchall()
            items = []
            for row in rows:
                job = json.loads(row[0])
                value = ingest.summary(job)
                if job['state'] == 'ready':
                    own = {i.get('file_id') for i in job['items'] if not i['skip']}
                    filed = {r[0] for r in db.execute('''SELECT f.id FROM files f WHERE f.present=1
                        AND REPLACE(f.relative_path,char(92),'/') NOT LIKE '待整理/%' ''')}
                    value['remaining_files'] = len(own - filed)
                items.append(value)
            return {'items': items, 'count': db.execute('SELECT COUNT(*) FROM import_jobs').fetchone()[0]}

    @router.get('/api/imports/{job_id}')
    def detail(job_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        with closing(connect_readonly(get_settings().database_path)) as db:
            try:
                job = ingest.load(db, job_id)
            except ValueError as exc:
                raise HTTPException(404, str(exc)) from exc
            return {**ingest.summary(job), 'items': job['items'][offset:offset+limit],
                    'ignored': job.get('ignored', [])[:100], 'offset': offset, 'limit': limit}

    @router.post('/api/imports/check', status_code=202)
    def check(request: ImportCheck):
        try:
            return manager.start_import_check(request.source)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    @router.post('/api/imports/{job_id}/start', status_code=202)
    def start(job_id: str, request: ImportStart):
        if not request.confirmed:
            raise HTTPException(422, '请确认保留来源原片并复制、入库本批文件')
        try:
            return manager.continue_import(job_id, request.album_id, request.name, request.category)
        except (ValueError, OSError) as exc:
            raise HTTPException(409, str(exc)) from exc

    return router
