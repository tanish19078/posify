import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, Query
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool

from posify.catalog import require_factory
from posify.audit import record_event
from posify.analysis import compute_analysis, save_analysis
from posify.captures import MAX_UPLOAD, capture_row, persist_image, sanitize_image
from posify.matching import extract_identifiers, match_identifiers
from posify.schemas import (Capture, CaptureAnalysis, CaptureReceipt, CaptureConfirm,
                            CaptureAssignment, EvidenceAttach, InspectionEvidence)


def install_capture_routes(app, database, auth, root):
    def lookup(db, capture_id, site_id):
        row = db.execute('SELECT * FROM captures WHERE id=? AND site_id=?',
                         (str(capture_id), site_id)).fetchone()
        if row is None:
            raise HTTPException(404, 'Capture not found in this site')
        return capture_row(row)

    def write_capture(raw, media, site_id):
        with database.connect() as db:
            require_factory(db, site_id)
        payload, width, height, flags = sanitize_image(raw, media)
        digest = persist_image(root, payload)
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM captures WHERE site_id=? AND sha256=?', (site_id, digest)).fetchone()
            if row:
                return {'replayed': True, 'capture': capture_row(row)}
            data = dict(id=str(uuid4()), site_id=site_id, sha256=digest, width=width,
                        height=height, warnings=flags, created_at=datetime.now(timezone.utc).isoformat())
            db.execute('INSERT INTO captures VALUES(:id,:site_id,:sha256,:width,:height,:warnings,:created_at)',
                       {**data, 'warnings': json.dumps(flags)})
            record_event(db, site_id, 'capture.created', data['id'], {'sha256': digest})
        return {'replayed': False, 'capture': data}

    @app.post('/v1/sites/{site_id}/captures', response_model=CaptureReceipt, dependencies=auth,
              openapi_extra={'requestBody': {'required': True, 'content': {
                  media: {'schema': {'type': 'string', 'format': 'binary'}}
                  for media in ['image/png', 'image/jpeg']}}})
    async def upload_capture(site_id: str, request: Request):
        if not site_id.strip() or len(site_id) > 200:
            raise HTTPException(422, 'Site ID must contain 1 to 200 characters')
        media = request.headers.get('content-type', '').split(';')[0].strip().lower()
        if media not in {'image/png', 'image/jpeg'}:
            raise HTTPException(415, 'Send raw image/png or image/jpeg bytes, not multipart form data')
        chunks, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_UPLOAD:
                raise HTTPException(413, 'Image exceeds 8 MiB')
            chunks.append(chunk)
        return await run_in_threadpool(write_capture, b''.join(chunks), media, site_id)

    @app.get('/v1/sites/{site_id}/captures/{capture_id}', response_model=Capture, dependencies=auth)
    def capture_metadata(site_id: str, capture_id: UUID):
        with database.connect() as db:
            return lookup(db, capture_id, site_id)

    @app.get('/v1/sites/{site_id}/captures', response_model=list[Capture], dependencies=auth)
    def list_captures(site_id: str, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            require_factory(db, site_id)
            return [capture_row(row) for row in db.execute(
                'SELECT * FROM captures WHERE site_id=? ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?',
                (site_id, limit, offset))]

    @app.get('/v1/sites/{site_id}/captures/{capture_id}/confirm', response_model=CaptureAssignment | None, dependencies=auth)
    def assignment(site_id: str, capture_id: UUID):
        with database.connect() as db:
            lookup(db, capture_id, site_id)
            row = db.execute('SELECT * FROM capture_assignments WHERE capture_id=?', (str(capture_id),)).fetchone()
            return dict(row) if row else None

    @app.get('/v1/sites/{site_id}/captures/{capture_id}/image', dependencies=auth)
    def capture_image(site_id: str, capture_id: UUID):
        with database.connect() as db:
            data = lookup(db, capture_id, site_id)
        path = root / (data['sha256'] + '.png')
        if not path.is_file():
            raise HTTPException(410, 'Capture metadata exists but image content is missing')
        return FileResponse(path, media_type='image/png', headers={'Cache-Control': 'no-store',
                            'X-Content-Type-Options': 'nosniff'})

    @app.post('/v1/sites/{site_id}/captures/{capture_id}/analyze', response_model=CaptureAnalysis, dependencies=auth)
    def analyze(site_id: str, capture_id: UUID):
        result = compute_analysis(app, database, root, site_id, capture_id)
        with database.connect() as db:
            save_analysis(db, site_id, result)
        return result

    @app.get('/v1/sites/{site_id}/captures/{capture_id}/analyses', response_model=list[CaptureAnalysis], dependencies=auth)
    def analyses(site_id: str, capture_id: UUID):
        with database.connect() as db:
            lookup(db, capture_id, site_id)
            rows = db.execute('SELECT result FROM capture_analyses WHERE capture_id=? ORDER BY created_at',
                              (str(capture_id),)).fetchall()
        return [json.loads(row['result']) for row in rows]


    @app.post('/v1/sites/{site_id}/captures/{capture_id}/confirm', response_model=CaptureAssignment, dependencies=auth)
    def confirm_capture(site_id: str, capture_id: UUID, body: CaptureConfirm):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            lookup(db, capture_id, site_id)
            asset = db.execute('SELECT id FROM assets WHERE id=? AND site_id=?',
                               (str(body.asset_id), site_id)).fetchone()
            if not asset:
                raise HTTPException(404, 'Asset not found in this site')
            old = db.execute('SELECT * FROM capture_assignments WHERE capture_id=?', (str(capture_id),)).fetchone()
            if old:
                if old['asset_id'] != str(body.asset_id):
                    raise HTTPException(409, 'Capture already confirmed for another asset')
                return dict(old)
            data = dict(capture_id=str(capture_id), asset_id=str(body.asset_id),
                        confirmed_at=datetime.now(timezone.utc).isoformat())
            db.execute('INSERT INTO capture_assignments VALUES(:capture_id,:asset_id,:confirmed_at)', data)
            record_event(db, site_id, 'capture.confirmed', str(capture_id),
                         {'asset_id': str(body.asset_id), 'basis': 'human_confirmation'})
        return data

    @app.post('/v1/sites/{site_id}/inspections/{inspection_id}/evidence', response_model=InspectionEvidence, dependencies=auth)
    def attach_evidence(site_id: str, inspection_id: UUID, body: EvidenceAttach):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            lookup(db, body.capture_id, site_id)
            current = db.execute('SELECT i.* FROM inspections i JOIN assets a ON a.id=i.asset_id '
                                 'WHERE i.id=? AND a.site_id=?', (str(inspection_id), site_id)).fetchone()
            if not current:
                raise HTTPException(404, 'Inspection not found in this site')
            data = dict(inspection_id=str(inspection_id), capture_id=str(body.capture_id))
            existing = db.execute('SELECT 1 FROM inspection_evidence WHERE inspection_id=? AND capture_id=?',
                                  (str(inspection_id), str(body.capture_id))).fetchone()
            if existing:
                return data
            if current['status'] != 'open':
                raise HTTPException(409, 'Submitted inspections are immutable')
            assigned = db.execute('SELECT asset_id FROM capture_assignments WHERE capture_id=?',
                                  (str(body.capture_id),)).fetchone()
            if not assigned or assigned['asset_id'] != current['asset_id']:
                raise HTTPException(409, 'Confirm this capture for the inspection asset before attaching it')
            db.execute('INSERT INTO inspection_evidence VALUES(:inspection_id,:capture_id)', data)
            record_event(db, site_id, 'inspection.evidence_attached', str(inspection_id), data)
        return data
