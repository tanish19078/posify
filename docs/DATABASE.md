# Database, ownership and deployment

## Persistence

SQLAlchemy manages connections and parameter binding. Alembic revisions 0001–0004
adopt the original schema, add catalogue/factory ownership, add durable jobs and
enforce factory references. SQLite remains the default for local development;
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
Publication is a deliberate operator action. The instance API token currently grants
administrative access to all factories/catalogue records. Organization relationships
and site filtering DO NOT implement user-level tenant authorization. OIDC, role
checks and catalogue curator permissions remain required before multi-user deployment.
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
in that pack yet. Asset editing and reviewed link corrections are not implemented.

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

Back up the database and capture volume together and rehearse restoration. Do not
run destructive downgrades; migrations deliberately require a reviewed backup/restore
plan for rollback. TLS, managed secrets, individual identities, quotas, monitoring
and retention policies remain deployment work.
