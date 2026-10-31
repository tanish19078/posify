# posify

A web-first equipment identification and inspection backend with shared catalogue
knowledge and factory-specific installed assets. No product name is selected. Start with evidence-backed asset identity and
versioned procedures; connect a local model for explanations without giving it
control over maintenance state.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.lock
pip install --no-deps -e .
export POSIFY_API_TOKEN="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
uvicorn posify.app:app --host 127.0.0.1 --port 8000
```

Use the same token in another terminal with `python scripts/demo.py`. Interactive
API docs: http://127.0.0.1:8000/docs (Authorize with the token). Data persists in
`var/posify.db`. Business endpoints require `X-API-Key`. On Windows, activate with
`.venv\Scripts\Activate.ps1` and set environment variables with PowerShell syntax.

## Components

| Path | Responsibility |
| --- | --- |
| `services/api/posify/` | API, persistent registry, inspection rules and local-model adapter |
| `services/api/tests/` | Workflow, auth, scope, replay and model-boundary tests |
| `packages/contracts/` | Generated OpenAPI contract for future clients |
| `scripts/` | Repeatable demo and contract export |
| `docs/BUILD_PLAN.md` | File-level build phases and acceptance walkthrough |
| `docs/ARCHITECTURE.md` | Data, identity, sync and deployment decisions |

## Working scope

Asset creation/listing; identifier candidates requiring human confirmation;
immutable procedure versions; inspection creation, observations and submission;
idempotent offline observation replay; site-pack export; audit history; local
procedure search and optional Ollama draft generation.

Image upload, OCR adapters, conservative identifier extraction, confirmed capture
assignment and inspection evidence are implemented. PaddleOCR and E5 require local
weights and optional dependencies; their adapters are not benchmarked here.
An inference-only YOLO11 ONNX adapter and durable OCR/detector job worker are
implemented. No trained detector artifact has been provided or benchmarked.
QR decoding, PDF ingestion, frontend, 3D and work-order integrations remain pending.
The site pack is a full JSON snapshot; observation replay is the first sync
primitive, not a complete mobile sync implementation.

## Database, catalogue and workers

SQLite remains available for local development; PostgreSQL and Alembic migrations
are implemented. See [database and ownership](docs/DATABASE.md),
[background jobs](docs/ANALYSIS_JOBS.md) and [detector contract](docs/DETECTOR_CONTRACT.md).
Register an organization and factory before creating assets, procedures or captures.
Global model/manual drafts need explicit publication and asset links need confirmation.
Global source excerpts are labelled separately from factory procedures.

## Images and local ML adapters

See [capture API](docs/CAPTURE_API.md) for uploads and evidence attachment, and
[local model setup](docs/LOCAL_MODELS.md) for explicit OCR/E5/Ollama configuration.
`GET /v1/runtime` reports component configuration without claiming successful inference.
Site-pack schema is now version 2. No training code or notebooks are included;
detector training stays in your separate Colab workflow.

## Local model

Set `POSIFY_OLLAMA_MODEL` to a model you already installed in Ollama, optionally
set `POSIFY_OLLAMA_URL`, and restart. No cloud API or particular model family is
required. Without a model the assistant returns source excerpts, not generated
advice. With a model it returns an unverified draft and source IDs; it cannot
advance inspections. Unavailable runtimes return 503, never fabricated output.

## Checks

```bash
pytest -q
python scripts/export_contracts.py --check
```

Development access still uses an instance-wide shared token. Add individual identity,
role/site authorization and operational controls before real multi-user deployment. See [build plan](docs/BUILD_PLAN.md).
