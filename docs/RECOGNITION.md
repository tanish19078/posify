# Equipment evidence recognition

The current local reader supports PP-OCRv6 through RapidOCR and a Tesseract baseline.
It detects nameplates, proposes equipment fields and checks
published catalogue records. It does **not** recognise machine makes/models from
overall appearance, perform 3D reconstruction or establish physical identity
automatically. A manufacturer/model candidate describes an equipment type;
factory asset tags/serials and human confirmation identify an installed machine.

## Reading pipeline

`detect_ocr` keeps the original plate crop, then tries bounded alternative views:
contrast, sharpening, scale, white border and quarter-turn orientations. A large
convex plate boundary can propose perspective rectification through OpenCV.
Sparse/block text layouts and bounded single-code line refinements are tried for
Tesseract. PP-OCRv6 supplies its own learned text-region detection and recognition. At most eight attempts per
region, twenty per capture and sixty seconds of reading are scheduled. Failed
alternative views retain the original. Remaining unread regions are flagged.
These limits do not provide process isolation for a hung optional native engine.

Reading layout is chosen by a documented text/word-confidence heuristic, without
catalogue or annotation access. The ranking is not recognition accuracy. Every
successful attempt is retained; source quadrilaterals, line/word boxes and field
locations are mapped back into uploaded-image coordinates through inverse
transforms. The original image is unchanged. `View source` shows its pixels.

Fields include manufacturer, model/type, serial, factory tag, frame and explicitly
printed voltage/power/speed/frequency units. Header brand and unlabelled model-code
proposals are marked by their basis. No automatic S/5, O/0 or I/1 substitution is
performed. Word confidence supports a value when the tokens cover it; otherwise
the conservative line score is used. Conflicting credible readings stay visible.
OCR confidence is a reading heuristic, never a machine identification probability.
Tables whose values cannot be associated with labels are deliberately not inferred.

## Catalogue and identity boundaries

Only published models enter retrieval. Manufacturer vocabulary is bounded to
published global names and the current factory's asset manufacturers. Search is
parameterised and bounded; truncation is reported. At most five distinct catalogue
variants are returned, with matching/missing/conflicting fields and evidence IDs.
Approximate model codes are suggestions; evidence support requires exact
case/space-normalised manufacturer and model agreement within one plate region.
Punctuation remains meaningful. Near-code contradictions prevent acceptance.
Multiple matching variants or multiple plates require explicit review.

Existing factory identifier matching remains conservative. Conflicting serial/tag
proposals veto a physical candidate. Model agreement never assigns a factory asset,
links a catalogue record or starts an inspection. Those remain authenticated,
explicit human operations. Corrections and reviews preserve the original evidence.

## Setup

Install `requirements-inference.lock` in the API/worker environment; it includes
the pinned OpenCV headless and RapidOCR packages. Provision the bundled pretrained
OCR models explicitly (no training required):

```bash
python scripts/install_ocr_models.py
export POSIFY_OCR_ENGINE=rapidocr
export POSIFY_RAPIDOCR_MODEL_DIR="$PWD/models/ocr-ppv6"
```

The installer checks pinned SHA-256 digests for the three artifacts distributed in
`rapidocr==3.10.0`, then stages a local bundle atomically. The server requires an
explicit model directory, verifies digests before loading and supplies local model
paths to the runtime. Inference must not fetch models. A native integration test
blocks runtime HTTP requests. Tesseract remains a selectable comparison baseline.
For Compose use `/models/ocr-ppv6`, enable `POSIFY_WITH_DETECTOR=true`, and recreate
the API/worker with the configured OCR engine and directory. Models remain operator-provisioned. Enable
the trained detector manifest and Tesseract as described in
[trained detector setup](TRAINED_DETECTOR.md), then restart workers. Without
OpenCV, contrast/orientation readings still run and failed geometry is flagged.
The synchronous `/analyze` compatibility endpoint remains baseline full-image OCR.

New analyses have `recognition_version=plate-evidence-v1`, structured fields,
equipment candidates, equipment status and reading attempts. Old stored analyses
remain readable with empty defaults; they must be re-analysed to gain new evidence.
No database migration is needed because immutable analysis payloads are JSON.

## Evaluate before claiming improvement

```bash
python scripts/evaluate_recognition.py --cases examples/recognition_smoke.json --manifest models/nameplate-v1/manifest.json --reader rapidocr --ocr-model-dir models/ocr-ppv6
```

This requires Tesseract for the original-reader comparison and supplies a labelled
**single-image development smoke check**, including a
synthetic near-code catalogue distractor. Its training overlap is unknown. It
cannot establish industrial accuracy or robustness. Labels and source pixels are
inspectable; the reference catalogue is transcribed from the photo.

The report compares a detector-crop/PSM-6 baseline with the selected enhanced reader using
the same field extractor. The default `--reader tesseract` measures preprocessing
alone; `--reader rapidocr` measures the explicitly provisioned learned reader. Only annotated identity fields are scored. Wrong single
values count as false positives and missed truths; conflicts/low-confidence values
abstain. Precision, recall and coverage are reported separately, including null
precision when there are no accepted values. Pipeline and baseline timing cover
different operations and must not be compared as equivalent latency benchmarks.

Use `--cases` with a separately collected labelled set to measure generalisation.
The runner verifies optional SHA-256 image pins, never downloads/trains a model,
and uses an isolated temporary registry. Reports default to ignored `var/`.
Genuinely independent field evaluation and visual appearance retrieval remain
outstanding; neither is implied by the smoke check or software tests.

Implementation references: [Tesseract image quality guidance](https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html)
and [OpenCV perspective transformations](https://docs.opencv.org/4.13.0/da/d6e/tutorial_py_geometric_transformations.html).

## Recorded development observation

On the bundled motor photo, the PP-OCRv6 reader recovered both annotated fields:
`SIEMENS` and `1HU3054-0AC01-Z`. The Tesseract baseline recovered the manufacturer
but abstained on the model. The matching catalogue fixture was supported; the
synthetic `1HU3054-0AC02-Z` distractor was contradicted. The neural pipeline took
about 5.1 seconds on the development CPU for this case. This is one development
observation with unknown training overlap, not an accuracy or latency guarantee.
The default web demo stores the actual neural output, including reading attempts;
its factory asset/inspection records remain explicitly fictional.
