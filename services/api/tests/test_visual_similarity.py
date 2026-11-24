import hashlib
import sys
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from posify.visual_similarity import (
    LocalVisionEmbedder,
    VisionEmbedderManifest,
    cosine_similarity,
    normalize_embedding,
    preprocess_vision,
    rank_visual_candidates,
)
from test_api import client


def test_preprocess_vision_outputs_normalized_fp32_nchw():
    img = Image.new('RGB', (400, 200), (255, 128, 0))
    tensor = preprocess_vision(img, size=(224, 224))
    assert tensor.shape == (1, 3, 224, 224)
    assert tensor.dtype == np.float32
    assert np.isfinite(tensor).all()


def test_manifest_validation_rejects_bad_format_and_dimensions():
    with pytest.raises(ValidationError):
        VisionEmbedderManifest(
            model_id='vis', revision='1', artifact='m.onnx', sha256='a' * 64,
            format='pt', embedding_dim=128,
        )
    with pytest.raises(ValidationError):
        VisionEmbedderManifest(
            model_id='vis', revision='1', artifact='m.onnx', sha256='a' * 64,
            input_size=(16, 224), embedding_dim=128,
        )


def test_cosine_similarity_and_candidate_ranking_enforces_review_and_threshold():
    q = normalize_embedding([3.0, 4.0, 0.0])
    assert pytest.approx(float(np.linalg.norm(q))) == 1.0
    m1, m2, m3 = uuid4(), uuid4(), uuid4()
    refs = [
        {'catalog_model_id': m1, 'manufacturer': 'SIEMENS', 'model': '1HU3054', 'category': 'Motor', 'embedding': [0.6, 0.8, 0.0]},
        {'catalog_model_id': m2, 'manufacturer': 'ABB', 'model': 'M3BP', 'category': 'Motor', 'embedding': [0.5, 0.85, 0.14]},
        {'catalog_model_id': m3, 'manufacturer': 'KSB', 'model': 'ETANORM', 'category': 'Pump', 'embedding': [0.0, 0.0, 1.0]},
    ]
    ranked = rank_visual_candidates(q, refs, min_similarity=0.75, top_k=5)
    assert [c.catalog_model_id for c in ranked] == [m1, m2]
    assert ranked[0].similarity == pytest.approx(1.0)
    assert all(c.requires_review for c in ranked)
    assert cosine_similarity([1.0, 0.0], [0.0, 1.0]) == 0.0


def test_local_vision_embedder_verifies_digest_and_runs_session(tmp_path, monkeypatch):
    artifact = tmp_path / 'encoder.onnx'
    artifact.write_bytes(b'controlled-vision-encoder')
    manifest = VisionEmbedderManifest(
        model_id='equipment-vision', revision='v1', artifact='encoder.onnx',
        sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
        input_size=(224, 224), embedding_dim=32,
    )
    manifest_file = tmp_path / 'manifest.json'
    manifest_file.write_text(manifest.model_dump_json())
    monkeypatch.setenv('POSIFY_VISION_EMBEDDER_MANIFEST', str(manifest_file))

    class Session:
        def __init__(self, path, sess_options, providers):
            assert providers == ['CPUExecutionProvider']
        def get_inputs(self):
            return [SimpleNamespace(name='image', type='tensor(float)', shape=[1, 3, 224, 224])]
        def get_outputs(self):
            return [SimpleNamespace(type='tensor(float)', shape=[1, 32])]
        def run(self, outputs, inputs):
            return [np.array([[3.0, 4.0] + [0.0] * 30], dtype=np.float32)]

    monkeypatch.setitem(sys.modules, 'onnxruntime', SimpleNamespace(SessionOptions=lambda: SimpleNamespace(), InferenceSession=Session))
    import posify.visual_similarity as mod
    monkeypatch.setattr(mod, 'runtime_version', lambda: '1.31.1')

    embedder = LocalVisionEmbedder()
    embedder.readiness = lambda: {'manifest_present': True, 'runtime_present': True}
    img = tmp_path / 'motor.png'
    Image.new('RGB', (300, 300), 'gray').save(img)
    vec, rev = embedder.embed(img)
    assert rev == 'equipment-vision@v1'
    assert vec == pytest.approx([0.6, 0.8] + [0.0] * 30)
    assert embedder.successful_inferences == 1

    # Tampered weights fail digest check
    artifact.write_bytes(b'tampered')
    embedder.session = None
    with pytest.raises(HTTPException) as exc:
        embedder.embed(img)
    assert exc.value.status_code == 503


def test_runtime_reports_vision_embedder_readiness(client):
    r = client.get('/v1/runtime')
    assert r.status_code == 200
    assert 'vision_embedder' in r.json()
    assert r.json()['vision_embedder']['configured'] is False
    assert r.json()['vision_embedder']['loaded'] is False
