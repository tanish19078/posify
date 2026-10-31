"""Browser-facing listings preserve membership boundaries and pagination."""
from test_api import client, setup_records
from test_captures import upload
from test_security import as_person, person


def test_workspace_discovery_only_returns_authorized_factories(client):
    assert {row['id'] for row in client.get('/v1/workspaces').json()} == {'plant-a', 'plant-b'}
    user, token = person(client, 'viewer')
    with as_person(client, token):
        assert [row['id'] for row in client.get('/v1/workspaces').json()] == ['plant-a']
    client.delete(f"/v1/access/users/{user['id']}/factories/plant-a")
    with as_person(client, token):
        assert client.get('/v1/workspaces').json() == []


def test_capture_history_and_assignment_are_scoped_and_bounded(client):
    asset, _ = setup_records(client)
    capture = upload(client).json()['capture']
    upload(client, 'plant-b')
    _, credential = person(client, 'viewer')
    with as_person(client, credential):
        route = '/v1/sites/plant-a/captures'
        assert [row['id'] for row in client.get(route).json()] == [capture['id']]
        assert client.get(route + '?offset=1&limit=1').json() == []
        assert client.get(route + '?limit=201').status_code == 422
        assert client.get(f"{route}/{capture['id']}/confirm").json() is None
        assert client.get('/v1/sites/plant-b/captures').status_code == 403
        assert client.get(f"/v1/sites/plant-b/captures/{capture['id']}/confirm").status_code == 403
        assert client.post(f"{route}/{capture['id']}/confirm", json={
            'asset_id': asset['id'], 'asset_confirmed': True}).status_code == 403
    client.post(f"/v1/sites/plant-a/captures/{capture['id']}/confirm", json={
        'asset_id': asset['id'], 'asset_confirmed': True}).raise_for_status()
    with as_person(client, credential):
        assert client.get(f"/v1/sites/plant-a/captures/{capture['id']}/confirm").json()['asset_id'] == asset['id']


def test_procedure_list_is_membership_scoped(client):
    _, procedure = setup_records(client)
    setup_records(client, site='plant-b')
    _, token = person(client, 'viewer')
    with as_person(client, token):
        assert [p['id'] for p in client.get('/v1/procedures?site_id=plant-a').json()] == [procedure['id']]
        assert client.get('/v1/procedures?site_id=plant-a&offset=1').json() == []
        assert client.get('/v1/procedures?site_id=plant-b').status_code == 403
        assert client.get('/v1/procedures?site_id=plant-a&limit=201').status_code == 422
