"""Run public-source images through the API queue, real ONNX inference and Tesseract."""
import argparse
import hashlib
import io
import json
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from posify.app import create_app
from posify.jobs import work_once


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--sources', default=Path('examples/nameplate_sources.json'), type=Path)
    parser.add_argument('--images', default=Path('var/public-nameplates'), type=Path)
    parser.add_argument('--output', default=Path('var/nameplate-integration.json'), type=Path)
    parser.add_argument('--download', action='store_true', help='Fetch the pinned public images with curl')
    args = parser.parse_args()
    sources = json.loads(args.sources.read_text())
    args.images.mkdir(parents=True, exist_ok=True)
    for source in sources:
        path = args.images / (source['id'] + '.jpg')
        if Path(source['id']).name != source['id'] or not source['url'].startswith('https://upload.wikimedia.org/'):
            raise ValueError('Invalid public-source entry')
        if not path.exists() and args.download:
            subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '60',
                            source['url'], '--output', str(path)], check=True)
        if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
            raise ValueError('Public image digest mismatch; review the source before updating its pin')
    os.environ['POSIFY_DETECTOR_MANIFEST'] = str(args.manifest.resolve())
    os.environ['POSIFY_OCR_ENGINE'] = 'tesseract'
    os.environ['POSIFY_AUTH_MODE'] = 'development'
    os.environ['POSIFY_AUTO_MIGRATE'] = 'true'
    rows = []
    with tempfile.TemporaryDirectory(prefix='posify-detector-smoke-') as temporary:
        root = Path(temporary)
        os.environ['POSIFY_CAPTURE_DIR'] = str(root / 'captures')
        os.environ['POSIFY_DOCUMENT_DIR'] = str(root / 'documents')
        app = create_app(str(root / 'smoke.db'), api_token='isolated-smoke-key')
        try:
            with TestClient(app) as client:
                client.headers['X-API-Key'] = 'isolated-smoke-key'
                owner = client.post('/v1/organizations', json={'name': 'Public image integration smoke'}).json()
                created = client.post('/v1/factories', json={'id': 'public-smoke', 'organization_id': owner['id'], 'name': 'Isolated public image smoke'})
                created.raise_for_status()
                for source in sources:
                    with Image.open(args.images / (source['id'] + '.jpg')) as original:
                        image = ImageOps.exif_transpose(original).convert('RGB')
                        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
                        data = io.BytesIO()
                        image.save(data, format='JPEG', quality=95)
                        size = list(image.size)
                    uploaded = client.post('/v1/sites/public-smoke/captures', content=data.getvalue(), headers={'Content-Type': 'image/jpeg'})
                    uploaded.raise_for_status()
                    capture = uploaded.json()['capture']
                    route = f"/v1/sites/public-smoke/captures/{capture['id']}/jobs"
                    queued = client.post(route, json={'id': str(uuid4()), 'mode': 'detect_ocr'})
                    queued.raise_for_status()
                    job_id = queued.json()['id']
                    started = time.perf_counter()
                    assert work_once(app)
                    duration = (time.perf_counter() - started) * 1000
                    job = client.get(f'/v1/sites/public-smoke/jobs/{job_id}').json()
                    if job['status'] != 'succeeded':
                        raise RuntimeError(f"Analysis failed for {source['id']}: {job['error_code']}")
                    result = job['result']
                    assert result['requires_confirmation'] is True
                    timings = []
                    path = app.state.capture_root / (capture['sha256'] + '.png')
                    for _ in range(3):
                        app.state.detector.predict(path)
                        timings.append(app.state.detector.last_inference_ms)
                    rows.append({'source': source, 'normalized_size': size,
                                 'alterations': 'EXIF orientation applied, aspect-preserving resize to at most 1600px, JPEG re-encoding for upload',
                                 'job_status': job['status'], 'detector_revision': result['detector_revision'],
                                 'detections': result['detections'], 'ocr_lines': len(result['lines']),
                                 'identifier_evidence': len(result['identifiers']), 'identity_status': result['status'],
                                 'requires_confirmation': result['requires_confirmation'], 'warnings': result['pipeline_warnings'],
                                 'analysis_wall_ms': round(duration, 3), 'median_warm_inference_ms': statistics.median(timings)})
                    print(source['id'], 'detections:', len(result['detections']), 'OCR lines:', len(result['lines']),
                          'warm ONNX ms:', statistics.median(timings))
                readiness = app.state.detector.readiness()
        finally:
            app.state.database.engine.dispose()
    import onnxruntime as ort
    report = {'purpose': 'public-image integration smoke, not held-out accuracy evaluation',
              'notice': 'No ground-truth boxes supplied; training-set overlap is unknown. No factory assets were seeded or auto-confirmed.',
              'runtime': ort.__version__, 'machine': platform.machine(), 'threads': readiness['threads'],
              'manifest_sha256': hashlib.sha256(args.manifest.read_bytes()).hexdigest(),
              'detector': readiness, 'cases': rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print('Report:', args.output)


if __name__ == '__main__':
    main()
