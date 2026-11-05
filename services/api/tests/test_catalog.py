from uuid import uuid4

import pytest

from test_api import client, setup_records


def create_model(c, **overrides):
    body = dict(manufacturer='Example', model='M1', variant='base', category='pump', source_ref='Manufacturer reference A')
    return c.post('/v1/catalog/models', json={**body, **overrides})


def publish(c, model):
    return c.post(f"/v1/catalog/models/{model['id']}/publish")


def test_factory_registration_and_unknown_factory(client):
    a, _ = setup_records(client)
    data = {k: v for k, v in a.items() if k not in {'id', 'revision'}}
    assert client.post('/v1/assets', json={**data, 'site_id': 'not-registered'}).status_code == 404
    org = client.post('/v1/organizations', json={'name': 'Factory owner'}).json()
    body = {'id': 'plant-c', 'organization_id': org['id'], 'name': 'Plant C'}
    assert client.post('/v1/factories', json=body).status_code == 201
    assert client.post('/v1/factories', json=body).status_code == 409
    assert client.post('/v1/factories', json={**body, 'id': 'plant-d', 'organization_id': str(uuid4())}).status_code == 404
    factories = client.get('/v1/factories', params={'organization_id': org['id']}).json()
    assert [f['id'] for f in factories] == ['plant-c']


def test_catalogue_review_uniqueness_and_search(client):
    model = create_model(client).json()
    assert model['status'] == 'draft'
    assert client.get('/v1/catalog/models').json() == []
    assert create_model(client, manufacturer='EXAMPLE', model='m1').status_code == 409
    assert publish(client, model).status_code == 200
    assert publish(client, model).status_code == 200
    assert len(client.get('/v1/catalog/models?q=exam').json()) == 1
    assert client.get('/v1/catalog/models?q=%25').json() == []


def test_factory_assets_share_model_not_history(client):
    a, _ = setup_records(client)
    b, _ = setup_records(client, site='plant-b')
    model = create_model(client).json()
    body = {'catalog_model_id': model['id'], 'asset_confirmed': True}
    path_a = f"/v1/sites/plant-a/assets/{a['id']}/catalog-link"
    assert client.post(path_a, json=body).status_code == 409
    publish(client, model)
    assert client.post(path_a, json={**body, 'asset_confirmed': False}).status_code == 422
    first = client.post(path_a, json=body)
    assert first.status_code == 200
    assert client.post(path_a, json=body).json() == first.json()
    assert client.post(f"/v1/sites/plant-b/assets/{b['id']}/catalog-link", json=body).status_code == 200
    assert client.get(path_a.replace('plant-a', 'plant-b')).status_code == 404
    assert client.get('/v1/catalog/models').json()[0]['id'] == model['id']
    # Published model data contains neither factory serials nor inspection history.
    assert 'serial' not in client.get('/v1/catalog/models').json()[0]


def test_unlinked_asset_is_distinct_from_missing_asset(client):
    asset, _ = setup_records(client)
    path = f"/v1/sites/plant-a/assets/{asset['id']}/catalog-link"
    assert client.get(path).status_code == 200
    assert client.get(path).json() is None
    assert client.get(f"/v1/sites/plant-a/assets/{uuid4()}/catalog-link").status_code == 404


def test_wrong_model_and_reassignment_rejected(client):
    a, _ = setup_records(client)
    model = create_model(client, model='OTHER').json()
    publish(client, model)
    path = f"/v1/sites/plant-a/assets/{a['id']}/catalog-link"
    assert client.post(path, json={'catalog_model_id': model['id'], 'asset_confirmed': True}).status_code == 409
    model = create_model(client).json()
    publish(client, model)
    assert client.post(path, json={'catalog_model_id': model['id'], 'asset_confirmed': True}).status_code == 200
    variant = create_model(client, variant='revision-b').json()
    publish(client, variant)
    assert client.post(path, json={'catalog_model_id': variant['id'], 'asset_confirmed': True}).status_code == 409


def test_global_document_revisions_and_publication(client):
    model = create_model(client).json()
    path = f"/v1/catalog/models/{model['id']}/documents"
    body = dict(title='Manual', revision=1, source_text='Manufacturer-approved reference text.', source_ref='Manual A page 1')
    doc = client.post(path, json=body).json()
    assert client.get(path).json() == []
    assert client.post(f"/v1/catalog/documents/{doc['id']}/publish").status_code == 409
    publish(client, model)
    assert client.post(f"/v1/catalog/documents/{doc['id']}/publish").status_code == 200
    assert client.post(path, json=body).status_code == 409
    assert client.post(path, json={**body, 'revision': 2}).status_code == 201
    assert len(client.get(path).json()) == 1
    assert len(client.get(path, params={'include_drafts': True}).json()) == 2


def test_catalogue_authentication(client):
    assert client.get('/v1/catalog/models', headers={'X-API-Key': 'wrong'}).status_code == 401


def test_assistant_keeps_global_sources_distinct_and_factory_scoped(client):
    a, _ = setup_records(client)
    b, _ = setup_records(client, site='plant-b')
    model = create_model(client).json()
    publish(client, model)
    path = f"/v1/catalog/models/{model['id']}/documents"
    doc = client.post(path, json=dict(title='Manual', revision=1, source_text='Bearing oscillation reference.',
                                     source_ref='Manufacturer manual page 12')).json()
    client.post(f"/v1/catalog/documents/{doc['id']}/publish")
    client.post(path, json=dict(title='Manual', revision=2, source_text='Unreviewed bearing oscillation draft.',
                               source_ref='Unreviewed page'))
    client.post(f"/v1/sites/plant-a/assets/{a['id']}/catalog-link",
                json={'catalog_model_id': model['id'], 'asset_confirmed': True})
    result = client.post('/v1/assistant/query', json={'site_id': 'plant-a', 'asset_id': a['id'],
                                                    'question': 'bearing oscillation'}).json()
    assert len(result['sources']) == 1
    source = result['sources'][0]
    assert source['source_kind'] == 'catalog_document'
    assert source['document_id'] == doc['id']
    assert source['procedure_id'] is None
    assert source['version'] == 1
    assert source['source_ref'] == 'Manufacturer manual page 12'
    other = client.post('/v1/assistant/query', json={'site_id': 'plant-b', 'asset_id': b['id'],
                                                   'question': 'bearing oscillation'}).json()
    assert other['sources'] == []
