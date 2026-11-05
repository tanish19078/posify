from contextlib import contextmanager
import hashlib
import time

import pytest
from fastapi.testclient import TestClient

from posify.app import create_app
from test_api import client, setup_records
from test_captures import upload


def person(c, role='technician', site='plant-a', **flags):
    r = c.post('/v1/access/users', json={'name': 'Test person', **flags})
    assert r.status_code == 201, r.text
    user = r.json()
    if role:
        assert c.put(f"/v1/access/users/{user['id']}/factories/{site}", json={'role': role}).status_code == 200
    receipt = c.post(f"/v1/access/users/{user['id']}/tokens", json={})
    assert receipt.status_code == 201, receipt.text
    assert receipt.headers['cache-control'] == 'no-store'
    return user, receipt.json()


@contextmanager
def as_person(c, credential):
    previous = dict(c.headers)
    c.headers.pop('X-API-Key', None)
    c.headers['Authorization'] = 'Bearer ' + credential['token']
    try:
        yield
    finally:
        c.headers.clear()
        c.headers.update(previous)


def test_individual_tokens_digest_expiry_revocation_and_state(client):
    user, token = person(client)
    with client.app.state.database.connect() as db:
        stored = dict(db.execute('SELECT * FROM user_tokens WHERE id=?', (token['id'],)).fetchone())
    assert stored['digest'] == hashlib.sha256(token['token'].encode()).hexdigest()
    assert token['token'] not in str(stored)
    metadata = client.get(f"/v1/access/users/{user['id']}/tokens").json()[0]
    assert 'digest' not in metadata and 'token' not in metadata
    with as_person(client, token):
        me = client.get('/v1/me').json()
        assert me['id'] == user['id'] and me['memberships'] == [{'site_id': 'plant-a', 'role': 'technician'}]
        assert client.get('/v1/me', headers={'X-API-Key': 'test-key'}).status_code == 401
        assert client.get('/v1/access/users').status_code == 403
    with client.app.state.database.connect() as db:
        db.execute('UPDATE user_tokens SET expires_at=? WHERE id=?', (time.time() - 1, token['id']))
    with as_person(client, token):
        assert client.get('/v1/me').status_code == 401
    fresh = client.post(f"/v1/access/users/{user['id']}/tokens", json={}).json()
    assert client.delete(f"/v1/access/tokens/{fresh['id']}").status_code == 204
    with as_person(client, fresh):
        assert client.get('/v1/me').status_code == 401
    fresh = client.post(f"/v1/access/users/{user['id']}/tokens", json={}).json()
    assert client.patch(f"/v1/access/users/{user['id']}", json={'active': False}).status_code == 200
    assert client.post(f"/v1/access/users/{user['id']}/tokens", json={}).status_code == 409
    assert client.patch(f"/v1/access/users/{user['id']}", json={'active': True}).status_code == 200
    with as_person(client, fresh):
        assert client.get('/v1/me').status_code == 401


def test_factory_scope_cannot_be_overridden_by_query_parameter(client):
    a, _ = setup_records(client)
    b, _ = setup_records(client, site='plant-b')
    _, token = person(client, 'manager')
    body = {k: v for k, v in b.items() if k not in {'id', 'revision'}}
    with as_person(client, token):
        assert client.get('/v1/assets?site_id=plant-a').status_code == 200
        assert client.get('/v1/assets?site_id=plant-b').status_code == 403
        assert client.post('/v1/assets?site_id=plant-a', json={**body, 'tag': 'NEW'}).status_code == 403
        assert client.post('/v1/identify?site_id=plant-a', json={'site_id': 'plant-b', 'tag': 'P-104'}).status_code == 403
        assert client.get(f"/v1/sites/plant-b/assets/{b['id']}?site_id=plant-a").status_code == 403
        assert client.get(f"/v1/sites/plant-a/assets/{b['id']}").status_code == 404
        assert client.get(f"/v1/sites/plant-a/assets/{a['id']}").status_code == 200


@pytest.mark.parametrize('role,can_capture,can_edit', [
    ('viewer', False, False), ('technician', True, False), ('supervisor', True, False), ('manager', True, True)])
def test_factory_role_boundaries(client, role, can_capture, can_edit):
    a, _ = setup_records(client)
    _, token = person(client, role)
    with as_person(client, token):
        assert client.get('/v1/sites/plant-a/pack').status_code == 200
        assert upload(client).status_code == (200 if can_capture else 403)
        assert client.patch(f"/v1/sites/plant-a/assets/{a['id']}", json={
            'expected_revision': 1, 'reason': 'Move', 'location': 'Bay 2'}).status_code == (200 if can_edit else 403)
        assert client.post('/v1/identify', json={'site_id': 'plant-a', 'tag': a['tag']}).status_code == 200
        assert client.get('/v1/organizations').status_code == 403
        assert client.get('/v1/runtime').status_code == 403
        assert client.post('/v1/access/users', json={'name': 'Forbidden'}).status_code == 403


