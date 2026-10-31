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


def test_passage_cache_survives_retriever_restart_and_model_change(client, tmp_path, monkeypatch):
    model_dir = tmp_path / 'encoder-artifacts'
    model_dir.mkdir()
    artifact = model_dir / 'weights.bin'
    artifact.write_bytes(b'revision-one')
    monkeypatch.setenv('POSIFY_EMBEDDING_DIR', str(model_dir))
    calls = []
    class Encoder:
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return [[1.0, 0.0] for _ in texts]
    def retriever():
        r = HybridRetriever(database=client.app.state.database)
        r._model = Encoder()
        r.readiness = lambda: {'artifact_present': True, 'dependency_present': True}
        return r
    sources = [dict(id='first', source_text='Oscillation reference', version=1, title='First')]
    first = retriever()
    first.search(sources, 'vibration')
    assert calls[-1] == ['query: vibration', 'passage: Oscillation reference']
    second = retriever()
    # Same passage vector, but the returned identity comes from this request's scoped source.
    result = second.search([{**sources[0], 'id': 'other-factory-source'}], 'vibration')
    assert calls[-1] == ['query: vibration']
    assert result[0]['procedure_id'] == 'other-factory-source'
    artifact.write_bytes(b'revision-two')
    third = retriever()
    third.search(sources, 'vibration')
    assert calls[-1] == ['query: vibration', 'passage: Oscillation reference']
    assert first._namespace != third._namespace


def test_corrupt_cached_vector_is_recomputed(client, tmp_path, monkeypatch):
    import hashlib
    monkeypatch.setenv('POSIFY_EMBEDDING_DIR', str(tmp_path / 'model'))
    (tmp_path / 'model').mkdir()
    r = HybridRetriever(database=client.app.state.database)
    r.readiness = lambda: {'artifact_present': True, 'dependency_present': True}
    calls = []
    class Encoder:
        def encode(self, texts, **kwargs):
            calls.append(texts)
            return [[1.0, 0.0] for _ in texts]
    r._model = Encoder()
    source = dict(id='one', source_text='Oscillation', version=1, title='One')
    namespace = r._cache_namespace()
    digest = hashlib.sha256(b'Oscillation').hexdigest()
    with client.app.state.database.connect() as db:
        db.execute('INSERT INTO embedding_cache VALUES(?,?,?)', (namespace, digest, '[0,0,1]'))
    assert r.search([source], 'vibration')[0]['procedure_id'] == 'one'
    assert calls[-1] == ['passage: Oscillation']
