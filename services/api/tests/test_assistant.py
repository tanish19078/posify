import json

import httpx

from test_api import client, setup_records


def query(c, a, question='Describe exterior inspection'):
    return c.post('/v1/assistant/query', json={'site_id': a['site_id'], 'asset_id': a['id'], 'question': question})


def test_extractive_default_and_abstention(client):
    a, _ = setup_records(client)
    client.app.state.model_name = ''
    answer = query(client, a).json()
    assert answer['mode'] == 'source_excerpts'
    assert answer['answer'] is None
    assert answer['sources'][0]['version'] == 1
    assert query(client, a, 'unicorn gearbox').json()['mode'] == 'insufficient_evidence'
    assert query(client, {**a, 'site_id': 'other'}).status_code == 404


def test_latest_revision_only(client):
    a, p = setup_records(client)
    client.app.state.model_name = ''
    client.post('/v1/procedures', json={**{k: v for k, v in p.items() if k != 'id'},
                                      'version': 2, 'source_text': 'Exterior inspection: updated instructions.'})
    assert {s['version'] for s in query(client, a).json()['sources']} == {2}


def test_model_payload_and_validated_citations(client):
    a, _ = setup_records(client)
    def handler(request):
        payload = json.loads(request.content)
        assert payload['stream'] is False
        assert 'tools' not in payload
        sources = json.loads(payload['messages'][1]['content'])['sources']
        draft = {'answer': 'Record exterior condition.', 'citations': [sources[0]['id']]}
        return httpx.Response(200, json={'message': {'content': json.dumps(draft)}})
    client.app.state.model_name = 'configured-local-model'
    client.app.state.model_transport = httpx.MockTransport(handler)
    r = query(client, a)
    assert r.status_code == 200
    assert r.json()['mode'] == 'model_draft'
    assert r.json()['requires_review']


def test_bad_model_output_is_not_presented(client):
    a, _ = setup_records(client)
    client.app.state.model_name = 'local'
    client.app.state.model_transport = httpx.MockTransport(lambda r: httpx.Response(
        200, json={'message': {'content': json.dumps({'answer': 'Invented', 'citations': ['fake']})}}))
    assert query(client, a).status_code == 502
    client.app.state.model_transport = httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    assert query(client, a).status_code == 502


def test_runtime_failure_is_explicit(client):
    a, _ = setup_records(client)
    client.app.state.model_name = 'local'
    def fail(request):
        raise httpx.ConnectError('unavailable', request=request)
    client.app.state.model_transport = httpx.MockTransport(fail)
    assert query(client, a).status_code == 503