def test_membership_revocation_and_catalogue_curator_permission(client):
    user, token = person(client, 'manager')
    model = {'manufacturer': 'Example', 'model': 'M1', 'category': 'pump', 'source_ref': 'Manual'}
    with as_person(client, token):
        assert client.get('/v1/catalog/models').status_code == 200
        assert client.get('/v1/catalog/models?include_drafts=on').status_code == 403
        assert client.post('/v1/catalog/models', json=model).status_code == 403
    assert client.delete(f"/v1/access/users/{user['id']}/factories/plant-a").status_code == 204
    with as_person(client, token):
        assert client.get('/v1/assets?site_id=plant-a').status_code == 403
    _, curator = person(client, role=None, is_curator=True)
    with as_person(client, curator):
        created = client.post('/v1/catalog/models', json=model)
        assert created.status_code == 201, created.text
        assert client.get('/v1/catalog/models?include_drafts=true').json()[0]['id'] == created.json()['id']
        assert client.post(f"/v1/catalog/models/{created.json()['id']}/publish").status_code == 200
        assert client.get('/v1/assets?site_id=plant-a').status_code == 403


def test_users_only_mode_rejects_bootstrap_and_named_admin_cannot_disable_self(client, monkeypatch):
    user, token = person(client, role=None, is_admin=True)
    with as_person(client, token):
        assert client.patch(f"/v1/access/users/{user['id']}", json={'active': False}).status_code == 409
    monkeypatch.setenv('POSIFY_AUTH_MODE', 'users')
    database = client.app.state.database
    with TestClient(create_app(database.path, 'test-key', database_url=database.engine.url)) as strict:
        assert strict.get('/health').status_code == 200
        assert strict.get('/v1/me', headers={'X-API-Key': 'test-key'}).status_code == 401
        assert strict.get('/v1/me', headers={'Authorization': 'Bearer ' + token['token']}).status_code == 200
    strict.app.state.database.engine.dispose()


def test_request_audit_actor_is_named_and_bootstrap_attribution_restores(client):
    setup_records(client)
    user, token = person(client)
    with as_person(client, token):
        capture = upload(client).json()['capture']
    events = client.get('/v1/sites/plant-a/audit', params={'entity_id': capture['id']}).json()
    assert events[0]['actor_id'] == user['id'] and events[0]['actor_type'] == 'user'
    a = client.post('/v1/assets', json={'site_id': 'plant-a', 'tag': 'SECOND', 'manufacturer': 'M',
        'model': 'M', 'serial': None, 'category': 'pump', 'location': 'Bay'}).json()
    event = client.get('/v1/sites/plant-a/audit', params={'entity_id': a['id']}).json()[0]
    assert event['actor_id'] is None and event['actor_type'] == 'bootstrap'


def test_new_protected_routes_require_explicit_policy(client):
    from fastapi import Depends
    from posify.security import authorization
    auth = authorization(client.app.state.database, 'test-key', 'development')

    @client.app.get('/v1/sites/{site_id}/future-sensitive-feature', dependencies=[Depends(auth)])
    def future(site_id: str):
        return {'secret': 'must remain denied'}

    _, token = person(client, 'manager')
    with as_person(client, token):
        assert client.get('/v1/sites/plant-a/future-sensitive-feature').status_code == 403


def test_provisioning_cli_private_file_and_existing_output_rollback(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path
    from posify.database import Database
    path = tmp_path / 'provision.db'
    output = tmp_path / 'admin.credentials.json'
    env = dict(os.environ, POSIFY_DB=str(path))
    env.pop('POSIFY_DATABASE_URL', None)
    script = Path(__file__).resolve().parents[3] / 'scripts/create_admin.py'
    command = [sys.executable, str(script), '--name', 'Operator', '--output', str(output)]
    first = subprocess.run(command, env=env, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    credential = json.loads(output.read_text())
    if os.name != 'nt':
        assert os.stat(output).st_mode & 0o777 == 0o600
    assert credential['token'] not in first.stdout
    second = subprocess.run(command, env=env, capture_output=True, text=True)
    assert second.returncode != 0
    assert json.loads(output.read_text()) == credential
    db = Database(str(path))
    with db.connect() as session:
        assert session.execute('SELECT COUNT(*) AS n FROM users').fetchone()['n'] == 1
        assert session.execute('SELECT COUNT(*) AS n FROM user_tokens').fetchone()['n'] == 1
        assert session.execute('SELECT actor_type FROM audit').fetchone()['actor_type'] == 'operator'
    db.engine.dispose()
    assert credential['token'].startswith('psf_')


def test_operator_summary_is_administrator_only(client):
    assert client.get('/v1/operations').json()['pending_reviews'] == 0
    _, token = person(client, 'manager')
    with as_person(client, token):
        assert client.get('/v1/operations').status_code == 403
