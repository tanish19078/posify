# Local inference and external detector handoff

Training, dataset building and Colab notebooks are deliberately outside this
repository. No training jobs are launched. The API can operate without a detector
or language model, and never treats a missing component as a successful inference.

## Current capability

| Component | Implemented | Verified here |
| --- | --- | --- |
| Image storage / metadata stripping | Yes | PNG/JPEG validation, replay and access tests |
| OCR parsing and matching | Yes | Real Tesseract on a synthetic nameplate; adversarial/conflict tests |
| PaddleOCR adapter | Yes, optional | Contract integration only; weights/runtime not installed |
| E5 hybrid retrieval adapter | Yes, optional | Prefixes, fusion and failure handling with a controlled encoder |
| Ollama drafts | Yes, optional | Simulated runtime responses; no LLM weights installed |
| Equipment detector inference | No | Awaiting the external model artifact and inference adapter |
| QR decoding | No | OCR reads explicit printed labels only |
| Mobile/3D | No | No on-phone inference claims |

`GET /v1/runtime` requires the instance API key. It reports configuration and
artifact availability, not a benchmark or a guarantee of successful inference.

## OCR

Set `POSIFY_OCR_ENGINE=tesseract` to use an installed Tesseract executable and its
English language data. This baseline has a 20-second subprocess timeout and a
fixed command without shell evaluation. It is never selected silently.

For PaddleOCR, install `pip install -e '.[ocr]'` in a dedicated environment,
provide existing model directories through `POSIFY_PADDLE_DET_DIR` and
`POSIFY_PADDLE_REC_DIR`, and set `POSIFY_OCR_ENGINE=paddle`. The adapter names
`PP-OCRv5_mobile_det` and `en_PP-OCRv5_mobile_rec` explicitly, disables orientation
and document-unwarping models, and loads on CPU. Missing files or runtime failure
return 503. Benchmark the pinned runtime against real nameplates before using it.
Weights are not included. Optional ML extras are not part of the tested core lock.

Identifier parsing deliberately requires explicit printed `TAG:`, `ASSET TAG:`,
`ASSET:`, `SERIAL:`, `SERIAL NO:` or `S/N:` labels. It ignores lines below a 0.75
engine score, does not repair O/0 or I/1, and refuses multiple values for one field.
The score is an engine heuristic, not a calibrated identity probability. Matching
is case-sensitive and ANDs supplied tag and serial evidence. No category fallback.

OCR may fail on split labels, glare, rotation and non-English text. The current
Paddle recognition configuration is English-specific. Use human review and test a
suitable language model before claiming regional-language support.

## Local retrieval / language model

Install `pip install -e '.[retrieval]'` separately and set `POSIFY_EMBEDDING_DIR`
to an existing multilingual-e5-small snapshot. Loading is local-only with remote
model code disabled. Queries use `query: ` and chunks use `passage: ` prefixes.
Normalized cosine scores and lexical ranks are combined by reciprocal rank fusion.
The default 0.80 semantic cutoff is an unevaluated configurable heuristic.

Only procedures applicable to the requested asset's site/manufacturer/model,
using the latest revision per title, enter search. At most 256 chunks are accepted
by semantic search. Passage embeddings are recomputed per request in this first
implementation; persistent indexing and calibrated evaluation remain future work.
A retrieval query is not automatically pinned to a particular inspection revision;
inspection execution still uses its immutable procedure ID.

Configure `POSIFY_OLLAMA_MODEL` with an already installed model (Qwen3-4B is one
candidate) and restart to enable draft generation. Offline artifact provisioning
is an operator action. The API never downloads language-model weights. Model text
cannot confirm an asset, attach evidence or submit an inspection.

## Colab detector handoff (future inference integration)

When the separately trained detector is ready, provide:

- ONNX export and its exact SHA-256; avoid executable pickle/PT uploads to an API.
- Model revision, architecture, export tool versions and ONNX opset.
- Ordered class map and dataset/license provenance.
- Input tensor shape, dtype, colour order, scaling and letterbox specification.
- Output tensor names, shape, box convention, score semantics and whether NMS is embedded.
- Intended confidence/IoU settings and reference input/output examples.
- Held-out evaluation results, failure cases and target hardware latency.

YOLO export variants have different output layouts. Do not guess decoding from a
filename or treat arbitrary ONNX files as trusted. A future adapter should validate
the manifest, verify the digest and reproduce the reference outputs before being
enabled. Detection locates a category; it never establishes an installed asset ID.

## Sources

- https://www.paddleocr.ai/main/en/version3.x/pipeline_usage/OCR.html
- https://tesseract-ocr.github.io/tessdoc/Command-Line-Usage.html
- https://huggingface.co/intfloat/multilingual-e5-small
