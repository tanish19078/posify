import io
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from PIL import Image, PngImagePlugin

from test_api import client, setup_records
from posify.captures import MAX_UPLOAD
from posify.matching import extract_identifiers
from posify.ocr import LocalOCR, OCRLine, parse_tsv


def image_bytes(size=(640, 360), metadata=False):
    image = Image.new('RGB', size, 'white')
    output = io.BytesIO()
    info = PngImagePlugin.PngInfo()
    if metadata:
        info.add_text('private-site-note', 'must be removed')
    image.save(output, format='PNG', pnginfo=info)
    return output.getvalue()


def upload(c, site='plant-a', data=None):
    return c.post(f'/v1/sites/{site}/captures', content=data if data is not None else image_bytes(),
                  headers={'Content-Type': 'image/png'})


class FakeOCR:
    engine = 'fixture'
    def __init__(self, lines): self.lines = lines
    def recognize(self, image):
        assert image.is_file()
        return self.lines


def test_capture_sanitization_replay_and_site_scope(client):
    first = upload(client, data=image_bytes(metadata=True))
    assert first.status_code == 200
    capture = first.json()['capture']
    assert not first.json()['replayed']
    assert upload(client).json()['replayed']
    route = f"/v1/sites/plant-a/captures/{capture['id']}"
    image = client.get(route + '/image')
    assert image.headers['content-type'] == 'image/png'
    assert 'private-site-note' not in Image.open(io.BytesIO(image.content)).info
    assert client.get(route.replace('plant-a', 'plant-b')).status_code == 404
    assert client.get(route.replace('plant-a', 'plant-b') + '/image').status_code == 404
    assert client.get(route + '/image', headers={'X-API-Key': 'bad'}).status_code == 401
    other = upload(client, site='plant-b').json()['capture']
    assert other['id'] != capture['id']
    events = client.get('/v1/sites/plant-a/audit').json()
    assert len([e for e in events if e['kind'] == 'capture.created']) == 1


@pytest.mark.parametrize('data,media,status', [
    (b'not an image', 'image/png', 422),
    (b'', 'image/png', 413),
    (b'hello', 'text/plain', 415),
    (image_bytes(), 'image/jpeg', 415),
    (b'x' * (MAX_UPLOAD + 1), 'image/png', 413),
    (image_bytes((4097, 1)), 'image/png', 413),
])
def test_bad_uploads_rejected(client, data, media, status):
    r = client.post('/v1/sites/plant-a/captures', content=data, headers={'Content-Type': media})
    assert r.status_code == status


def test_chunked_upload_size_is_bounded(client):
    r = client.post('/v1/sites/plant-a/captures', content=iter([b'x' * MAX_UPLOAD, b'x']),
                    headers={'Content-Type': 'image/png'})
    assert r.status_code == 413


def test_ocr_matching_and_analysis_history(client):
    a, _ = setup_records(client)
    capture = upload(client).json()['capture']
    client.app.state.ocr = FakeOCR([OCRLine(text='ASSET TAG: P-104', confidence=.98),
                                    OCRLine(text='Serial No: S-001', confidence=.96)])
    route = f"/v1/sites/plant-a/captures/{capture['id']}"
    result = client.post(route + '/analyze').json()
    assert result['status'] == 'candidate_found'
    assert result['candidates'][0]['id'] == a['id']
    assert result['requires_confirmation']
    assert result['identifiers'][0]['line_index'] == 0
    assert len(client.get(route + '/analyses').json()) == 1
    assert client.post(route.replace('plant-a', 'plant-b') + '/analyze').status_code == 404
    assert client.get('/v1/sites/plant-a/pack').json()['inspections'] == []


@pytest.mark.parametrize('lines,status', [
    ([OCRLine(text='TAG: P-104', confidence=.2)], 'insufficient_evidence'),
    ([OCRLine(text='TAG: P-104', confidence=.99), OCRLine(text='SERIAL: WRONG', confidence=.99)], 'no_match'),
    ([OCRLine(text='TAG: P-104 TAG: P-105', confidence=.99)], 'ambiguous_identifiers'),
    ([OCRLine(text='A pump that looks familiar', confidence=.99)], 'insufficient_evidence'),
])
def test_ocr_does_not_guess(client, lines, status):
    setup_records(client)
    capture = upload(client).json()['capture']
    client.app.state.ocr = FakeOCR(lines)
    r = client.post(f"/v1/sites/plant-a/captures/{capture['id']}/analyze")
    assert r.json()['status'] == status
    assert r.json()['candidates'] == []


def test_disabled_ocr_is_explicit(client, monkeypatch):
    monkeypatch.setenv('POSIFY_OCR_ENGINE', 'disabled')
    client.app.state.ocr = LocalOCR()
    capture = upload(client).json()['capture']
    route = f"/v1/sites/plant-a/captures/{capture['id']}"
    assert client.post(route + '/analyze').status_code == 503
    assert client.get(route + '/analyses').json() == []


def test_identifier_characters_are_not_corrected():
    ids = extract_identifiers([OCRLine(text='Serial: S-OO1', confidence=.99)])
    assert ids[0]['value'] == 'S-OO1'


