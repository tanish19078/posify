"""Run against a live local service. Creates isolated, explicitly fictional data."""
import os
from uuid import uuid4

import httpx


def main():
    token = os.environ.get('POSIFY_API_TOKEN')
    if not token:
        raise SystemExit('Set POSIFY_API_TOKEN to the running server token')
    site = 'demo-' + uuid4().hex[:8]
    with httpx.Client(base_url=os.getenv('POSIFY_API_URL', 'http://127.0.0.1:8000'),
                      headers={'X-API-Key': token}, timeout=40, trust_env=False) as c:
        def request(method, path, **kwargs):
            r = c.request(method, path, **kwargs)
            r.raise_for_status()
            return r.json()

        a = request('POST', '/v1/assets', json=dict(site_id=site, tag='P-104',
                    manufacturer='Fictional Training Equipment', model='DEMO-1', serial='TRAINING-001',
                    category='pump', location='Simulated training bay'))
        p = request('POST', '/v1/procedures', json=dict(site_id=site,
                    manufacturer=a['manufacturer'], model=a['model'], title='Training record', version=1,
                    steps=[{'id': 'external', 'instruction': 'Record the training image visibility.'}],
                    source_text='Training image inspection: record whether the external label is readable. '
                    'This fictional procedure is not an operational maintenance instruction.'))
        match = request('POST', '/v1/identify', json={'site_id': site, 'tag': 'P-104'})
        assert match['requires_confirmation']
        print('1. Identifier match returned; technician confirmation required')
        i = request('POST', '/v1/inspections', json=dict(site_id=site, asset_id=a['id'],
                    procedure_id=p['id'], asset_confirmed=True))
        path = '/v1/inspections/' + i['id']
        observation = dict(id=str(uuid4()), site_id=site, step_id='external',
                           result='unknown', note='Illustrative training image not supplied')
        request('POST', path + '/observations', json=observation)
        assert request('POST', path + '/observations', json=observation)['replayed']
        print('2. Observation recorded; retry returned the original without duplication')
        request('POST', path + '/submit', params={'site_id': site})
        print('3. Inspection submitted with unknown finding preserved')
        answer = request('POST', '/v1/assistant/query', json=dict(site_id=site,
                         asset_id=a['id'], question='Describe training image inspection'))
        print('4. Assistant response mode:', answer['mode'])
        pack = request('GET', f'/v1/sites/{site}/pack')
        assert len(pack['observations']) == 1
        events = request('GET', f'/v1/sites/{site}/audit')
        print(f'5. Site pack contains one observation; audit contains {len(events)} events')
        print('Demo completed:', site)


if __name__ == '__main__':
    main()
