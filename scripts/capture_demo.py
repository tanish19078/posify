"""Exercise real OCR -> confirmation -> inspection evidence. No training data output."""
import io
import os
from uuid import uuid4

import httpx
from PIL import Image, ImageDraw, ImageFont


def main():
    token = os.environ.get('POSIFY_API_TOKEN')
    if not token:
        raise SystemExit('Set POSIFY_API_TOKEN to the running server token')
    image = Image.new('RGB', (1400, 300), 'white')
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=56)
    draw.text((30, 30), 'ASSET TAG: P-104', fill='black', font=font)
    draw.text((30, 140), 'SERIAL: S-001', fill='black', font=font)
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    site = 'capture-demo-' + uuid4().hex[:8]
    with httpx.Client(base_url=os.getenv('POSIFY_API_URL', 'http://127.0.0.1:8000'),
                      headers={'X-API-Key': token}, trust_env=False, timeout=60) as client:
        def call(method, path, **kwargs):
            r = client.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()
        runtime = call('GET', '/v1/runtime')
        if not runtime['ocr']['configured']:
            raise SystemExit('Enable a local OCR engine on the server before running this walkthrough')
        asset = call('POST', '/v1/assets', json=dict(site_id=site, tag='P-104',
                     manufacturer='Fictional Training Equipment', model='DEMO-1', serial='S-001',
                     category='pump', location='Simulated inspection bay'))
        procedure = call('POST', '/v1/procedures', json=dict(site_id=site,
                         manufacturer=asset['manufacturer'], model=asset['model'],
                         title='Synthetic nameplate review', version=1,
                         steps=[dict(id='label', instruction='Record synthetic label readability.')],
                         source_text='Synthetic demonstration only: record nameplate readability. '
                         'This is not an operational maintenance procedure.'))
        capture_route = f'/v1/sites/{site}/captures'
        receipt = call('POST', capture_route, content=buffer.getvalue(), headers={'Content-Type': 'image/png'})
        capture = receipt['capture']
        route = capture_route + '/' + capture['id']
        assert call('POST', capture_route, content=buffer.getvalue(),
                    headers={'Content-Type': 'image/png'})['replayed']
        analysis = call('POST', route + '/analyze')
        assert analysis['status'] == 'candidate_found', analysis
        assert analysis['candidates'][0]['id'] == asset['id']
        print('Real OCR engine:', analysis['engine'])
        print('Synthetic tag/serial matched, pending explicit confirmation')
        call('POST', route + '/confirm', json={'asset_id': asset['id'], 'asset_confirmed': True})
        inspection = call('POST', '/v1/inspections', json=dict(site_id=site,
                          asset_id=asset['id'], procedure_id=procedure['id'], asset_confirmed=True))
        evidence_route = f"/v1/sites/{site}/inspections/{inspection['id']}/evidence"
        call('POST', evidence_route, json={'capture_id': capture['id']})
        call('POST', evidence_route, json={'capture_id': capture['id']})
        call('POST', f"/v1/inspections/{inspection['id']}/observations", json=dict(
             id=str(uuid4()), site_id=site, step_id='label', result='pass', note='Synthetic label readable'))
        call('POST', f"/v1/inspections/{inspection['id']}/submit", params={'site_id': site})
        pack = call('GET', f'/v1/sites/{site}/pack')
        assert pack['schema_version'] == 2
        assert len(pack['captures']) == len(pack['capture_assignments']) == len(pack['inspection_evidence']) == 1
        print('Confirmation, evidence replay, submission and site-pack export passed')
        print('Completed synthetic walkthrough:', site)


if __name__ == '__main__':
    main()
