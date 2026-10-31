"""Two-person corrections for confirmed links; attached evidence cannot be reassigned."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Query, Request
from pydantic import Field, StringConstraints

from posify.audit import record_event, timestamp
from posify.schemas import StrictModel

Reason = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class CatalogCorrection(StrictModel):
    id: UUID
    expected_revision: int = Field(ge=1)
    catalog_model_id: UUID
    reason: Reason


class CaptureCorrection(StrictModel):
    id: UUID
    asset_id: UUID
    reason: Reason


class Decision(StrictModel):
    decision: Literal['approved', 'rejected']
    note: Reason


class Correction(StrictModel):
    id: UUID
    site_id: str
    entity_kind: Literal['asset_catalog', 'capture_assignment']
    entity_id: UUID
    expected_revision: int | None
    before_value: UUID
    after_value: UUID
    reason: str
    requested_by: UUID
    status: Literal['pending', 'approved', 'rejected']
    reviewed_by: UUID | None
    review_note: str | None
    created_at: str
    reviewed_at: str | None


def individual(request):
    user_id = request.state.principal['id']
    if not user_id:
        raise HTTPException(403, 'Correction requires an individual bearer credential')
    return user_id


def validate_target(db, site, kind, entity, target):
    if kind == 'asset_catalog':
        asset = db.execute('SELECT * FROM assets WHERE id=? AND site_id=?', (entity, site)).fetchone()
        if not asset:
            raise HTTPException(404, 'Asset not found in this factory')
        model = db.execute("SELECT * FROM catalog_models WHERE id=? AND status='published'", (target,)).fetchone()
        if not model:
            raise HTTPException(409, 'Target catalogue model must be published')
        if (asset['manufacturer'].casefold(), asset['model'].casefold()) != (model['manufacturer'].casefold(), model['model'].casefold()):
            raise HTTPException(409, 'Correction must retain manufacturer/model applicability')
        current = db.execute('SELECT catalog_model_id AS value FROM asset_catalog_links WHERE asset_id=?', (entity,)).fetchone()
        revision = asset['revision']
    else:
        if not db.execute('SELECT id FROM captures WHERE id=? AND site_id=?', (entity, site)).fetchone():
            raise HTTPException(404, 'Capture not found in this factory')
        if not db.execute('SELECT id FROM assets WHERE id=? AND site_id=?', (target, site)).fetchone():
            raise HTTPException(404, 'Target asset not found in this factory')
        if db.execute('SELECT 1 FROM inspection_evidence WHERE capture_id=?', (entity,)).fetchone():
            raise HTTPException(409, 'Capture attached to an inspection cannot be reassigned')
        current = db.execute('SELECT asset_id AS value FROM capture_assignments WHERE capture_id=?', (entity,)).fetchone()
        revision = None
    if not current:
        raise HTTPException(409, 'Confirm an initial link before requesting a correction')
    return current['value'], revision


def install_correction_routes(app, database, auth):
    def create(site, entity, kind, body, request, target, expected=None):
        user_id = individual(request)
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT * FROM correction_requests WHERE id=?', (str(body.id),)).fetchone()
            if old:
                if (old['site_id'], old['entity_id'], old['entity_kind'], old['requested_by'], old['after_value'], old['reason'], old['expected_revision']) != (
                    site, str(entity), kind, user_id, str(target), body.reason, expected):
                    raise HTTPException(409, 'Correction ID reused with different content')
                return dict(old)
            before, revision = validate_target(db, site, kind, str(entity), str(target))
            if revision != expected:
                raise HTTPException(409, 'Asset changed; reload before requesting correction')
            if before == str(target):
                raise HTTPException(422, 'Correction must change the confirmed link')
            data = dict(id=str(body.id), site_id=site, entity_id=str(entity), entity_kind=kind,
                        expected_revision=expected, before_value=before, after_value=str(target), reason=body.reason,
                        requested_by=user_id, status='pending', reviewed_by=None, review_note=None,
                        created_at=timestamp(), reviewed_at=None)
            db.execute('INSERT INTO correction_requests (id,site_id,entity_kind,entity_id,expected_revision,before_value,after_value,reason,requested_by,status,reviewed_by,review_note,created_at,reviewed_at) '
                       'VALUES(:id,:site_id,:entity_kind,:entity_id,:expected_revision,:before_value,:after_value,:reason,:requested_by,:status,:reviewed_by,:review_note,:created_at,:reviewed_at)', data)
            record_event(db, site, 'correction.requested', data['id'], {'entity_kind': kind, 'entity_id': str(entity)})
        return data

    @app.post('/v1/sites/{site_id}/assets/{asset_id}/corrections', response_model=Correction, dependencies=auth)
    def catalog_correction(site_id: str, asset_id: UUID, body: CatalogCorrection, request: Request):
        return create(site_id, asset_id, 'asset_catalog', body, request, body.catalog_model_id, body.expected_revision)

    @app.post('/v1/sites/{site_id}/captures/{capture_id}/corrections', response_model=Correction, dependencies=auth)
    def capture_correction(site_id: str, capture_id: UUID, body: CaptureCorrection, request: Request):
        return create(site_id, capture_id, 'capture_assignment', body, request, body.asset_id)

    @app.get('/v1/sites/{site_id}/corrections', response_model=list[Correction], dependencies=auth)
    def corrections(site_id: str, status: Literal['pending', 'approved', 'rejected'] | None = None,
                    limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM correction_requests WHERE site_id=? '
                    + ('AND status=? ' if status else '') + 'ORDER BY created_at DESC,id LIMIT ? OFFSET ?',
                    [site_id, *([status] if status else []), limit, offset])]

    @app.post('/v1/sites/{site_id}/corrections/{correction_id}/decision', response_model=Correction, dependencies=auth)
    def decision(site_id: str, correction_id: UUID, body: Decision, request: Request):
        reviewer = individual(request)
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM correction_requests WHERE id=? AND site_id=?', (str(correction_id), site_id)).fetchone()
            if not row:
                raise HTTPException(404, 'Correction not found in this factory')
            data = dict(row)
            if data['requested_by'] == reviewer:
                raise HTTPException(409, 'A different individual must review the correction')
            if data['status'] != 'pending':
                if (data['status'], data['reviewed_by'], data['review_note']) == (body.decision, reviewer, body.note):
                    return data
                raise HTTPException(409, 'Correction decision is immutable')
            if body.decision == 'approved':
                before, revision = validate_target(db, site_id, data['entity_kind'], data['entity_id'], data['after_value'])
                if before != data['before_value'] or revision != data['expected_revision']:
                    raise HTTPException(409, 'Confirmed link or asset revision changed; request a new correction')
                if data['entity_kind'] == 'asset_catalog':
                    db.execute('UPDATE asset_catalog_links SET catalog_model_id=?,confirmed_at=? WHERE asset_id=?',
                               (data['after_value'], timestamp(), data['entity_id']))
                    db.execute('UPDATE assets SET revision=revision+1 WHERE id=?', (data['entity_id'],))
                else:
                    db.execute('UPDATE capture_assignments SET asset_id=?,confirmed_at=? WHERE capture_id=?',
                               (data['after_value'], timestamp(), data['entity_id']))
            data.update(status=body.decision, reviewed_by=reviewer, review_note=body.note, reviewed_at=timestamp())
            db.execute('UPDATE correction_requests SET status=?,reviewed_by=?,review_note=?,reviewed_at=? WHERE id=?',
                       (data['status'], reviewer, body.note, data['reviewed_at'], data['id']))
            record_event(db, site_id, 'correction.' + body.decision, data['id'],
                         {'entity_kind': data['entity_kind'], 'entity_id': data['entity_id'],
                          'before': data['before_value'], 'after': data['after_value']})
        return data
