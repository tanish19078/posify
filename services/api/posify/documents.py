"""PDF imports remain drafts, retain page citations and never execute PDF content."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from tempfile import NamedTemporaryFile
from uuid import UUID, uuid4

from fastapi import HTTPException, Query, Request
from fastapi.responses import FileResponse
from pydantic import Field
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from posify.audit import record_event, timestamp
from posify.catalog import CatalogDocument, model_record
from posify.pdf_extract import MAX_BYTES
from posify.schemas import StrictModel


class PDFImport(StrictModel):
    document: CatalogDocument
    sha256: str
    page_count: int
    empty_pages: list[int]


def parse_pdf(raw):
    if not raw.startswith(b'%PDF-'):
        raise HTTPException(422, 'Not a PDF document')
    try:
        result = subprocess.run([sys.executable, '-m', 'posify.pdf_extract'], input=raw,
                                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=12, check=False)
        if result.returncode != 0 or len(result.stdout) > 200000:
            raise HTTPException(422, 'PDF extraction exceeded resource limits or failed')
        data = json.loads(result.stdout)
    except subprocess.TimeoutExpired:
        raise HTTPException(422, 'PDF extraction exceeded its time limit')
    except (OSError, ValueError):
        raise HTTPException(503, 'PDF extraction subprocess unavailable')
    if 'error' in data:
        code = data['error']
        raise HTTPException(503 if code == 'resource_limits_unavailable' else
                            413 if code.endswith('_limit') else 422, code)
    return data


def store_original(root, digest, raw):
    root.mkdir(parents=True, exist_ok=True)
    target = root / (digest + '.pdf')
    if target.is_file():
        return
    with NamedTemporaryFile(dir=root, delete=False) as handle:
        temporary = Path(handle.name)
        try:
            handle.write(raw)
            handle.flush()
            try:
                temporary.replace(target)
            except OSError:
                # Concurrent imports can share the same content-addressed original.
                if not target.is_file():
                    raise
        finally:
            temporary.unlink(missing_ok=True)


def install_document_routes(app, database, auth, root):
    def import_document(model_id, raw, title, revision, source_ref):
        with database.connect() as db:
            model_record(db, model_id)
        parsed = parse_pdf(raw)
        digest = hashlib.sha256(raw).hexdigest()
        store_original(root, digest, raw)
        data = dict(id=str(uuid4()), catalog_model_id=str(model_id), title=title, revision=revision,
                    source_text='\n'.join(page['source_text'] for page in parsed['pages']),
                    source_ref=source_ref, status='draft', created_at=timestamp())
        # Joining pages adds separators to the existing document API's text budget.
        if len(data['source_text']) > 30000:
            raise HTTPException(413, 'pdf_text_limit')
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('INSERT INTO catalog_documents VALUES(:id,:catalog_model_id,:title,:revision,:source_text,:source_ref,:status,:created_at)', data)
            except IntegrityError:
                raise HTTPException(409, 'Document revision already exists; create a new revision')
            db.execute('INSERT INTO document_imports VALUES(?,?,?,?)',
                       (data['id'], digest, parsed['page_count'], json.dumps(parsed['empty_pages'])))
            for page in parsed['pages']:
                db.execute('INSERT INTO document_pages VALUES(?,?,?)', (data['id'], page['page_number'], page['source_text']))
            record_event(db, '@catalog', 'catalog.pdf_imported', data['id'],
                         {'sha256': digest, 'page_count': parsed['page_count'], 'empty_pages': parsed['empty_pages']})
        return {'document': data, 'sha256': digest, 'page_count': parsed['page_count'], 'empty_pages': parsed['empty_pages']}

    @app.post('/v1/catalog/models/{model_id}/pdf', response_model=PDFImport, status_code=201, dependencies=auth,
              openapi_extra={'requestBody': {'required': True, 'content': {'application/pdf': {'schema': {'type': 'string', 'format': 'binary'}}}}})
    async def import_pdf(model_id: UUID, request: Request, title: str = Query(min_length=1, max_length=200),
                         revision: int = Query(ge=1), source_ref: str = Query(min_length=1, max_length=200)):
        if not title.strip() or not source_ref.strip():
            raise HTTPException(422, 'Title and source reference cannot be blank')
        if request.headers.get('content-type', '').split(';')[0].strip().lower() != 'application/pdf':
            raise HTTPException(415, 'Send raw application/pdf bytes')
        raw, size = [], 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > MAX_BYTES:
                raise HTTPException(413, 'PDF exceeds 8 MiB')
            raw.append(chunk)
        return await run_in_threadpool(import_document, model_id, b''.join(raw), title.strip(), revision, source_ref.strip())

    @app.get('/v1/catalog/documents/{document_id}/pdf', dependencies=auth)
    def original(document_id: UUID, request: Request):
        who = request.state.principal
        with database.connect() as db:
            row = db.execute('SELECT d.status,m.status AS model_status,i.sha256 FROM catalog_documents d '
                             'JOIN document_imports i ON i.document_id=d.id JOIN catalog_models m ON m.id=d.catalog_model_id WHERE d.id=?',
                             (str(document_id),)).fetchone()
        if not row or (not who['is_admin'] and not who['is_curator'] and
                       (row['status'] != 'published' or row['model_status'] != 'published')):
            raise HTTPException(404, 'Published PDF not found')
        path = root / (row['sha256'] + '.pdf')
        if not path.is_file():
            raise HTTPException(410, 'Original PDF content is missing')
        return FileResponse(path, media_type='application/pdf', filename=str(document_id) + '.pdf',
                            content_disposition_type='attachment', headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})
