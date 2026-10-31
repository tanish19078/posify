from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from posify.app import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(str(tmp_path / 'test.db'), 'test-key')) as c:
        c.headers['X-API-Key'] = 'test-key'
        yield c


def setup_records(c, site='plant-a', model='M1', version=1):
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
    assert client.post('/v1/assets', json={k: v for k, v in a.items() if k != 'id'}).status_code == 409
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
