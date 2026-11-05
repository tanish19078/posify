import io
import os

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from test_api import client, setup_records
from test_catalog import create_model, publish
from test_security import person, as_person


def pdf_bytes(texts, encrypted=False):
    writer = PdfWriter()
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                             NameObject('/BaseFont'): NameObject('/Helvetica')})
    for text in texts:
        page = writer.add_blank_page(width=300, height=200)
        if text:
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
            stream = DecodedStreamObject()
            stream.set_data(('BT /F1 12 Tf 20 150 Td (' + text + ') Tj ET').encode('ascii'))
            page[NameObject('/Contents')] = stream
    if encrypted:
        writer.encrypt('private')
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def import_pdf(c, model_id, raw, **overrides):
    return c.post(f'/v1/catalog/models/{model_id}/pdf',
                  params={'title': 'Manual', 'revision': 1, 'source_ref': 'Manufacturer manual', **overrides},
                  headers={'Content-Type': 'application/pdf'}, content=raw)


@pytest.mark.skipif(os.name == 'nt', reason='PDF resource isolation requires Unix')
def test_pdf_draft_publication_download_and_page_level_retrieval(client):
    a, _ = setup_records(client)
    model = create_model(client).json()
    viewer, token = person(client, 'viewer')
    raw = pdf_bytes(['', 'Bearing oscillation reference for inspection.'])
    result = import_pdf(client, model['id'], raw)
    assert result.status_code == 201, result.text
    imported = result.json()
    assert imported['page_count'] == 2 and imported['empty_pages'] == [1]
    document = imported['document']
    assert document['status'] == 'draft'
    original = f"/v1/catalog/documents/{document['id']}/pdf"
    with as_person(client, token):
        assert client.get(original).status_code == 404
        assert import_pdf(client, model['id'], raw).status_code == 403
    assert client.get(original).content == raw
    assert 'attachment' in client.get(original).headers['content-disposition']
    publish(client, model)
    assert client.post(f"/v1/catalog/documents/{document['id']}/publish").status_code == 200
    client.post(f"/v1/sites/plant-a/assets/{a['id']}/catalog-link", json={'catalog_model_id': model['id'], 'asset_confirmed': True})
    with as_person(client, token):
        downloaded = client.get(original)
        assert downloaded.status_code == 200 and downloaded.content == raw
        result = client.post('/v1/assistant/query', json={'site_id': 'plant-a', 'asset_id': a['id'], 'question': 'bearing oscillation'}).json()
    source = result['sources'][0]
    assert source['document_id'] == document['id'] and source['page_number'] == 2
    assert ':p2:' in source['id']
    assert import_pdf(client, model['id'], raw).status_code == 409


@pytest.mark.parametrize('raw,status', [
    (b'not PDF', 422), (b'%PDF-1.7\nbroken', 422),
    (pdf_bytes(['']), 422), (pdf_bytes(['Text'], encrypted=True), 422),
    (pdf_bytes(['x' * 30001]), 413), (pdf_bytes([''] * 101), 413),
])
@pytest.mark.skipif(os.name == 'nt', reason='PDF resource isolation requires Unix')
def test_pdf_resource_and_content_limits(client, raw, status):
    model = create_model(client).json()
    response = import_pdf(client, model['id'], raw)
    assert response.status_code == status, response.text
    assert client.get(f"/v1/catalog/models/{model['id']}/documents?include_drafts=true").json() == []


def test_pdf_stream_byte_limit_and_media_type(client):
    model = create_model(client).json()
    assert import_pdf(client, model['id'], b'%PDF-' + b'x' * (8 * 1024 * 1024)).status_code == 413
    assert client.post(f"/v1/catalog/models/{model['id']}/pdf", params={'title': 'M', 'revision': 1, 'source_ref': 'R'},
                       headers={'Content-Type': 'text/plain'}, content=b'hello').status_code == 415
