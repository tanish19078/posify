import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image
from pydantic import ValidationError

from posify.detector import DetectorManifest, postprocess, preprocess


def manifest(**overrides):
    return DetectorManifest(model_id='fixture', revision='1', artifact='model.onnx', sha256='a'*64,
                            class_names=['pump', 'nameplate'], **overrides)


def test_letterbox_mapping_and_classwise_nms():
    image = Image.new('RGB', (1000, 500), 'white')
    tensor, transform = preprocess(image, (640, 640))
    assert tensor.shape == (1, 3, 640, 640)
    assert tensor.dtype == np.float32
    # Original box [100,50,300,150] -> padded input [64,192,192,256].
    raw = np.array([[[128, 128, 128], [224, 224, 224], [128, 128, 128], [64, 64, 64],
                     [.9, .8, .1], [.1, .2, .95]]], dtype=np.float32)
    output = postprocess(raw, manifest(), image.size, transform)
    assert len(output) == 2  # Same-class duplicate suppressed; different class retained.
    assert output[0].label == 'nameplate'
    assert output[0].box == pytest.approx((100, 50, 300, 150))


def test_detector_rejects_wrong_shapes_nonfinite_and_invalid_scores():
    for raw in [np.zeros((1, 10, 6)), np.full((1, 6, 1), np.nan), np.ones((1, 6, 1))*2]:
        with pytest.raises(HTTPException) as exc:
            postprocess(raw, manifest(), (640, 640), (1, 1, 0, 0))
        assert exc.value.status_code == 502


def test_invalid_manifest_layout_and_dimensions_rejected():
    with pytest.raises(ValidationError):
        manifest(output_layout='guess-from-filename')
    with pytest.raises(ValidationError):
        manifest(input_size=(0, 640))


def test_empty_detector_output_is_valid():
    assert postprocess(np.zeros((1, 6, 0)), manifest(), (100, 100), (1, 1, 0, 0)) == []


@pytest.mark.parametrize('size', [(1, 4096), (4096, 1)])
def test_extreme_image_aspect_ratio_keeps_positive_resize_dimensions(size):
    tensor, transform = preprocess(Image.new('RGB', size), (640, 640))
    assert tensor.shape == (1, 3, 640, 640)
    assert transform[0] > 0 and transform[1] > 0


def test_runtime_session_reuse_and_verified_inference_metrics(tmp_path, monkeypatch):
    import hashlib
    import json
    import sys
    from types import SimpleNamespace
    from posify.detector import LocalDetector
    artifact = tmp_path / 'model.onnx'
    artifact.write_bytes(b'controlled-test-artifact')
    spec = DetectorManifest(model_id='test', revision='1', artifact='model.onnx',
                            sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(), class_names=['nameplate'])
    path = tmp_path / 'manifest.json'
    path.write_text(spec.model_dump_json())
    monkeypatch.setenv('POSIFY_DETECTOR_MANIFEST', str(path))
    sessions = []
    class Session:
        def __init__(self, path, sess_options, providers):
            assert sess_options.intra_op_num_threads == 1 and providers == ['CPUExecutionProvider']
            sessions.append(self)
        def get_inputs(self):
            return [SimpleNamespace(name='images', type='tensor(float)', shape=[1, 3, 640, 640])]
        def get_outputs(self):
            return [SimpleNamespace(type='tensor(float)', shape=[1, 5, 1])]
        def run(self, outputs, inputs):
            return [np.array([[[320], [320], [100], [100], [.9]]], dtype=np.float32)]
    fake = SimpleNamespace(SessionOptions=lambda: SimpleNamespace(), InferenceSession=Session)
    monkeypatch.setitem(sys.modules, 'onnxruntime', fake)
    import posify.detector as module
    monkeypatch.setattr(module, 'runtime_version', lambda: '1.31.1')
    # Runtime presence was checked independently in CI; use the controlled runtime here.
    detector = LocalDetector()
    detector.readiness = lambda: {'manifest_present': True, 'runtime_present': True}
    image = tmp_path / 'image.png'
    Image.new('RGB', (640, 640)).save(image)
    assert detector.predict(image)[0][0].box == pytest.approx((270, 270, 370, 370))
    detector.predict(image)
    assert len(sessions) == 1 and detector.successful_inferences == 2
    assert detector.last_inference_ms >= 0


def test_provided_export_raw_reference_conformance():
    import os
    from pathlib import Path
    from posify.detector import LocalDetector
    configured = os.getenv('POSIFY_TEST_DETECTOR_MANIFEST')
    if not configured:
        pytest.skip('Operator-provisioned weights are not committed to CI')
    previous = os.environ.get('POSIFY_DETECTOR_MANIFEST')
    os.environ['POSIFY_DETECTOR_MANIFEST'] = configured
    try:
        detector = LocalDetector()
        manifest, session = detector.load()
        root = Path(configured).parent
        x = np.load(root / 'reference_input.npy', allow_pickle=False)
        expected = np.load(root / 'reference_raw_output.npy', allow_pickle=False)
        actual = session.run(None, {session.get_inputs()[0].name: x})[0]
        assert x.shape == (1, 3, *manifest.input_size)
        assert actual.shape[1] == 4 + len(manifest.class_names)
        np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-3)
    finally:
        if previous is None:
            os.environ.pop('POSIFY_DETECTOR_MANIFEST', None)
        else:
            os.environ['POSIFY_DETECTOR_MANIFEST'] = previous


def test_old_native_runtime_is_rejected_before_import(monkeypatch):
    import posify.detector as module
    monkeypatch.setattr(module, 'runtime_version', lambda: '1.20.1')
    detector = module.LocalDetector()
    with pytest.raises(ValueError, match='requirements-inference.lock'):
        detector.load()
