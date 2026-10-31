"""Supervisor review remains separate from the immutable submitted inspection."""
from typing import Annotated, Literal
from uuid import UUID

from fastapi import HTTPException, Query, Request
from pydantic import StringConstraints

from posify.audit import record_event, timestamp
from posify.schemas import StrictModel, Inspection


class ReviewCreate(StrictModel):
    id: UUID
    outcome: Literal['accepted', 'follow_up']
    note: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=4000)]


class Review(ReviewCreate):
    inspection_id: UUID
    reviewer_id: UUID
    created_at: str


class ReviewReceipt(StrictModel):
    replayed: bool
    review: Review


def install_review_routes(app, database, auth):
    @app.get('/v1/inspections', response_model=list[Inspection], dependencies=auth)
    def inspections(site_id: str = Query(min_length=1), status: Literal['open', 'submitted'] | None = None,
                    unreviewed: bool = False, limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        clauses, args = ['a.site_id=?'], [site_id]
        if status:
            clauses.append('i.status=?')
            args.append(status)
        if unreviewed:
            clauses.extend(["i.status='submitted'", 'NOT EXISTS (SELECT 1 FROM inspection_reviews r WHERE r.inspection_id=i.id)'])
        with database.connect() as db:
            return [dict(r) for r in db.execute('SELECT i.* FROM inspections i JOIN assets a ON a.id=i.asset_id WHERE '
                    + ' AND '.join(clauses) + ' ORDER BY i.created_at DESC,i.id LIMIT ? OFFSET ?', [*args, limit, offset])]

    @app.post('/v1/sites/{site_id}/inspections/{inspection_id}/reviews', response_model=ReviewReceipt, dependencies=auth)
    def review(site_id: str, inspection_id: UUID, body: ReviewCreate, request: Request):
        reviewer = request.state.principal['id']
        if not reviewer:
            raise HTTPException(403, 'Review requires an individual bearer credential')
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT i.* FROM inspections i JOIN assets a ON a.id=i.asset_id WHERE i.id=? AND a.site_id=?',
                                 (str(inspection_id), site_id)).fetchone()
            if not current:
                raise HTTPException(404, 'Inspection not found in this factory')
            existing = db.execute('SELECT * FROM inspection_reviews WHERE id=? OR inspection_id=?',
                                  (str(body.id), str(inspection_id))).fetchone()
            if existing:
                if (existing['id'], existing['inspection_id'], existing['reviewer_id'], existing['outcome'], existing['note']) != (
                    str(body.id), str(inspection_id), reviewer, body.outcome, body.note):
                    raise HTTPException(409, 'Review already recorded or ID reused with different content')
                return {'replayed': True, 'review': dict(existing)}
            if current['status'] != 'submitted':
                raise HTTPException(409, 'Submit the inspection before review')
            if reviewer in {current['created_by'], current['submitted_by']}:
                raise HTTPException(409, 'Review must be performed by a different individual')
            if db.execute("SELECT 1 FROM observations o JOIN audit e ON e.entity_id=o.id AND e.kind='observation.created' WHERE o.inspection_id=? AND e.actor_id=?",
                          (str(inspection_id), reviewer)).fetchone():
                raise HTTPException(409, 'Review must be independent of observation authors')
            if body.outcome == 'accepted' and db.execute("SELECT 1 FROM observations WHERE inspection_id=? AND result!='pass'",
                                                         (str(inspection_id),)).fetchone():
                raise HTTPException(409, 'Failed or unknown findings require follow-up')
            data = {**body.model_dump(mode='json'), 'inspection_id': str(inspection_id),
                    'reviewer_id': reviewer, 'created_at': timestamp()}
            db.execute('INSERT INTO inspection_reviews VALUES(:id,:inspection_id,:reviewer_id,:outcome,:note,:created_at)', data)
            record_event(db, site_id, 'inspection.reviewed', str(inspection_id),
                         {'review_id': data['id'], 'outcome': body.outcome})
        return {'replayed': False, 'review': data}

    @app.get('/v1/sites/{site_id}/inspections/{inspection_id}/reviews', response_model=list[Review], dependencies=auth)
    def reviews(site_id: str, inspection_id: UUID):
        with database.connect() as db:
            if not db.execute('SELECT i.id FROM inspections i JOIN assets a ON a.id=i.asset_id WHERE i.id=? AND a.site_id=?',
                              (str(inspection_id), site_id)).fetchone():
                raise HTTPException(404, 'Inspection not found in this factory')
            return [dict(r) for r in db.execute('SELECT * FROM inspection_reviews WHERE inspection_id=?', (str(inspection_id),))]
