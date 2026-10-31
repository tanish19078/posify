"""Opaque individual credentials and fail-closed factory authorization."""
import hashlib
import secrets
import time
from uuid import UUID, uuid4
from typing import Literal

from fastapi import Depends, HTTPException, Query, Request, Response
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field

from posify.audit import actor, record_event, timestamp
from posify.schemas import StrictModel, Text

ROLES = {'viewer': 0, 'technician': 1, 'supervisor': 2, 'manager': 3}

SITE_PERMISSIONS = {
    ('GET', '/v1/assets'): 'viewer', ('POST', '/v1/assets'): 'manager',
    ('POST', '/v1/procedures'): 'manager', ('POST', '/v1/identify'): 'viewer',
    ('POST', '/v1/assistant/query'): 'viewer',
    ('GET', '/v1/inspections'): 'viewer', ('POST', '/v1/inspections'): 'technician',
    ('GET', '/v1/procedures'): 'viewer',
    ('GET', '/v1/inspections/{inspection_id}'): 'viewer',
    ('POST', '/v1/inspections/{inspection_id}/observations'): 'technician',
    ('POST', '/v1/inspections/{inspection_id}/submit'): 'technician',
}
for method, suffix, role in [
    ('GET', '/assets/{asset_id}', 'viewer'), ('PATCH', '/assets/{asset_id}', 'manager'),
    ('GET', '/pack', 'viewer'), ('GET', '/audit', 'viewer'),
    ('POST', '/captures', 'technician'), ('GET', '/captures/{capture_id}', 'viewer'),
    ('GET', '/captures', 'viewer'), ('GET', '/captures/{capture_id}/confirm', 'viewer'),
    ('GET', '/captures/{capture_id}/image', 'viewer'),
    ('POST', '/captures/{capture_id}/analyze', 'technician'),
    ('GET', '/captures/{capture_id}/analyses', 'viewer'),
    ('POST', '/captures/{capture_id}/confirm', 'technician'),
    ('POST', '/inspections/{inspection_id}/evidence', 'technician'),
    ('POST', '/captures/{capture_id}/jobs', 'technician'),
    ('GET', '/jobs', 'viewer'), ('GET', '/jobs/{job_id}', 'viewer'),
    ('POST', '/jobs/{job_id}/cancel', 'technician'),
    ('GET', '/assets/{asset_id}/catalog-link', 'viewer'),
    ('POST', '/assets/{asset_id}/catalog-link', 'manager'),
    ('POST', '/assets/{asset_id}/corrections', 'manager'),
    ('POST', '/captures/{capture_id}/corrections', 'manager'),
    ('GET', '/corrections', 'viewer'), ('POST', '/corrections/{correction_id}/decision', 'supervisor'),
    ('GET', '/inspections/{inspection_id}/reviews', 'viewer'),
    ('POST', '/inspections/{inspection_id}/reviews', 'supervisor'),
]:
    SITE_PERMISSIONS[(method, '/v1/sites/{site_id}' + suffix)] = role

CATALOG_PERMISSIONS = {
    ('POST', '/v1/catalog/models/{model_id}/pdf'),
    ('GET', '/v1/catalog/documents/{document_id}/pdf'),
    ('GET', '/v1/catalog/models'), ('POST', '/v1/catalog/models'),
    ('POST', '/v1/catalog/models/{model_id}/publish'),
    ('GET', '/v1/catalog/models/{model_id}/documents'),
    ('POST', '/v1/catalog/models/{model_id}/documents'),
    ('POST', '/v1/catalog/documents/{document_id}/publish'),
}



class UserCreate(StrictModel):
    name: Text
    is_admin: bool = False
    is_curator: bool = False


class User(StrictModel):
    id: UUID
    name: str
    active: bool
    is_admin: bool
    is_curator: bool
    created_at: str


class Membership(StrictModel):
    role: Literal['viewer', 'technician', 'supervisor', 'manager']


class UserState(StrictModel):
    active: bool


class TokenCreate(StrictModel):
    lifetime_days: int = Field(default=30, ge=1, le=90)


class TokenReceipt(StrictModel):
    id: UUID
    user_id: UUID
    token: str
    expires_at: float


class TokenInfo(StrictModel):
    id: UUID
    user_id: UUID
    expires_at: float
    revoked: bool
    created_at: str


def create_user(db, body):
    data = dict(id=str(uuid4()), name=body.name, active=1,
                is_admin=int(body.is_admin), is_curator=int(body.is_curator), created_at=timestamp())
    db.execute('INSERT INTO users VALUES(:id,:name,:active,:is_admin,:is_curator,:created_at)', data)
    return data


