from uuid import uuid4
import os
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from posify.database import Database

import pytest
from fastapi.testclient import TestClient

from posify.app import create_app


@pytest.fixture
def client(tmp_path):
    target = os.getenv('POSIFY_TEST_DATABASE_URL')
    admin = None
    schema = 'test_' + uuid4().hex
    url = None
    if target:
        parsed = make_url(target)
        if parsed.drivername in {'postgresql', 'postgres'}:
            parsed = parsed.set(drivername='postgresql+psycopg')
        admin = create_engine(parsed)
        with admin.begin() as connection:
            connection.execute(text('CREATE SCHEMA "' + schema + '"'))
        url = parsed.update_query_dict({'options': '-csearch_path=' + schema})
        prepared = Database(str(tmp_path / 'test.db'), url=url, migrate=True)
        prepared.engine.dispose()
    try:
        with TestClient(create_app(str(tmp_path / 'test.db'), 'test-key', database_url=url)) as c:
            c.headers['X-API-Key'] = 'test-key'
            register_factory(c, 'plant-a')
            register_factory(c, 'plant-b')
            yield c
        c.app.state.database.engine.dispose()
    finally:
        if admin:
            with admin.begin() as connection:
                connection.execute(text('DROP SCHEMA "' + schema + '" CASCADE'))
            admin.dispose()


def register_factory(c, site):
    org = c.post('/v1/organizations', json={'name': 'Test organization'}).json()
    r = c.post('/v1/factories', json={'id': site, 'organization_id': org['id'], 'name': site})
    assert r.status_code == 201, r.text


def setup_records(c, site='plant-a', model='M1', version=1):
    # Restart tests instantiate a fresh client without the fixture's seed factories.
    with c.app.state.database.connect() as db:
        known = db.execute('SELECT id FROM factories WHERE id=?', (site,)).fetchone()
    if not known:
        register_factory(c, site)
    a = c.post('/v1/assets', json=dict(site_id=site, tag='P-104', manufacturer='Example',
               model=model, serial='S-001', category='pump', location='Bay 1'))
    assert a.status_code == 201, a.text
    p = c.post('/v1/procedures', json=dict(site_id=site, manufacturer='Example', model=model,
               title='Visual inspection', version=version,
               steps=[dict(id='exterior', instruction='Record visible exterior condition.')],
               source_text='Exterior inspection: record visible condition without operating equipment.'))
    assert p.status_code == 201, p.text
    return a.json(), p.json()


def start(c, a, p):
    return c.post('/v1/inspections', json=dict(site_id=a['site_id'], asset_id=a['id'],
                  procedure_id=p['id'], asset_confirmed=True))


def test_auth_and_health(client):
    assert client.get('/health').status_code == 200
    assert client.get('/v1/assets?site_id=plant-a', headers={'X-API-Key': 'wrong'}).status_code == 401
    assert client.get('/v1/assets').status_code == 422


def test_identity_never_guesses_from_category(client):
    a, _ = setup_records(client)
    assert client.post('/v1/identify', json={'site_id': 'plant-a', 'category': 'pump'}).json()['candidates'] == []
    matched = client.post('/v1/identify', json={'site_id': 'plant-a', 'tag': 'P-104'}).json()
    assert matched['candidates'][0]['id'] == a['id']
    assert matched['requires_confirmation']
    assert client.post('/v1/identify', json={'site_id': 'plant-a', 'tag': 'P-104', 'serial': 'wrong'}).json()['candidates'] == []
    assert client.post('/v1/identify', json={'site_id': 'plant-b', 'tag': 'P-104'}).json()['candidates'] == []


def test_unique_identifiers_and_procedure_versions(client):
    a, p = setup_records(client)
    assert client.post('/v1/assets', json={k: v for k, v in a.items() if k not in {'id', 'revision'}}).status_code == 409
    assert client.post('/v1/procedures', json={k: v for k, v in p.items() if k != 'id'}).status_code == 409
    assert client.post('/v1/procedures', json={**{k: v for k, v in p.items() if k != 'id'}, 'version': 2}).status_code == 201


def test_confirmation_applicability_and_site(client):
    a, p = setup_records(client)
    data = dict(site_id='plant-a', asset_id=a['id'], procedure_id=p['id'], asset_confirmed=False)
    assert client.post('/v1/inspections', json=data).status_code == 422
    assert client.post('/v1/inspections', json={**data, 'asset_confirmed': True, 'site_id': 'other'}).status_code == 404
    p2 = client.post('/v1/procedures', json={**{k: v for k, v in p.items() if k != 'id'}, 'model': 'M2'}).json()
    assert start(client, a, p2).status_code == 409


