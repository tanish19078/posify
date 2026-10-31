import pytest
from fastapi import HTTPException

from posify.retrieval import HybridRetriever
from test_api import client, setup_records


def test_runtime_reports_configuration_not_fake_readiness(client):
    r = client.get('/v1/runtime')
    assert r.status_code == 200
    assert r.json()['detector']['inference_implemented'] is True
    assert r.json()['detector']['loaded'] is False
    assert r.json()['assistant']['inference_verified'] is False
    assert client.get('/v1/runtime', headers={'X-API-Key': 'bad'}).status_code == 401


def test_missing_local_model_is_explicit(monkeypatch):
    monkeypatch.setenv('POSIFY_EMBEDDING_DIR', '/nonexistent/posify-model')
    r = HybridRetriever()
    with pytest.raises(HTTPException) as exc:
        r.search([dict(id='one', source_text='Exterior condition', version=1, title='Inspection')], 'condition')
    assert exc.value.status_code == 503


def test_hybrid_prefixes_ranking_and_scoping(monkeypatch, tmp_path):
    monkeypatch.setenv('POSIFY_EMBEDDING_DIR', str(tmp_path))
    r = HybridRetriever()
    r.readiness = lambda: {'artifact_present': True, 'dependency_present': True}
    class Encoder:
        def encode(self, texts, **kwargs):
            assert texts[0] == 'query: vibration'
            assert all(t.startswith('passage: ') for t in texts[1:])
            assert kwargs['normalize_embeddings']
            return [[1, 0], [1, 0], [0, 1]]
    r._model = Encoder()
    sources = [dict(id='related', source_text='Oscillation inspection', version=1, title='Related'),
               dict(id='unrelated', source_text='Paint colour', version=1, title='Other')]
    result = r.search(sources, 'vibration')
    assert [s['procedure_id'] for s in result] == ['related']


def test_retrieval_mode_is_returned(client, monkeypatch):
    monkeypatch.delenv('POSIFY_EMBEDDING_DIR', raising=False)
    client.app.state.retriever = HybridRetriever()
    a, _ = setup_records(client)
    r = client.post('/v1/assistant/query', json=dict(site_id='plant-a', asset_id=a['id'], question='exterior'))
    assert r.json()['retrieval_method'] == 'lexical'


@pytest.mark.parametrize('value', ['nan', 'inf', '-2', '2'])
def test_invalid_score_setting_rejected(monkeypatch, value):
    monkeypatch.setenv('POSIFY_EMBEDDING_MIN_SCORE', value)
    with pytest.raises(RuntimeError):
        HybridRetriever()
