# Database, ownership and deployment

## Persistence

SQLAlchemy manages connections and parameter binding. Alembic revisions 0001–0008
adopt the original schema, add catalogue/factory ownership, add durable jobs and
enforce factory references, add asset revisions and persist identity/review records, page-level PDF sources and cached embeddings. SQLite remains the default for local development;
PostgreSQL is configured with `POSIFY_DATABASE_URL`. No SQL is assembled from user
values. The compatibility layer translates only fixed positional placeholders.

SQLite schema upgrades run automatically by default. PostgreSQL startup checks the
revision and requires `python scripts/migrate.py` as a separate step. Explicit
`POSIFY_AUTO_MIGRATE=true` is available for isolated development only. Run migrations
with a single operator/process; concurrent migration runners are not supported.
The database adapter serializes explicit write transactions with SQLite's write
lock or a PostgreSQL transaction advisory lock. This favors correctness over write
throughput; move to narrower locks only after contention is measured.

Existing v2 SQLite records are retained. Their site IDs become factory records in
a clearly marked legacy organization. Review ownership before enabling real access
controls. This does not copy a SQLite database into PostgreSQL. Cross-engine data
transfer remains an operator-reviewed export/import task.

## Ownership and shared knowledge

- Organization -> factory -> installed asset, with unique tags/serials per factory.
- Global catalogue model -> manufacturer/model/variant, category and source reference.
- Asset -> confirmed catalogue link. Shared model knowledge does not share private history.
- Global documents are immutable revisions, created as drafts and explicitly published.
- An assistant query can use the latest published document revision per title only
  after the installed asset has a confirmed catalogue link. Factory procedures are
  separately labelled; inspection execution stays pinned to its own procedure ID.

Assets, factory procedures and captures now require a registered factory. The
service returns 404 for unknown factories; database constraints also reject direct
orphan writes. Legacy SQLite tables use equivalent reference triggers to avoid
rebuilding evidence-bearing tables during migration.

The source reference is supplied provenance, not automatic manufacturer verification.
Publication requires a global curator or administrator. Factory memberships enforce
role-based access for individual bearer credentials; the development bootstrap key
retains administrative access. Switch to `POSIFY_AUTH_MODE=users` to disable that
key. See [identity and review](ACCESS_AND_REVIEW.md) for provisioning and role rules.
Variant applicability is manually confirmed; the service checks manufacturer/model
agreement and does not infer hardware or firmware configuration.

## APIs

- POST/GET `/v1/organizations`
- POST `/v1/factories`; GET `/v1/factories?organization_id=...`
- POST/GET `/v1/catalog/models`; listing excludes drafts unless requested
- POST `/v1/catalog/models/{id}/publish`
- POST/GET `/v1/catalog/models/{id}/documents`
- POST `/v1/catalog/documents/{id}/publish`
- POST/GET `/v1/sites/{site}/assets/{asset}/catalog-link`

Site-pack v2 retains its existing local inspection/capture contract. Catalogue
models and global documents are retrieved through their APIs and are not embedded
in that pack yet. Location/category editing is revision-checked. Catalogue-link and unattached-capture
corrections require independent review; physical identity-field corrections remain pending.
Review/correction records are read through their APIs and are not included in site packs.

## Local PostgreSQL / worker stack

The proposed Compose stack contains PostgreSQL 17, a one-shot migration service,
the API and a separate worker. No frontend is included. Set a generated API token
and URL-safe database password in `.env`, then run:

```bash
mkdir -p models
docker compose up --build
```

The API binds to host loopback port 8000. PostgreSQL is internal to the Compose
network. Database and captures use separate persistent volumes; provision model
artifacts under `models/` and refer to their `/models/...` paths inside containers.
The image includes Tesseract but not optional Paddle/E5/ONNX dependencies or weights.
Ollama on a host is not reachable through container localhost; configure an explicit
reachable runtime URL before enabling the model. No model is pulled automatically.
The container configuration is supplied but was not run in this development host,
which does not have Docker. CI separately verifies the PostgreSQL code paths.

Back up the database, capture volume and original-document volume together and rehearse restoration. Do not
run destructive downgrades; migrations deliberately require a reviewed backup/restore
plan for rollback. TLS, managed secrets, monitoring, storage quotas and retention policies remain
deployment work; analysis queue capacity is bounded separately.

## Installed asset metadata updates

`GET /v1/sites/{site}/assets/{asset}` returns the current asset, including `revision`.
Use that revision when changing location or category:

```http
PATCH /v1/sites/plant-a/assets/{asset}
X-API-Key: <instance token>
Content-Type: application/json

{"expected_revision":1,"reason":"Relocated during layout change","location":"Bay 2"}
```

A successful change increments the revision and records the reason plus before/after
values in the same transaction. A stale revision returns 409 with the current
revision; reload and review before resubmitting. An unchanged request at the current
revision is a no-op. Retrying a completed change with its old revision returns 409.
Tag, serial, manufacturer, model and factory cannot be changed through this route.
Existing assets receive revision 1 during migration 0005.

Audit queries support exact `entity_id` and `kind` filters alongside the existing
`after` sequence cursor and `limit`. For example, use
`/v1/sites/plant-a/audit?entity_id={asset}&kind=asset.updated` for metadata changes.
New audit events distinguish `user`, `bootstrap`, `operator` and `system` actors;
individual requests include `actor_id`. Pre-migration rows remain `legacy`. Historical captures and submitted inspection observations are preserved;
asset metadata in registry reads and site packs reflects the current value.
