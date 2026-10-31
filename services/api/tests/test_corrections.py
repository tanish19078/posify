from uuid import uuid4

from test_api import client, setup_records, start
from test_catalog import create_model, publish
from test_captures import upload
from test_security import as_person, person


def linked_asset(c):
    a, p = setup_records(c)
    initial = create_model(c).json()
    publish(c, initial)
    target = create_model(c, variant='variant-b').json()
    publish(c, target)
    path = f"/v1/sites/plant-a/assets/{a['id']}/catalog-link"
    assert c.post(path, json={'catalog_model_id': initial['id'], 'asset_confirmed': True}).status_code == 200
    return a, p, initial, target, path


def test_catalogue_correction_requires_two_people_and_preserves_review_history(client):
    a, _, initial, target, path = linked_asset(client)
    _, manager = person(client, 'manager')
    reviewer, supervisor = person(client, 'supervisor')
    body = {'id': str(uuid4()), 'expected_revision': 1, 'catalog_model_id': target['id'], 'reason': 'Variant confirmed from manufacturer label'}
    route = f"/v1/sites/plant-a/assets/{a['id']}/corrections"
    assert client.post(route, json=body).status_code == 403
    with as_person(client, manager):
        pending = client.post(route, json=body)
        assert pending.status_code == 200, pending.text
        assert pending.json()['status'] == 'pending'
        assert client.post(route, json=body).json() == pending.json()
        assert client.post(route, json={**body, 'reason': 'Changed'}).status_code == 409
        decision = f"/v1/sites/plant-a/corrections/{body['id']}/decision"
        assert client.post(decision, json={'decision': 'approved', 'note': 'Self'}).status_code == 409
    assert client.get(path).json()['catalog_model_id'] == initial['id']
    with as_person(client, supervisor):
        result = client.post(decision, json={'decision': 'approved', 'note': 'Independent label check'})
        assert result.status_code == 200, result.text
        assert result.json()['reviewed_by'] == reviewer['id']
        assert client.post(decision, json={'decision': 'approved', 'note': 'Independent label check'}).json() == result.json()
        assert client.post(decision, json={'decision': 'rejected', 'note': 'Changed'}).status_code == 409
    assert client.get(path).json()['catalog_model_id'] == target['id']
    assert client.get(f"/v1/sites/plant-a/assets/{a['id']}").json()['revision'] == 2
    assert client.get('/v1/sites/plant-a/corrections?status=pending').json() == []
    assert client.get('/v1/sites/plant-a/corrections?status=approved').json()[0]['id'] == body['id']
    event = client.get('/v1/sites/plant-a/audit?kind=correction.approved').json()[0]
    assert event['payload']['before'] == initial['id'] and event['actor_id'] == reviewer['id']


def test_stale_catalogue_correction_cannot_overwrite_new_asset_revision(client):
    a, _, initial, target, path = linked_asset(client)
    _, manager = person(client, 'manager')
    _, supervisor = person(client, 'supervisor')
    body = {'id': str(uuid4()), 'expected_revision': 1, 'catalog_model_id': target['id'], 'reason': 'Correct variant'}
    with as_person(client, manager):
        assert client.post(f"/v1/sites/plant-a/assets/{a['id']}/corrections", json=body).status_code == 200
        assert client.patch(f"/v1/sites/plant-a/assets/{a['id']}", json={
            'expected_revision': 1, 'reason': 'Moved', 'location': 'Bay 2'}).status_code == 200
    decision = f"/v1/sites/plant-a/corrections/{body['id']}/decision"
    with as_person(client, supervisor):
        assert client.post(decision, json={'decision': 'approved', 'note': 'Check'}).status_code == 409
        assert client.post(decision, json={'decision': 'rejected', 'note': 'Stale request'}).status_code == 200
    assert client.get(path).json()['catalog_model_id'] == initial['id']


def test_capture_correction_blocks_attached_evidence_even_if_attached_after_request(client):
    a, p = setup_records(client)
    b = client.post('/v1/assets', json={**{k: v for k, v in a.items() if k not in {'id', 'revision'}},
                                       'tag': 'P-200', 'serial': 'S-200'}).json()
    capture = upload(client).json()['capture']
    base = f"/v1/sites/plant-a/captures/{capture['id']}"
    assert client.post(base + '/confirm', json={'asset_id': a['id'], 'asset_confirmed': True}).status_code == 200
    _, manager = person(client, 'manager')
    _, supervisor = person(client, 'supervisor')
    body = {'id': str(uuid4()), 'asset_id': b['id'], 'reason': 'Wrong initial assignment'}
    with as_person(client, manager):
        assert client.post(base + '/corrections', json=body).status_code == 200
    inspection = start(client, a, p).json()
    assert client.post(f"/v1/sites/plant-a/inspections/{inspection['id']}/evidence", json={'capture_id': capture['id']}).status_code == 200
    with as_person(client, supervisor):
        assert client.post(f"/v1/sites/plant-a/corrections/{body['id']}/decision",
                           json={'decision': 'approved', 'note': 'Check'}).status_code == 409
    with as_person(client, manager):
        assert client.post(base + '/corrections', json={**body, 'id': str(uuid4())}).status_code == 409
    assert client.post(base + '/confirm', json={'asset_id': a['id'], 'asset_confirmed': True}).json()['asset_id'] == a['id']


def test_unattached_capture_can_be_corrected_but_not_to_another_factory(client):
    a, _ = setup_records(client)
    foreign, _ = setup_records(client, site='plant-b')
    b = client.post('/v1/assets', json={**{k: v for k, v in a.items() if k not in {'id', 'revision'}},
                                       'tag': 'P-200', 'serial': 'S-200'}).json()
    capture = upload(client).json()['capture']
    base = f"/v1/sites/plant-a/captures/{capture['id']}"
    client.post(base + '/confirm', json={'asset_id': a['id'], 'asset_confirmed': True})
    _, manager = person(client, 'manager')
    _, supervisor = person(client, 'supervisor')
    body = {'id': str(uuid4()), 'asset_id': b['id'], 'reason': 'Independent identifier check'}
    with as_person(client, manager):
        assert client.post(base + '/corrections', json={**body, 'asset_id': foreign['id']}).status_code == 404
        assert client.post(base + '/corrections', json=body).status_code == 200
    with as_person(client, supervisor):
        assert client.post(f"/v1/sites/plant-a/corrections/{body['id']}/decision",
                           json={'decision': 'approved', 'note': 'Verified serial'}).status_code == 200
    assert client.post(base + '/confirm', json={'asset_id': b['id'], 'asset_confirmed': True}).json()['asset_id'] == b['id']
