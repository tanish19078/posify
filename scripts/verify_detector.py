"""Check an operator-provisioned export against its reference raw output."""
import argparse
import json
import os
from pathlib import Path

import numpy as np

from posify.detector import LocalDetector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('var/detector-conformance.json'))
    args = parser.parse_args()
    os.environ['POSIFY_DETECTOR_MANIFEST'] = str(args.manifest)
    detector = LocalDetector()
    manifest, session = detector.load()
    root = args.manifest.parent
    x = np.load(root / 'reference_input.npy', allow_pickle=False)
    expected = np.load(root / 'reference_raw_output.npy', allow_pickle=False)
    if x.dtype != np.float32 or x.shape != (1, 3, *manifest.input_size) or not np.isfinite(x).all():
        raise ValueError('Reference input does not match the declared finite FP32 input')
    actual = session.run(None, {session.get_inputs()[0].name: x})[0]
    if actual.shape != expected.shape or not np.isfinite(expected).all():
        raise ValueError('Reference output is invalid or has the wrong shape')
    np.testing.assert_allclose(actual, expected, rtol=1e-4, atol=1e-3)
    import onnxruntime as ort
    result = {'model_id': manifest.model_id, 'revision': manifest.revision, 'sha256': manifest.sha256,
              'class_names': manifest.class_names, 'runtime': ort.__version__, 'provider': 'CPUExecutionProvider',
              'input_shape': list(x.shape), 'output_shape': list(actual.shape),
              'max_abs_error': float(np.max(np.abs(actual - expected))), 'reference_conformance': 'passed',
              'notice': 'Reference tensor compatibility does not establish image detection accuracy.'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
