import time
from uuid import uuid4

from posify.detector import Detection
from posify.jobs import claim_job, finish_job, work_once
from posify.ocr import OCRLine
from test_api import client, setup_records
from test_captures import FakeOCR, upload


def enqueue(c, capture, **overrides):
    return c.post(f"/v1/sites/plant-a/captures/{capture['id']}/jobs",
                  json={'id': str(uuid4()), 'mode': 'ocr', **overrides})


def test_job_replay_scope_and_persistent_worker_result(client):
    setup_records(client)
    capture = upload(client).json()['capture']
    job_id = str(uuid4())
    job = enqueue(client, capture, id=job_id).json()
    assert job['status'] == 'queued'
    assert enqueue(client, capture, id=job_id).json()['id'] == job_id
    assert enqueue(client, capture, id=job_id, mode='detect_ocr').status_code == 409
    assert client.get(f'/v1/sites/plant-b/jobs/{job_id}').status_code == 404
    client.app.state.ocr = FakeOCR([OCRLine(text='TAG: P-104', confidence=.99)])
    assert work_once(client.app)
    result = client.get(f'/v1/sites/plant-a/jobs/{job_id}').json()
    assert result['status'] == 'succeeded'
    assert result['attempts'] == 1
    assert result['result']['status'] == 'candidate_found'
    assert 'claim_token' not in result
    assert not work_once(client.app)
    runs = client.get(f"/v1/sites/plant-a/captures/{capture['id']}/analyses").json()
    assert len(runs) == 1


def test_worker_retries_are_bounded(client):
    capture = upload(client).json()['capture']
    job = enqueue(client, capture).json()
    class Unavailable:
        engine = 'unavailable'
        def recognize(self, _):
            from fastapi import HTTPException
            raise HTTPException(503, 'Unavailable')
    client.app.state.ocr = Unavailable()
    for attempt in range(3):
        with client.app.state.database.connect() as db:
            db.execute('UPDATE analysis_jobs SET available_at=0 WHERE id=?', (job['id'],))
        assert work_once(client.app)
    result = client.get(f"/v1/sites/plant-a/jobs/{job['id']}").json()
    assert result['status'] == 'failed'
    assert result['attempts'] == 3
    assert result['error_code'] == 'component_http_503'
    assert not work_once(client.app)


def test_expired_worker_cannot_publish_result(client):
    capture = upload(client).json()['capture']
    enqueue(client, capture)
    first = claim_job(client.app.state.database)
    assert first is not None
    assert claim_job(client.app.state.database) is None
    with client.app.state.database.connect() as db:
        db.execute('UPDATE analysis_jobs SET lease_until=0 WHERE id=?', (first['id'],))
    second = claim_job(client.app.state.database)
    assert second['claim_token'] != first['claim_token']
    assert finish_job(client.app.state.database, first, error_code='stale') is False
    assert finish_job(client.app.state.database, second, error_code='new-worker') is True


def test_detector_crop_ocr_coordinates_are_returned_in_original_image(client):
    setup_records(client)
    capture = upload(client).json()['capture']
    class Detector:
        def predict(self, path):
            return [Detection(class_id=0, label='nameplate', confidence=.95, box=(100, 50, 300, 150))], 'fixture@1'
    client.app.state.detector = Detector()
    client.app.state.ocr = FakeOCR([OCRLine(text='TAG: P-104', confidence=.99, box=(10, 20, 150, 40))])
    job = enqueue(client, capture, mode='detect_ocr').json()
    assert work_once(client.app)
    result = client.get(f"/v1/sites/plant-a/jobs/{job['id']}").json()['result']
    assert result['lines'][0]['box'] == [110, 70, 250, 90]
    assert result['detector_revision'] == 'fixture@1'
    assert result['inference_mode'] == 'detect_ocr'
    assert result['status'] == 'candidate_found'


def test_no_detections_has_explicit_whole_image_ocr_fallback(client):
    capture = upload(client).json()['capture']
    class Detector:
        def predict(self, path): return [], 'fixture@1'
    client.app.state.detector = Detector()
    client.app.state.ocr = FakeOCR([])
    job = enqueue(client, capture, mode='detect_ocr').json()
    work_once(client.app)
    result = client.get(f"/v1/sites/plant-a/jobs/{job['id']}").json()['result']
    assert result['status'] == 'insufficient_evidence'
    assert result['pipeline_warnings'] == ['no_detections_full_image_ocr']
