# posify

An equipment identification and inspection backend, designed for an offline field
client. No product name is selected. Start with evidence-backed asset identity and
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

This version does not perform OCR, equipment detection, document ingestion,
3D reconstruction, image uploads, mobile inference or work-order integrations.
The site pack is a full JSON snapshot; observation replay is the first sync
primitive, not a complete mobile sync implementation.

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

Local single-instance development only: replace shared-token authentication with
user/site authorization and add production persistence, migrations and deployment
controls before using across a real organization. See [build plan](docs/BUILD_PLAN.md).