def test_tesseract_confidence_uses_weakest_word():
    tsv = 'page_num\tblock_num\tpar_num\tline_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    tsv += '1\t1\t1\t1\t0\t0\t10\t10\t99\tTAG:\n'
    tsv += '1\t1\t1\t1\t12\t0\t20\t10\t30\tP-104\n'
    lines = parse_tsv(tsv)
    assert lines[0].box == (0, 0, 32, 10)
    assert extract_identifiers(lines) == []


@pytest.mark.skipif(not shutil.which('tesseract'), reason='Optional local Tesseract binary not installed')
def test_real_tesseract_reads_synthetic_label(client, monkeypatch):
    from PIL import ImageDraw, ImageFont
    font_path = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not font_path.exists():
        pytest.skip('Smoke-test font unavailable')
    image = Image.new('RGB', (1400, 300), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype(str(font_path), 56)
    draw.text((30, 30), 'ASSET TAG: P-104', fill='black', font=font)
    draw.text((30, 140), 'SERIAL: S-001', fill='black', font=font)
    data = io.BytesIO()
    image.save(data, format='PNG')
    setup_records(client)
    monkeypatch.setenv('POSIFY_OCR_ENGINE', 'tesseract')
    client.app.state.ocr = LocalOCR()
    capture = upload(client, data=data.getvalue()).json()['capture']
    r = client.post(f"/v1/sites/plant-a/captures/{capture['id']}/analyze")
    assert r.status_code == 200, r.text
    assert r.json()['engine'] == 'tesseract'
    assert r.json()['status'] == 'candidate_found', r.json()


def test_confirmed_capture_can_be_attached_once(client):
    from test_api import start
    a, p = setup_records(client)
    i = start(client, a, p).json()
    capture = upload(client).json()['capture']
    route = f"/v1/sites/plant-a/captures/{capture['id']}/confirm"
    evidence = f"/v1/sites/plant-a/inspections/{i['id']}/evidence"
    body = {'capture_id': capture['id']}
    assert client.post(evidence, json=body).status_code == 409
    assert client.post(route, json={'asset_id': a['id'], 'asset_confirmed': False}).status_code == 422
    first = client.post(route, json={'asset_id': a['id'], 'asset_confirmed': True})
    assert first.status_code == 200
    assert client.post(route, json={'asset_id': a['id'], 'asset_confirmed': True}).json() == first.json()
    assert client.post(evidence, json=body).status_code == 200
    assert client.post(evidence, json=body).status_code == 200
    detail = client.get(f"/v1/inspections/{i['id']}?site_id=plant-a").json()
    assert detail['capture_ids'] == [capture['id']]
    pack = client.get('/v1/sites/plant-a/pack').json()
    assert pack['schema_version'] == 2
    assert len(pack['captures']) == len(pack['capture_assignments']) == len(pack['inspection_evidence']) == 1
    assert client.get('/v1/sites/plant-b/pack').json()['captures'] == []
    audit = client.get('/v1/sites/plant-a/audit').json()
    assert len([e for e in audit if e['kind'] == 'inspection.evidence_attached']) == 1


def test_capture_assignment_cannot_cross_assets_or_sites(client):
    from test_api import start
    a, p = setup_records(client)
    b, _ = setup_records(client, site='plant-b')
    second = client.post('/v1/assets', json={**{k: v for k, v in a.items() if k != 'id'},
                                          'tag': 'P-105', 'serial': 'S-002'}).json()
    capture = upload(client).json()['capture']
    route = f"/v1/sites/plant-a/captures/{capture['id']}/confirm"
    assert client.post(route, json={'asset_id': b['id'], 'asset_confirmed': True}).status_code == 404
    assert client.post(route, json={'asset_id': a['id'], 'asset_confirmed': True}).status_code == 200
    assert client.post(route, json={'asset_id': second['id'], 'asset_confirmed': True}).status_code == 409
    i = start(client, second, p).json()
    assert client.post(f"/v1/sites/plant-a/inspections/{i['id']}/evidence",
                       json={'capture_id': capture['id']}).status_code == 409


def test_submitted_inspection_rejects_new_evidence(client):
    from test_api import start
    from uuid import uuid4
    a, p = setup_records(client)
    i = start(client, a, p).json()
    capture = upload(client).json()['capture']
    client.post(f"/v1/sites/plant-a/captures/{capture['id']}/confirm",
                json={'asset_id': a['id'], 'asset_confirmed': True})
    client.post(f"/v1/inspections/{i['id']}/observations", json=dict(id=str(uuid4()),
                site_id='plant-a', step_id='exterior', result='unknown', note='Unclear'))
    client.post(f"/v1/inspections/{i['id']}/submit?site_id=plant-a")
    assert client.post(f"/v1/sites/plant-a/inspections/{i['id']}/evidence",
                       json={'capture_id': capture['id']}).status_code == 409


def test_concurrent_capture_retries_create_one_record(client):
    def send(_):
        r = upload(client)
        assert r.status_code == 200
        return r.json()['capture']['id']
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(send, range(8)))
    assert len(set(ids)) == 1
    events = client.get('/v1/sites/plant-a/audit').json()
    assert len([e for e in events if e['kind'] == 'capture.created']) == 1