def test_inspection_replay_and_submission(client):
    a, p = setup_records(client)
    i = start(client, a, p).json()['id']
    route = f'/v1/inspections/{i}'
    assert client.post(route + '/submit?site_id=plant-a').status_code == 409
    body = dict(id=str(uuid4()), site_id='plant-a', step_id='exterior', result='unknown', note='Photo unclear')
    assert client.post(route + '/observations', json={**body, 'step_id': 'invented'}).status_code == 422
    first = client.post(route + '/observations', json=body)
    assert first.status_code == 200
    assert not first.json()['replayed']
    assert client.post(route + '/observations', json=body).json()['replayed']
    assert client.post(route + '/observations', json={**body, 'result': 'pass'}).status_code == 409
    assert client.post(route + '/observations', json={**body, 'id': str(uuid4())}).status_code == 409
    assert client.post(route + '/submit?site_id=plant-a').json()['status'] == 'submitted'
    assert client.post(route + '/observations', json=body).json()['replayed']
    assert client.post(route + '/observations', json={**body, 'id': str(uuid4())}).status_code == 409
    assert client.post(route + '/submit?site_id=plant-a').json()['replayed']
    assert client.get(route + '?site_id=other').status_code == 404
    assert client.get(route + '?site_id=plant-a').json()['observations'][0]['result'] == 'unknown'
    events = client.get('/v1/sites/plant-a/audit').json()
    assert [e['kind'] for e in events].count('observation.created') == 1
    assert [e['kind'] for e in events].count('inspection.submitted') == 1


def test_site_pack_is_scoped_and_retains_pinned_version(client):
    a, p = setup_records(client)
    setup_records(client, site='plant-b')
    i = start(client, a, p).json()
    client.post('/v1/procedures', json={**{k: v for k, v in p.items() if k != 'id'}, 'version': 2})
    pack = client.get('/v1/sites/plant-a/pack').json()
    assert len(pack['assets']) == 1
    assert len(pack['procedures']) == 2
    assert pack['inspections'][0]['procedure_id'] == p['id'] == i['procedure_id']
    assert all(p['site_id'] == 'plant-a' for p in pack['procedures'])


def test_restart_retains_records(tmp_path):
    path = str(tmp_path / 'persistent.db')
    with TestClient(create_app(path, 'key')) as c:
        c.headers['X-API-Key'] = 'key'
        setup_records(c)
    with TestClient(create_app(path, 'key')) as c:
        assert len(c.get('/v1/assets?site_id=plant-a', headers={'X-API-Key': 'key'}).json()) == 1


def test_duplicate_step_ids_rejected(client):
    _, p = setup_records(client)
    body = {k: v for k, v in p.items() if k != 'id'}
    body['steps'] = body['steps'] * 2
    assert client.post('/v1/procedures', json=body).status_code == 422


def test_asset_metadata_update_conflict_and_history(client):
    a, _ = setup_records(client)
    route = f"/v1/sites/plant-a/assets/{a['id']}"
    assert a['revision'] == 1
    body = {'expected_revision': 1, 'reason': 'Moved during layout change', 'location': 'Bay 2'}
    result = client.patch(route, json=body)
    assert result.status_code == 200, result.text
    assert result.json()['revision'] == 2
    assert result.json()['location'] == 'Bay 2'
    stale = client.patch(route, json={**body, 'location': 'Bay 3'})
    assert stale.status_code == 409
    assert stale.json()['detail']['current_revision'] == 2
    assert client.get(route).json()['location'] == 'Bay 2'
    assert client.get('/v1/assets?site_id=plant-a').json()[0]['revision'] == 2
    assert client.get('/v1/sites/plant-a/pack').json()['assets'][0]['revision'] == 2
    events = client.get('/v1/sites/plant-a/audit', params={
        'entity_id': a['id'], 'kind': 'asset.updated'}).json()
    assert len(events) == 1
    payload = events[0]['payload']
    assert payload == {'reason': body['reason'], 'previous_revision': 1, 'revision': 2,
                       'changes': {'location': {'before': 'Bay 1', 'after': 'Bay 2'}}}
    assert client.get('/v1/sites/plant-a/audit', params={
        'entity_id': a['id'], 'after': events[0]['sequence']}).json() == []
    assert client.get('/v1/sites/plant-b/audit', params={'entity_id': a['id']}).json() == []
    assert client.get('/v1/sites/plant-a/audit', params={
        'kind': "asset.updated' OR 1=1 --"}).json() == []


def test_asset_metadata_update_scope_validation_and_noop(client):
    a, _ = setup_records(client)
    route = f"/v1/sites/plant-a/assets/{a['id']}"
    body = {'expected_revision': 1, 'reason': 'Review', 'location': 'Bay 1'}
    assert client.patch(route.replace('plant-a', 'plant-b'), json=body).status_code == 404
    assert client.get(route.replace('plant-a', 'plant-b')).status_code == 404
    for invalid in ({'location': None}, {'reason': ' '}, {'expected_revision': 0},
                    {'tag': 'P-200'}, {'manufacturer': 'Other'}):
        assert client.patch(route, json={**body, **invalid}).status_code == 422
    assert client.patch(route, json={'expected_revision': 1, 'reason': 'Empty edit'}).status_code == 422
    assert client.patch(route, json=body).json()['revision'] == 1
    assert client.get('/v1/sites/plant-a/audit', params={'kind': 'asset.updated'}).json() == []
    changed = client.patch(route, json={**body, 'category': 'centrifugal pump'})
    assert changed.json()['revision'] == 2
    assert changed.json()['tag'] == a['tag']
    assert client.patch(route, json={**body, 'expected_revision': 2,
                                    'category': 'centrifugal pump'}).json()['revision'] == 2
