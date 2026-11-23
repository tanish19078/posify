# Colab ML starter for the posify backend

Start with a single `nameplate` class. A nameplate detector can immediately feed
our OCR pipeline. Add pump/valve/motor categories after you have enough correctly
annotated photographs; equipment recognition and exact installed-asset identity
are separate tasks.

This kit is separate from the backend runtime. It does not contain trained weights
or downloaded datasets. Training and model export have NOT been run by the author.
Dataset validation, CLI parsing and pure-Python helpers were checked locally.
YOLO dependencies are a pinned baseline, not a claim of being the newest release.
Colab GPU availability, CUDA compatibility and download access must be checked in
your runtime. Keep Colab's preinstalled torch/torchvision; start a fresh runtime if
an incompatible package environment has already been created.

## Quick start

1. Open https://colab.research.google.com and upload `START_COLAB.ipynb` from this ZIP.
2. Select a GPU runtime (T4 is a reasonable starting point if available).
3. Run the first cell and upload this original starter ZIP, then install requirements.
4. Download a dataset as YOLO-format ZIP, upload it in the dataset cell, and inspect
   the displayed labels and folder layout before training.
5. Run validation, training, held-out evaluation, then export the backend bundle.

Minimal commands after extracting this ZIP:

```bash
pip install -r requirements-colab.txt
# Optional: remap & merge one or more YOLO datasets into a canonical multi-class layout:
python prepare_multiclass.py \
  --source /content/raw_nameplate --source /content/raw_pump --source /content/raw_valve \
  --classes nameplate,pump,valve \
  --remap nameplate=nameplate --remap 0=pump --remap open=valve --remap close=valve \
  --output /content/dataset
python validate_dataset.py --data /content/dataset/data.yaml
python train_yolo.py --data /content/dataset/data.yaml --epochs 60 --batch 8 --device 0 --name equipment_yolo11n_v2
python evaluate_yolo.py --weights /content/runs/equipment_yolo11n_v2/weights/best.pt \
  --data /content/dataset/data.yaml --split test --device 0
python export_backend.py --weights /content/runs/equipment_yolo11n_v2/weights/best.pt \
  --output /content/backend_export --model-id equipment-detector --revision v2
```

If CUDA memory runs out, reduce batch to 4 or 2 first. Start with `yolo11n.pt`;
try `--weights yolo11s.pt --name nameplate_yolo11s` only after measuring a baseline.
Model weights download from Ultralytics on first training use. Do not keep tuning
on the test set. Use a fresh run name for another experiment.

## Dataset links and limits

| Source | Link | Appropriate use / limitation |
| --- | --- | --- |
| Flying Squirrels Nameplate Detection V2 | https://universe.roboflow.com/flying-squirrels/nameplate-detection-v2 | Best first detection candidate: one `nameplate` class; listing shows 1,543 source images. Version counts can include augmented images. CC BY 4.0 as listed. |
| RWTH pump detection | https://universe.roboflow.com/rwth-gxwxz/pump-detection | Small equipment starter; listing shows 164 source images and a class called `0`. Inspect photographs and remap labels deliberately. CC BY 4.0 as listed. |
| Industrial detection valve detector | https://universe.roboflow.com/industrial-detection/valve-detector | Small starter with open/close valve classes, 92 listed images. State recognition is not all-valve category coverage. CC BY 4.0 as listed. |
| Kahua Pompax classification | https://huggingface.co/datasets/kahua-ml/pompax-classification | Nameplate image classification, NOT ready YOLO bounding boxes. Requires box annotation for detection. CC BY 4.0 as listed. |
| IndOCR-24 | https://data.mendeley.com/datasets/pdxxnm3fwj/2 | Restricted-alphabet industrial CHARACTER classification, not full nameplate reading. Auxiliary research only. |

Inspect each selected dataset's version, actual imagery, annotations and terms.
Export the first three through the publisher's dataset/download interface in YOLO
format; accounts or API keys may be required. If using an API key, store it in
Colab Secrets rather than source code. No API key is included in this kit.

Do not combine schematic/P&ID symbols with real equipment photographs as equivalent
training images. Do not naively merge a pump-only set with a nameplate-only set:
objects left unlabelled for the other classes become false background examples.
For a multi-class set, annotate all target classes consistently on every image.

Retain publisher attribution and version information. Dataset size and a public
model's advertised score do not establish performance on our factory scenes.

## Dataset layout

```text
/content/dataset/
  data.yaml
  train/images/       train/labels/
  valid/images/       valid/labels/
  test/images/        test/labels/
```