def issue_token(db, user_id, days):
    credential = 'psf_' + secrets.token_urlsafe(32)
    data = dict(id=str(uuid4()), user_id=str(user_id),
                digest=hashlib.sha256(credential.encode()).hexdigest(),
                expires_at=time.time() + days * 86400, revoked=0, created_at=timestamp())
    db.execute('INSERT INTO user_tokens VALUES(:id,:user_id,:digest,:expires_at,:revoked,:created_at)', data)
    return {'id': data['id'], 'user_id': data['user_id'], 'token': credential, 'expires_at': data['expires_at']}


def enforce_policy(request, who, database, body=None):
    """Unknown routes and global administration are denied to ordinary members."""
    route, method = request.scope['route'].path, request.method
    if method == 'GET' and route in {'/v1/me', '/v1/workspaces'}:
        return
    if who['is_admin']:
        return
    if (method, route) in CATALOG_PERMISSIONS:
        drafts = request.query_params.get('include_drafts', 'false').lower() not in {'false', '0', 'off', 'no', ''}
        if (method != 'GET' or drafts) and not who['is_curator']:
            raise HTTPException(403, 'Catalogue curator permission required')
        return
    body_scoped = {'/v1/assets', '/v1/procedures', '/v1/identify', '/v1/inspections',
                   '/v1/assistant/query', '/v1/inspections/{inspection_id}/observations'}
    if request.path_params.get('site_id') is not None:
        site = request.path_params['site_id']
    elif method != 'GET' and route in body_scoped:
        site = body.get('site_id') if isinstance(body, dict) else None
    else:
        site = request.query_params.get('site_id')
    required = SITE_PERMISSIONS.get((method, route))
    if required is None or not isinstance(site, str):
        raise HTTPException(403, 'Administrator permission required')
    with database.connect() as db:
        membership = db.execute('SELECT role FROM factory_memberships WHERE user_id=? AND site_id=?',
                                (who['id'], site)).fetchone()
    if not membership:
        raise HTTPException(403, 'Factory membership required')
    if ROLES[membership['role']] < ROLES[required]:
        raise HTTPException(403, f'{required.capitalize()} factory permission required')


