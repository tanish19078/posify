# Nameplate evidence mini demo

A 22-second, 1920 × 1080 presentation built with
[Brag](https://github.com/latent-spaces/brag/tree/main/skills/brag) and
Hyperframes 0.8.223. It shows a real public nameplate photo, the detector's
measured region, raw Tesseract output and the human confirmation boundary.
The panels are a video composition; the production web client remains pending.

## Inputs and provenance

- Install the backend and the nameplate ONNX bundle using
  [trained detector setup](../../docs/TRAINED_DETECTOR.md).
- Generate `var/nameplate-integration.json` and its pinned public images:
  `python scripts/detector_smoke.py --manifest models/nameplate-v1/manifest.json --download`.
- Obtain Brag at commit `669ab9286aa28b6c3ee30e75f181ee74319d012a`.
  Pass the checkout's `skills/brag` directory to `prepare.py`.
- Install Node.js, FFmpeg, Tesseract and DejaVu fonts. The Python backend
  environment supplies Pillow and the OCR adapter. `--fonts` overrides the
  default Linux font directory.

The measured case is selected by source ID, and its source digest is checked
before preparation. No image, model weights or licensed audio is committed here.
Review [credits.txt](credits.txt) before redistributing a render.

## Build and render

Run from the repository root with the backend Python environment activated:

```bash
export HYPERFRAMES_NO_TELEMETRY=1
export DO_NOT_TRACK=1
npx --yes hyperframes@0.8.223 init brag-output/composition --non-interactive --skip-skills --skill=brag
npx --yes --package=hyperframes@0.8.223 -c 'python demos/nameplate-video/prepare.py --brag-dir /absolute/path/to/brag/skills/brag'
python demos/nameplate-video/build.py
npx --yes hyperframes@0.8.223 browser ensure
npx --yes hyperframes@0.8.223 check brag-output/composition --contrast --snapshots --at 1.5,9.6,14.8,20 --json
npx --yes hyperframes@0.8.223 preview brag-output/composition
npx --yes hyperframes@0.8.223 render brag-output/composition --quality delivery --fps 30 --output brag-output/brag.mp4
ffmpeg -y -ss 9.6 -i brag-output/brag.mp4 -frames:v 1 -q:v 2 brag-output/brag.jpg
```

`prepare.py --hyperframes-dir` can select an existing Hyperframes package.
`HYPERFRAMES_BROWSER_PATH` can select an existing compatible Chrome headless shell
when automatic browser provisioning is unavailable. Generated output is ignored.

[brag-plan.md](brag-plan.md) and [composition-brief.md](composition-brief.md)
record the storyboard, motion, audio and evidence choices. `build.py` writes the
four scene templates and root timeline; `prepare.py` supplies measured image/OCR
evidence and licensed local assets. No network requests are needed during rendering.

## Interpretation

The detector score is an output confidence, not a measured accuracy. The
72–75 ms figure is warm CPU ONNX execution on four smoke images, excluding OCR,
queueing and HTTP. These public images are not an independent accuracy benchmark.
OCR did not produce a verified asset identifier; the video preserves raw text
and explicitly requests human confirmation. Recheck timing and copy if inputs,
OCR versions, model outputs or measurements change.
