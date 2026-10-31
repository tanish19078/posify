# Build plan

The repository name is retained; no product branding is selected.

## 1. Backend foundation (this implementation)
Files: `pyproject.toml`, `services/api/posify/{database,schemas,app}.py`,
`services/api/tests/test_api.py`, `packages/contracts/openapi.json`.

Deliver a persistent asset registry, conservative identifier matching, immutable
procedure versions, validated inspection lifecycle, replay-safe observation sync,
site-pack export and audit events. Use SQLite for a single-instance local service;
PostgreSQL and migrations are required before multi-instance deployment.

## 2. Local knowledge and model boundary (this implementation)
Files: `services/api/posify/assistant.py`, `scripts/demo.py`.

Retrieve applicable procedure excerpts; provide extractive results without a
model, or a bounded draft using a locally configured Ollama model. Return source
IDs and explicit draft status. Never let generated text mutate inspection state.
A generated answer is not mechanically verified merely because its citation IDs
are valid. Evaluate groundedness with technician-reviewed cases.

## 3. Perception integration (partially implemented)
Implemented: `services/api/posify/{captures,capture_routes,ocr,matching,retrieval}.py`,
`services/api/tests/{test_captures,test_retrieval}.py`, `docs/{CAPTURE_API,LOCAL_MODELS}.md`.

Image storage, basic quality flags, optional OCR and E5 adapters, conservative
identifier matching, human confirmation and inspection evidence are implemented.
Object detection, QR decoding and multi-view recognition remain unimplemented.
Training/dataset building will be performed separately in Colab; no training
scripts or notebooks belong in this implementation. The external artifact handoff
requirements are documented in `docs/LOCAL_MODELS.md`.

## 4. Mobile field client (next)
Planned files: `apps/android/` with capture, asset review, inspection, local
storage and sync packages. Generate the client from OpenAPI. Load site packs
locally, retain observations in an outbox, show unsynchronized records, and
benchmark a mobile model before choosing its runtime. Desktop-local inference
is not on-phone inference.

## 5. Management and operational integration (next)
Planned files: `apps/console/`, `services/api/posify/{identity,evidence,integrations}.py`,
`infra/`, `evals/`.

Add OIDC roles and site-scoped authorization, signed/checksummed site packs,
evidence uploads, document ingestion/review, PostgreSQL migrations, backups,
telemetry, work-order connectors and model distribution. The initial shared-token
API is for local development, not tenant isolation or production access control.

## 6. Spatial enhancements (optional)
Planned files: `apps/android/.../spatial/`, `packages/spatial-contracts/`.

Depth/AR overlays and links to existing CAD/BIM models, with device capability
checks. No engineering measurements or hidden-fault diagnosis from RGB alone.

## Acceptance walkthrough
Create asset and immutable procedure; request an identifier match; confirm the
asset; create inspection against that exact procedure version; append/replay
observations; submit only after every step has an explicit result; export the
site pack and audit history. Repeat after a service restart.
