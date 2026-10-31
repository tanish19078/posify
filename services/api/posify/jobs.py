"""Database-backed queue. Claims and result publication are short transactions."""
import json
import os
from threading import Event, Thread
import time
from datetime import datetime, timezone
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Query
from pydantic import Field

from posify.analysis import compute_analysis, save_analysis
from posify.catalog import record_event
from posify.schemas import CaptureAnalysis, StrictModel


class JobCreate(StrictModel):
    id: UUID
    mode: Literal['ocr', 'detect_ocr'] = 'ocr'


class AnalysisJob(StrictModel):
    id: UUID
    site_id: str
    capture_id: UUID
    mode: Literal['ocr', 'detect_ocr']
    status: Literal['queued', 'running', 'succeeded', 'failed']
    attempts: int
    max_attempts: int
    error_code: str | None
    result: CaptureAnalysis | None
    created_at: str
    updated_at: str


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def public_job(row):
    data = dict(row)
    for key in ['available_at', 'lease_until', 'claim_token']:
        data.pop(key, None)
    data['result'] = json.loads(data['result']) if data['result'] else None
    return data


def install_job_routes(app, database, auth):
    app.state.job_deadline = int(os.getenv('POSIFY_JOB_DEADLINE_SECONDS', '1800'))
    if not 30 <= app.state.job_deadline <= 7200:
        raise RuntimeError('POSIFY_JOB_DEADLINE_SECONDS must be between 30 and 7200')
    queue_limit = int(os.getenv('POSIFY_QUEUE_LIMIT', '100'))
    if not 1 <= queue_limit <= 10000:
        raise RuntimeError('POSIFY_QUEUE_LIMIT must be between 1 and 10000')
    @app.post('/v1/sites/{site_id}/captures/{capture_id}/jobs', response_model=AnalysisJob,
              dependencies=auth, status_code=202)
    def enqueue(site_id: str, capture_id: UUID, body: JobCreate):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM captures WHERE id=? AND site_id=?', (str(capture_id), site_id)).fetchone():
                raise HTTPException(404, 'Capture not found in this factory')
            previous = db.execute('SELECT * FROM analysis_jobs WHERE id=?', (str(body.id),)).fetchone()
            if previous:
                if (previous['site_id'], previous['capture_id'], previous['mode']) != (site_id, str(capture_id), body.mode):
                    raise HTTPException(409, 'Job ID already used for another request')
                return public_job(previous)
            pending = db.execute("SELECT COUNT(*) AS count FROM analysis_jobs WHERE site_id=? AND status IN ('queued','running')", (site_id,)).fetchone()['count']
            if pending >= queue_limit:
                raise HTTPException(429, 'Factory analysis queue is full', headers={'Retry-After': '2'})
            now = timestamp()
            data = dict(id=str(body.id), site_id=site_id, capture_id=str(capture_id), mode=body.mode,
                        status='queued', attempts=0, max_attempts=3, available_at=time.time(), lease_until=None,
                        claim_token=None, result=None, error_code=None, created_at=now, updated_at=now)
            db.execute('INSERT INTO analysis_jobs VALUES(:id,:site_id,:capture_id,:mode,:status,:attempts,:max_attempts,'
                       ':available_at,:lease_until,:claim_token,:result,:error_code,:created_at,:updated_at)', data)
            record_event(db, site_id, 'analysis_job.queued', data['id'], {'capture_id': str(capture_id), 'mode': body.mode})
        return public_job(data)

    @app.post('/v1/sites/{site_id}/jobs/{job_id}/cancel', response_model=AnalysisJob, dependencies=auth)
    def cancel(site_id: str, job_id: UUID):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM analysis_jobs WHERE id=? AND site_id=?', (str(job_id), site_id)).fetchone()
            if not row:
                raise HTTPException(404, 'Job not found in this factory')
            if row['status'] in {'succeeded', 'failed'}:
                if row['error_code'] == 'cancelled_by_user':
                    return public_job(row)
                raise HTTPException(409, 'Completed jobs cannot be cancelled')
            db.execute("UPDATE analysis_jobs SET status='failed',error_code='cancelled_by_user',lease_until=NULL,claim_token=NULL,updated_at=? WHERE id=?",
                       (timestamp(), str(job_id)))
            record_event(db, site_id, 'analysis_job.cancelled', str(job_id), {})
            result = db.execute('SELECT * FROM analysis_jobs WHERE id=?', (str(job_id),)).fetchone()
        return public_job(result)

    @app.get('/v1/sites/{site_id}/jobs/{job_id}', response_model=AnalysisJob, dependencies=auth)
    def get_job(site_id: str, job_id: UUID):
        with database.connect() as db:
            row = db.execute('SELECT * FROM analysis_jobs WHERE id=? AND site_id=?', (str(job_id), site_id)).fetchone()
        if not row:
            raise HTTPException(404, 'Job not found in this factory')
        return public_job(row)

    @app.get('/v1/sites/{site_id}/jobs', response_model=list[AnalysisJob], dependencies=auth)
    def list_jobs(site_id: str, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            rows = db.execute('SELECT * FROM analysis_jobs WHERE site_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?',
                              (site_id, limit, offset)).fetchall()
        return [public_job(r) for r in rows]


def claim_job(database, lease_seconds=300):
    now, claim = time.time(), str(uuid4())
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        exhausted = db.execute("SELECT id,site_id FROM analysis_jobs WHERE status='running' AND lease_until<? AND attempts>=max_attempts", (now,)).fetchall()
        for expired in exhausted:
            db.execute("UPDATE analysis_jobs SET status='failed',error_code='lease_attempts_exhausted',updated_at=? WHERE id=?",
                       (timestamp(), expired['id']))
            record_event(db, expired['site_id'], 'analysis_job.failed', expired['id'], {'error_code': 'lease_attempts_exhausted'})
        row = db.execute("SELECT * FROM analysis_jobs WHERE attempts<max_attempts AND "
                         "((status='queued' AND available_at<=?) OR (status='running' AND lease_until<?)) "
                         'ORDER BY created_at,id LIMIT 1', (now, now)).fetchone()
        if not row:
            return None
        db.execute("UPDATE analysis_jobs SET status='running',attempts=attempts+1,claim_token=?,lease_until=?,updated_at=? WHERE id=?",
                   (claim, now + lease_seconds, timestamp(), row['id']))
        record_event(db, row['site_id'], 'analysis_job.claimed', row['id'],
                     {'attempt': row['attempts'] + 1, 'reclaimed': row['status'] == 'running'})
        return {**dict(row), 'claim_token': claim, 'attempts': row['attempts'] + 1, 'lease_until': now + lease_seconds}


def finish_job(database, claim, result=None, error_code=None, retryable=False):
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        current = db.execute("SELECT * FROM analysis_jobs WHERE id=? AND status='running' AND claim_token=? AND lease_until>?",
                             (claim['id'], claim['claim_token'], time.time())).fetchone()
        if not current:
            return False  # The lease expired or another worker owns the job. Discard stale work.
        if result is not None:
            save_analysis(db, current['site_id'], result)
            db.execute("UPDATE analysis_jobs SET status='succeeded',result=?,error_code=NULL,lease_until=NULL,claim_token=NULL,updated_at=? WHERE id=?",
                       (json.dumps(result), timestamp(), current['id']))
            record_event(db, current['site_id'], 'analysis_job.succeeded', current['id'], {'analysis_id': result['id']})
        else:
            retry = retryable and current['attempts'] < current['max_attempts']
            status = 'queued' if retry else 'failed'
            db.execute('UPDATE analysis_jobs SET status=?,error_code=?,available_at=?,lease_until=NULL,claim_token=NULL,updated_at=? WHERE id=?',
                       (status, error_code, time.time() + min(30, 2 ** current['attempts']), timestamp(), current['id']))
            record_event(db, current['site_id'], 'analysis_job.' + status, current['id'], {'error_code': error_code})
        return True


def renew_claim(database, claim, lease_seconds):
    with database.connect() as db:
        db.execute('BEGIN IMMEDIATE')
        result = db.execute("UPDATE analysis_jobs SET lease_until=?,updated_at=? WHERE id=? AND status='running' AND claim_token=? AND lease_until>?",
                            (time.time() + lease_seconds, timestamp(), claim['id'], claim['claim_token'], time.time()))
        return result.rowcount == 1


def work_once(app, lease_seconds=300):
    claim = claim_job(app.state.database, lease_seconds)
    if not claim:
        return False
    stopped = Event()
    deadline = time.monotonic() + app.state.job_deadline
    def heartbeat():
        while not stopped.wait(max(.1, lease_seconds / 3)):
            try:
                if time.monotonic() >= deadline or not renew_claim(app.state.database, claim, lease_seconds):
                    return
            except Exception:
                return  # Lost database contact: let the lease expire; do not assume ownership.
    thread = Thread(target=heartbeat, name='posify-job-heartbeat', daemon=True)
    thread.start()
    try:
        result = compute_analysis(app, app.state.database, app.state.capture_root,
                                  claim['site_id'], claim['capture_id'], claim['mode'])
        if time.monotonic() >= deadline:
            finish_job(app.state.database, claim, error_code='execution_deadline')
        else:
            finish_job(app.state.database, claim, result=result)
    except HTTPException as exc:
        finish_job(app.state.database, claim, error_code=f'component_http_{exc.status_code}',
                   retryable=exc.status_code >= 500)
    except Exception:
        finish_job(app.state.database, claim, error_code='internal_analysis_error', retryable=True)
    finally:
        stopped.set()
        thread.join(timeout=1)
    return True
