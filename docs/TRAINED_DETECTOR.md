# Nameplate detector integration

The operator-provided `nameplate-detector@v1` ONNX export is integrated with the
capture-analysis worker. It detects one class, `nameplate`; it does not classify
pumps/valves or establish an installed asset's identity. The model and public image
files remain outside Git in ignored local directories.

Artifact SHA-256:
`b5b84f7e1dd006a1522fd0d2f371dd37dc18ef79a30488836b4001d91e818f50`

## Provision and verify

```bash
pip install -r requirements-inference.lock
pip install --no-deps -e .
python scripts/install_detector.py /path/to/backend_export.zip
python scripts/verify_detector.py --manifest models/nameplate-v1/manifest.json
```

The installer accepts exactly the five expected root-level export files, checks the
manifest/report/digest, stages them before installation and refuses to replace a
different revision. Exact repeated installs are safe. It never deserializes PT files.
Reference tensors load with `allow_pickle=False`.

The verified CPU runtime is ONNX Runtime 1.31.1. The original 1.20.1 runtime crashed
at native import on this development host; 1.31.1 imported and ran successfully.
The loader rejects unsupported runtime versions before importing the native module.
The supplied `[1,3,640,640]` input and `[1,5,8400]` raw output matched exactly
(maximum absolute error 0.0). The reference is an all-zero tensor: this verifies
export/runtime compatibility, not detection accuracy or image preprocessing parity.

Enable the API and worker with the same environment:

```bash
export POSIFY_DETECTOR_MANIFEST="$PWD/models/nameplate-v1/manifest.json"
export POSIFY_OCR_ENGINE=tesseract
export POSIFY_DETECTOR_THREADS=1
# Start API and worker in separate terminals with the same DB/capture settings:
uvicorn posify.app:app --host 127.0.0.1 --port 8000
python -m posify.worker
```

Supply the API credential/authentication mode described in the README. Tesseract
with English language data must be installed. Enqueue jobs with `mode=detect_ocr`.
Detector runtime counters and latency are process-local; the API process may remain
unloaded while a separate worker has already completed inference. Job results record
the detector revision. `last_inference_ms` measures ONNX execution only.

For Compose, set `POSIFY_WITH_DETECTOR=true` and
`POSIFY_DETECTOR_MANIFEST=/models/nameplate-v1/manifest.json`, then rebuild. The local
`models/` directory is mounted read-only. The supplied Compose configuration has
not been executed on this development host; Python API/worker processes were tested.

## Public-image smoke results

The pinned public sources, authors, licenses, download URLs and image digests are in
[the source manifest](../examples/nameplate_sources.json). The images were independently sourced from Commons; no dataset files or
private factory photos were supplied for this check. Training-set overlap is unknown;
these four examples are not a held-out accuracy benchmark.

```bash
python scripts/detector_smoke.py --manifest models/nameplate-v1/manifest.json --download
```

This creates an isolated temporary registry and runs upload -> queue -> actual
ONNX inference -> Tesseract crop OCR -> persisted result. Photos are oriented,
resized to at most 1600 pixels on the long edge and re-encoded for API upload.
Any redistribution of image derivatives must preserve their listed attribution/license.
The full local JSON report is written under ignored `var/`.

Measured on this x86_64 development host, FP32 CPU execution with one inference thread:

| Public photo | Returned nameplate regions | Highest score | OCR lines | Median warm ONNX time | Analysis wall time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Electrolux motor | 1 | 0.422 | 4 | 74.8 ms | 1069 ms |
| Current transformer | 1 | 0.926 | 8 | 73.0 ms | 511 ms |
| Malmbergs motor | 1 | 0.917 | 5 | 72.4 ms | 929 ms |
| Westinghouse marine motor | 1 | 0.869 | 36 | 72.7 ms | 3061 ms |

Each warm timing is the median of three additional inference runs after its queued
analysis. Wall time includes OCR and persistence, and the first case includes model
loading. Scores are detector outputs, not calibrated probabilities. A returned box
is not proof that the complete plate is covered: visual review found the Westinghouse
region cut off lower plate text. No ground-truth boxes or OCR transcriptions were
supplied, so precision/recall, box coverage and OCR accuracy were not measured here.

All four analyses correctly retained `requires_confirmation=true` and
`status=insufficient_evidence`: no printed tag/serial passed the existing conservative
parser. It requires explicit labelled delimiters and rejects weak OCR lines. No
factory assets were seeded to manufacture successful matches. Human review remains
necessary for unlabelled `No.` fields, split labels and incomplete crops.

A separate live loopback HTTP API plus a separate `python -m posify.worker --once`
process also completed `detect_ocr` successfully on the transformer image: one region,
eight OCR lines and explicit human confirmation retained.

## Operator-reported training evaluation

The supplied report lists 1,073 training images, 310 validation images and 160 test
images (369 test boxes). Reported test precision is 0.8190, recall 0.6640,
mAP@50 0.7407 and mAP@50–95 0.5765. These metrics were not rerun against the ONNX
export here. The dataset fingerprint is
`1b6ae602c90bbede0f1596fb3776d788d2f9f196aa1e9fe5000cc2aba7b29509`.
Asset/session grouping and near-duplicate leakage were not checked in that report.
The report does not supply a dataset source/version/license; preserve that provenance
alongside the training artifacts. Broader field images and annotated independent
evaluation remain necessary before setting operational thresholds.

## Regression checks

```bash
POSIFY_TEST_DETECTOR_MANIFEST=models/nameplate-v1/manifest.json pytest -q
```

Local verification passed all 111 tests including the actual artifact reference
check. CI installs/imports the pinned CPU runtime and runs 110 tests on each database;
the weight-dependent reference test is skipped because weights are not committed.
