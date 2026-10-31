# Backend-first build plan

The product remains unnamed. Web is the first client; frontend is intentionally deferred.
Training and dataset building remain separate Colab work.

## Implemented backend

- SQLAlchemy connections and Alembic revisions: `database.py`, `migrations/`.
- Organizations, factories, global models/manual revisions and confirmed asset links: `catalog.py`.
- Local assets, immutable procedures, inspection observations, submission and audit: `app.py`.
- Image validation/storage, OCR, identifier evidence and confirmed attachments: `captures.py`, `capture_routes.py`, `ocr.py`, `matching.py`.
- Source-labelled factory/global retrieval and optional local E5/Ollama: `assistant.py`, `retrieval.py`.
- Inference-only YOLO11 ONNX input/output contract: `detector.py`.
- Cropped OCR orchestration and original-image coordinates: `analysis.py`.
- Durable leased jobs, retries and fencing: `jobs.py`, `worker.py`.
- Generated OpenAPI, smoke scripts, SQLite/PostgreSQL CI and proposed Docker Compose stack.

## Next backend work

Individual identities and site/role authorization; editable asset lifecycle with
reviewed corrections; actual Paddle/E5/Ollama provisioning and evaluation; detector
artifact conformance; PDF ingestion and per-page citations; persistent vector index;
supervisor review/work orders; evidence retention and backup/restore verification.
Catalogue knowledge is not yet included in site-pack snapshots. Organization data
relationships do not constitute tenant security.

## Deferred clients

A web capture/review/inspection interface and management console will use OpenAPI.
No Android client is planned for this build. Browser offline caching can be evaluated
later; running inference on a factory server does not mean inference runs in a browser.

## Optional spatial work

Existing CAD links or browser overlays only after core field workflows work. No 3D
reconstruction or hidden-fault diagnosis is promised.