def authorization(database, bootstrap_token, mode):
    key_header = APIKeyHeader(name='X-API-Key', auto_error=False)
    bearer = HTTPBearer(auto_error=False)

    async def authorize(request: Request, key: str | None = Depends(key_header),
                        credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if key and request.headers.get('authorization'):
            raise HTTPException(401, 'Supply exactly one credential')
        if key:
            if mode != 'development' or not bootstrap_token or not secrets.compare_digest(key.encode(), bootstrap_token.encode()):
                raise HTTPException(401, 'Invalid API key')
            who = {'id': None, 'type': 'bootstrap', 'is_admin': True, 'is_curator': True}
        else:
            if not credentials or credentials.scheme.lower() != 'bearer':
                raise HTTPException(401, 'Bearer credential required')
            digest = hashlib.sha256(credentials.credentials.encode()).hexdigest()
            with database.connect() as db:
                row = db.execute('SELECT u.* FROM users u JOIN user_tokens t ON t.user_id=u.id '
                                 'WHERE t.digest=? AND t.revoked=0 AND t.expires_at>? AND u.active=1',
                                 (digest, time.time())).fetchone()
            if not row:
                raise HTTPException(401, 'Invalid or expired credential')
            who = {**dict(row), 'type': 'user'}
        body = None
        if request.method != 'GET' and request.scope['route'].path in {
            '/v1/assets', '/v1/procedures', '/v1/identify', '/v1/inspections',
            '/v1/assistant/query', '/v1/inspections/{inspection_id}/observations'}:
            try:
                body = await request.json()
            except (ValueError, UnicodeDecodeError):
                body = None
        enforce_policy(request, who, database, body)
        request.state.principal = who
        marker = actor.set(who)
        try:
            yield who
        finally:
            actor.reset(marker)
    return authorize


def install_security_routes(app, database, auth):
    @app.get('/v1/workspaces', dependencies=auth)
    def workspaces(request: Request, limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0)):
        who = request.state.principal
        with database.connect() as db:
            if who['is_admin']:
                rows = db.execute('SELECT * FROM factories ORDER BY name,id LIMIT ? OFFSET ?', (limit, offset))
            else:
                rows = db.execute('SELECT f.* FROM factories f JOIN factory_memberships m ON m.site_id=f.id '
                                  'WHERE m.user_id=? ORDER BY f.name,f.id LIMIT ? OFFSET ?', (who['id'], limit, offset))
            return [dict(row) for row in rows]

    @app.get('/v1/me', dependencies=auth)
    def me(request: Request):
        who = request.state.principal
        with database.connect() as db:
            memberships = [dict(r) for r in db.execute('SELECT site_id,role FROM factory_memberships WHERE user_id=? ORDER BY site_id',
                                                      (who['id'],))] if who['id'] else []
        return {'id': who['id'], 'name': who.get('name'), 'type': who['type'],
                'is_admin': bool(who['is_admin']), 'is_curator': bool(who['is_curator']), 'memberships': memberships}

    @app.post('/v1/access/users', status_code=201, response_model=User, dependencies=auth)
    def add_user(body: UserCreate):
        with database.connect() as db:
            data = create_user(db, body)
            record_event(db, '@security', 'user.created', data['id'], {'is_admin': body.is_admin, 'is_curator': body.is_curator})
        return data

    @app.get('/v1/access/users', response_model=list[User], dependencies=auth)
    def users(limit: int = Query(100, ge=1, le=200), offset: int = Query(0, ge=0)):
        with database.connect() as db:
            return [dict(r) for r in db.execute('SELECT * FROM users ORDER BY id LIMIT ? OFFSET ?', (limit, offset))]

    def require_user(db, user_id):
        row = db.execute('SELECT * FROM users WHERE id=?', (str(user_id),)).fetchone()
        if not row:
            raise HTTPException(404, 'User not found')
        return row

    @app.patch('/v1/access/users/{user_id}', response_model=User, dependencies=auth)
    def user_state(user_id: UUID, body: UserState, request: Request):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = dict(require_user(db, user_id))
            if str(user_id) == request.state.principal['id'] and not body.active:
                raise HTTPException(409, 'Administrators cannot disable themselves')
            db.execute('UPDATE users SET active=? WHERE id=?', (int(body.active), str(user_id)))
            if not body.active:
                db.execute('UPDATE user_tokens SET revoked=1 WHERE user_id=?', (str(user_id),))
            record_event(db, '@security', 'user.state_changed', str(user_id), {'active': body.active})
        return {**current, 'active': body.active}

    @app.put('/v1/access/users/{user_id}/factories/{site_id}', dependencies=auth)
    def membership(user_id: UUID, site_id: str, body: Membership):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require_user(db, user_id)
            if not db.execute('SELECT id FROM factories WHERE id=?', (site_id,)).fetchone():
                raise HTTPException(404, 'Factory not found')
            db.execute('DELETE FROM factory_memberships WHERE user_id=? AND site_id=?', (str(user_id), site_id))
            db.execute('INSERT INTO factory_memberships VALUES(?,?,?)', (str(user_id), site_id, body.role))
            record_event(db, site_id, 'membership.granted', str(user_id), {'role': body.role})
        return {'user_id': str(user_id), 'site_id': site_id, 'role': body.role}

    @app.delete('/v1/access/users/{user_id}/factories/{site_id}', status_code=204, dependencies=auth)
    def remove_membership(user_id: UUID, site_id: str):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            require_user(db, user_id)
            db.execute('DELETE FROM factory_memberships WHERE user_id=? AND site_id=?', (str(user_id), site_id))
            record_event(db, site_id, 'membership.removed', str(user_id), {})
        return Response(status_code=204)

    @app.post('/v1/access/users/{user_id}/tokens', status_code=201, response_model=TokenReceipt, dependencies=auth)
    def token(user_id: UUID, body: TokenCreate, response: Response):
        with database.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not require_user(db, user_id)['active']:
                raise HTTPException(409, 'User is disabled')
            data = issue_token(db, user_id, body.lifetime_days)
            record_event(db, '@security', 'token.issued', data['id'], {'user_id': str(user_id)})
        response.headers['Cache-Control'] = 'no-store'
        return data

    @app.get('/v1/access/users/{user_id}/tokens', response_model=list[TokenInfo], dependencies=auth)
    def tokens(user_id: UUID, limit: int = Query(100, ge=1, le=200)):
        with database.connect() as db:
            require_user(db, user_id)
            return [dict(r) for r in db.execute('SELECT id,user_id,expires_at,revoked,created_at FROM user_tokens WHERE user_id=? ORDER BY created_at DESC LIMIT ?',
                                               (str(user_id), limit))]

    @app.delete('/v1/access/tokens/{token_id}', status_code=204, dependencies=auth)
    def revoke(token_id: UUID):
        with database.connect() as db:
            if not db.execute('SELECT id FROM user_tokens WHERE id=?', (str(token_id),)).fetchone():
                raise HTTPException(404, 'Token not found')
            db.execute('UPDATE user_tokens SET revoked=1 WHERE id=?', (str(token_id),))
            record_event(db, '@security', 'token.revoked', str(token_id), {})
        return Response(status_code=204)
