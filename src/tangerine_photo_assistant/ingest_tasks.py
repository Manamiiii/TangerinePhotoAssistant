"""Import orchestration in the existing single-task slot."""
from contextlib import closing
from threading import Thread

from . import ingest
from .database import connect, connect_readonly


class ImportTaskMixin:
    def recover_import_job(self):
        with closing(connect_readonly(self.settings.database_path)) as db:
            job = ingest.active(db)
        if job and self._state.status == 'idle':
            self._state = type(self._state)(id=job['id'], status='paused', stage='import-workflow',
                message='导入尚未完成，请在导入新照片中继续', result={'import_id': job['id']})

    def start_import_check(self, source):
        with self._lock:
            if self._state.status in {'running', 'paused'}:
                raise ValueError('请先完成当前后台任务')
            with closing(connect(self.settings.database_path)) as db:
                job = ingest.new_job(db, self.settings, source)
            self._state = type(self._state)(id=job['id'], status='running', stage='import-workflow',
                message='正在检查来源目录…', result={'import_id': job['id']})
        Thread(target=self._run_import_job, args=(job['id'],), daemon=True).start()
        return self.snapshot()

    def continue_import(self, job_id, album_id=None, name='', category='日常'):
        with self._lock:
            if self._state.status == 'running' or (self._state.status == 'paused' and
                (self._state.stage != 'import-workflow' or self._state.id != job_id)):
                raise ValueError('已有运行或暂停的其他任务')
            with closing(connect(self.settings.database_path)) as db:
                job = ingest.load(db, job_id)
                if job['state'] == 'preview':
                    if ingest.active(db):
                        raise ValueError('请先继续未完成导入')
                    ingest.prepare(db, self.settings, job, album_id, name, category)
                elif job['state'] not in ingest.ACTIVE:
                    raise ValueError('该批次无需继续导入')
            self._state = type(self._state)(id=job_id, status='running', stage='import-workflow',
                message='正在继续导入…', result={'import_id': job_id})
        Thread(target=self._run_import_job, args=(job_id,), daemon=True).start()
        return self.snapshot()

    def _run_import_job(self, job_id):
        try:
            self._execute_import_job(job_id)
        except Exception as exc:
            # Fail closed even when opening the database or saving the error fails.
            self._update(status='paused', message=f'导入中断：{exc}；请恢复来源或存储后继续',
                         error=type(exc).__name__, result={'import_id': job_id})

    def _execute_import_job(self, job_id):
        with closing(connect(self.settings.database_path)) as db:
            job = ingest.load(db, job_id)
            def progress(current, total, phase, done, size):
                self._update(current=current, total=total, message=f'{phase}：{current} / {total}',
                             bytes_current=done, bytes_total=size or None)
            try:
                if job['state'] == 'checking':
                    ingest.inspect(db, self.settings, job, progress)
                else:
                    if job['state'] == 'copying':
                        ingest.copy_files(db, self.settings, job, progress)
                    ingest.index_files(db, self.settings, job, progress)
                self._update(status='complete', message='来源检查完成，请确认导入' if job['state']=='preview'
                    else '复制和入库完成，可查看照片或继续正式归档', error=None,
                    result={'import_id':job_id, 'album_id':job.get('album_id')})
            except Exception as exc:
                if job['state'] == 'checking':
                    job['state'] = 'check_failed'
                job['error'] = str(exc)
                ingest.save(db, job)
                self._update(status='paused' if job['state'] in ingest.ACTIVE else 'failed',
                    message='导入中断，原片保留；请在导入页核对原因后继续', error=type(exc).__name__,
                    result={'import_id':job_id, 'album_id':job.get('album_id')})