Each label line is `class_id x_center y_center width height` with normalized [0,1]
coordinates. Use empty label files for reviewed negative images. The validator
requires explicit negatives rather than treating missing annotations as negatives.
Set `path`, `train`, `val` and `test` correctly in data.yaml; public exports may use
incorrect-for-your-folder `../train/images` paths. The notebook normalizes the common
Roboflow layout after showing the class names. It never changes class IDs for you.

Split by physical asset or capture session BEFORE augmentation. Supply
`--groups groups.csv` (see example) to check that a group never crosses splits.
Exact image hashes catch byte-identical duplication only, not resized/cropped
near-duplicates. Augmented versions of the same image must remain in one split.
Keep some real factory photographs as a separate field test.

## What to return for backend integration

`export_backend.py` produces `backend_export.zip` containing:

- `model.onnx` and a digest-matched `manifest.json` with the actual ordered classes.
- Reference input/raw output arrays for export-conformance checks.
- Export report with tensor shapes and package version.

Also send `best.pt` for reproducibility, the dataset report/version and attribution,
held-out metrics, and several representative success/failure images with ground truth.
Only operator-reviewed ONNX artifacts are loaded by the backend; PT files are not
accepted through an API. Do not upload private factory data into a public repository.

The backend requires a static FP32 `[1,3,H,W]` input, RGB [0,1], centered padding 114,
and raw `[1,4+C,N]` output. Export uses `dynamic=False`, `half=False`, `nms=False`,
`simplify=False`, batch 1 and opset 17. The script runs ONNX Runtime to check shapes,
finite scores and class count. It does not establish detection accuracy.

Ultralytics licensing: https://www.ultralytics.com/license
Review AGPL-3.0/enterprise options against the intended distribution before deployment.

## OCR: benchmark first, fine-tune only with transcription labels

Start with official pretrained PP-OCRv5 rather than training a recognizer from scratch.
The YOLO dataset provides bounding boxes; that is NOT recognition transcription data.

Official English recognition model:
https://huggingface.co/PaddlePaddle/en_PP-OCRv5_mobile_rec
Official fine-tuning documentation:
https://www.paddleocr.ai/main/en/version3.x/module_usage/text_recognition.html

In a separate fresh environment, install PaddlePaddle using its official installer
for your CUDA version (https://www.paddlepaddle.org.cn/en/install/quick), plus PaddleOCR.
For a CPU-only first benchmark, `pip install 'paddlepaddle>=3.2,<4' 'paddleocr>=3.2,<4'`
is an option. Avoid changing the CUDA stack in your active YOLO training session.

Use human-transcribed nameplate images and JSONL matching `ocr_labels.example.jsonl`:

```bash
python benchmark_ocr.py --labels /content/ocr_labels.jsonl \
  --images /content/nameplates --output /content/ocr_evaluation.json
```

This reports character error rate, exact text and exact serial extraction accuracy.
Without local model directories, the benchmark explicitly initializes named official
models and may download their weights. This differs from the backend, which requires
operator-provisioned local model files.

For recognition fine-tuning you need line-image crops and UTF-8 lists formatted:
`relative/path/to/line.png<TAB>exact transcription`. Use a trusted checkout of
https://github.com/PaddlePaddle/PaddleOCR, a compatible upstream recognition config,
its matching dynamic training checkpoint and character dictionary. Pin the chosen
checkout commit. Example upstream config:
https://github.com/PaddlePaddle/PaddleOCR/blob/main/configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml

```bash
python finetune_ocr.py --repo /content/PaddleOCR \
  --config configs/rec/PP-OCRv5/PP-OCRv5_mobile_rec.yml \
  --pretrained /content/checkpoints/MATCHING_TRAINING_CHECKPOINT.pdparams \
  --train-list /content/ocr/train.txt --val-list /content/ocr/val.txt \
  --image-root /content/ocr/line_crops --output /content/ocr_finetune \
  --epochs 20 --batch 32 --lr 0.00001
```

By default this only writes a config. Add `--run` after verifying architecture,
dictionary and checkpoint compatibility. It uses the upstream trainer, not a
reimplemented recognizer. An inference `.pdiparams` bundle is not a training checkpoint.
The generic PP-OCRv5 mobile config is not the same as the English-only model; do not
mix their checkpoints or dictionaries. A custom OCR export is not automatically a
drop-in backend model: return config, dictionary and export details for integration.

## Application database

Dataset links above are training data. The application DB is separate. See
`DATABASE_START.md` for the existing PostgreSQL setup. No hosted database URL has
been provisioned. Colab detector training does not need the application database.
