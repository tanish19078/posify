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
