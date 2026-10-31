from uuid import uuid4

import pytest

from test_api import client, setup_records, start
from test_security import as_person, person


def submit_as(c, credential, a, p, result='pass'):
    with as_person(c, credential):
        response = start(c, a, p)
        assert response.status_code == 201, response.text
        inspection = response.json()
        base = f"/v1/inspections/{inspection['id']}"
        assert c.post(base + '/observations', json={'id': str(uuid4()), 'site_id': a['site_id'],
            'step_id': 'exterior', 'result': result}).status_code == 200
        assert c.post(base + '/submit', params={'site_id': a['site_id']}).status_code == 200
    return inspection


@pytest.mark.parametrize('result', ['pass', 'fail', 'unknown'])
def test_independent_review_followup_and_replay(client, result):
    a, p = setup_records(client)
    creator, tech = person(client)
    reviewer, supervisor = person(client, 'supervisor')
    inspection = submit_as(client, tech, a, p, result)
    route = f"/v1/sites/plant-a/inspections/{inspection['id']}/reviews"
    body = {'id': str(uuid4()), 'outcome': 'accepted', 'note': 'Reviewed the evidence'}
    assert client.post(route, json=body).status_code == 403
    assert len(client.get('/v1/inspections?site_id=plant-a&unreviewed=true').json()) == 1
    with as_person(client, supervisor):
        if result != 'pass':
            assert client.post(route, json=body).status_code == 409
            body['outcome'] = 'follow_up'
        first = client.post(route, json=body)
        assert first.status_code == 200, first.text
        assert not first.json()['replayed']
        assert first.json()['review']['reviewer_id'] == reviewer['id']
        assert client.post(route, json=body).json()['replayed']
        assert client.post(route, json={**body, 'note': 'Changed'}).status_code == 409
        assert client.post(route.replace('plant-a', 'plant-b'), json=body).status_code == 403
    assert client.get('/v1/inspections?site_id=plant-a&unreviewed=true').json() == []
    assert len(client.get(route).json()) == 1
    detail = client.get(f"/v1/inspections/{inspection['id']}?site_id=plant-a").json()
    assert detail['created_by'] == detail['submitted_by'] == creator['id']
    assert detail['status'] == 'submitted' and detail['observations'][0]['result'] == result
    event = client.get('/v1/sites/plant-a/audit', params={'kind': 'inspection.reviewed'}).json()[0]
    assert event['actor_id'] == reviewer['id']


def test_review_rejects_self_review_and_open_inspection(client):
    a, p = setup_records(client)
    _, supervisor = person(client, 'supervisor')
    _, other = person(client, 'supervisor')
    inspection = submit_as(client, supervisor, a, p)
    route = f"/v1/sites/plant-a/inspections/{inspection['id']}/reviews"
    body = {'id': str(uuid4()), 'outcome': 'accepted', 'note': 'Checked'}
    with as_person(client, supervisor):
        assert client.post(route, json=body).status_code == 409
        opened = start(client, a, p).json()
    with as_person(client, other):
        assert client.post(route.replace(inspection['id'], opened['id']), json=body).status_code == 409
        assert client.post(route, json={**body, 'note': ' '}).status_code == 422


def test_observation_author_cannot_review_even_when_creator_and_submitter_differ(client):
    a, p = setup_records(client)
    _, technician = person(client)
    _, supervisor = person(client, 'supervisor')
    with as_person(client, technician):
        inspection = start(client, a, p).json()
    with as_person(client, supervisor):
        assert client.post(f"/v1/inspections/{inspection['id']}/observations", json={
            'id': str(uuid4()), 'site_id': 'plant-a', 'step_id': 'exterior', 'result': 'pass'}).status_code == 200
    with as_person(client, technician):
        assert client.post(f"/v1/inspections/{inspection['id']}/submit?site_id=plant-a").status_code == 200
    with as_person(client, supervisor):
        assert client.post(f"/v1/sites/plant-a/inspections/{inspection['id']}/reviews", json={
            'id': str(uuid4()), 'outcome': 'accepted', 'note': 'Self-authored observation'}).status_code == 409
