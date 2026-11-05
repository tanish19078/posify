# Identity, factory permissions and human review

## Runtime requirements

The core Python dependency lock covers these workflows; no identity provider or
additional service is required. Individual credentials are random opaque bearer
tokens. Only SHA-256 digests are stored; the credential is returned once at issue
time. Tokens default to 30 days, with an administrator-selected maximum of 90 days.
This is an operator-provisioned access system, not an OIDC/SSO or password login UI.

Run schema migrations before PostgreSQL API/worker startup. Revisions 0006 and 0007
add identities, memberships, named audit actors, inspection reviews and corrections.
Existing inspections retain null creator/submitter IDs and audit rows are labelled
`legacy`; historical individual attribution cannot be reconstructed.

## Initial administrator

For local development, the existing `X-API-Key` is a bootstrap administrator in
`POSIFY_AUTH_MODE=development`. It can provision people and memberships. Bootstrap
credentials cannot perform inspection reviews or request/approve corrections.
Those operations require a named individual.

For bearer-only operation, provision the first administrator directly against the
configured database before starting the API:

```bash
mkdir -p credentials
python scripts/create_admin.py --name 'Factory administrator' \
  --output credentials/admin.credentials.json
export POSIFY_AUTH_MODE=users
uvicorn posify.app:app --host 127.0.0.1 --port 8000
```

The CLI creates the credential file with mode 0600 and refuses to overwrite an
existing path. Database migrations must already be applied for PostgreSQL.
Protect this file, use HTTPS for non-loopback access and distribute individual
credentials privately. Files under `credentials/` and `*.credentials.json` are ignored
by Git. No credentials are included in the repository. In containers, run provisioning
from an operator session sharing the configured database and retrieve the private
output file through your normal secrets workflow.

Requests use `Authorization: Bearer <token>`. Do not also send `X-API-Key`.
`POSIFY_AUTH_MODE=users` rejects the bootstrap key, even when one is configured.
Disabling a user revokes all of their existing tokens; re-enabling them requires
issuing a new token. Revocation and membership checks occur on every new request;
an already authorized in-flight request may finish.

## Provisioning API

All `/v1/access/*` routes require administrator permission.

| Route | Purpose |
| --- | --- |
| `POST /v1/access/users` | Create a named user with optional global admin/curator flags |
| `GET /v1/access/users` | Paginated user directory |
| `PATCH /v1/access/users/{id}` | Enable/disable a user; administrators cannot disable themselves |
| `PUT /v1/access/users/{id}/factories/{site}` | Set `viewer`, `technician`, `supervisor` or `manager` role |
| `DELETE /v1/access/users/{id}/factories/{site}` | Remove factory access |
| `POST /v1/access/users/{id}/tokens` | Issue a token using `{"lifetime_days":30}` |
| `GET /v1/access/users/{id}/tokens` | List token metadata without digests or credentials |
| `DELETE /v1/access/tokens/{id}` | Revoke a token |
| `GET /v1/me` | Inspect your identity, global flags and factory memberships |

Factory roles are cumulative: viewer < technician < supervisor < manager.

| Operation | Minimum factory role |
| --- | --- |
| Read records, images, audit, packs; query identity/assistant | Viewer |
| Upload/analyze/confirm captures; run/cancel jobs; record inspections | Technician |
| Review submitted inspections and decide correction requests | Supervisor |
| Create assets/procedures; edit asset metadata; establish catalogue links; request corrections | Manager |

A membership is required in the exact factory used by the endpoint. Body-scoped
routes authorize the body factory; query parameters cannot override it. A global
administrator can access every factory. Catalogue curators can create/publish
shared knowledge and read drafts; ordinary users can read published global material.
Organization/factory provisioning, runtime configuration and user administration
remain global administrator operations. Unknown protected routes fail closed for
ordinary users. Factory membership does not grant catalogue publication permission.

## Inspection review

`GET /v1/inspections?site_id=plant-a&unreviewed=true` lists submitted inspections
awaiting review. Normal status and pagination filters are also available.

```http
POST /v1/sites/plant-a/inspections/{inspection}/reviews
Authorization: Bearer <supervisor credential>
Content-Type: application/json

{"id":"<client UUID>","outcome":"follow_up","note":"Arrange a clearer inspection of the obscured label."}
```

Only submitted inspections can be reviewed. The reviewer must differ from the
recorded creator, submitter and named observation authors. `accepted` is allowed only when every observation
is `pass`; failed/unknown observations require `follow_up`. Neither outcome proves
that equipment is safe to operate. Review records are immutable and do not rewrite
observations or change the inspection's submitted state. Exact UUID/payload/reviewer
replays are safe; changed reuse returns 409. GET the same route to read reviews.
A follow-up decision does not automatically create a work order.

## Confirmed link corrections

A manager requests a change; another named supervisor/manager approves or rejects
it. A requester cannot decide their own request. Approval rechecks factory ownership,
current confirmed values, applicability and (for catalogue links) asset revision.
Stale requests return 409 and can be rejected before creating a new request.

| Request route | Body fields |
| --- | --- |
| `POST /v1/sites/{site}/assets/{asset}/corrections` | `id`, `expected_revision`, `catalog_model_id`, `reason` |
| `POST /v1/sites/{site}/captures/{capture}/corrections` | `id`, `asset_id`, `reason` |
| `GET /v1/sites/{site}/corrections?status=pending` | Paginated request list |
| `POST /v1/sites/{site}/corrections/{id}/decision` | `decision`: `approved`/`rejected`, plus `note` |

Catalogue corrections must retain manufacturer/model agreement and target a published
model; an approved change increments the installed asset revision. Physical identity
fields (tag, serial, manufacturer/model) remain fixed. Capture assignment corrections
are blocked once that capture is attached to any inspection, including an open one.
Historical OCR analyses remain snapshots; they are not rewritten after a correction.
Request UUIDs and matching decision retries are safe. Final decisions are immutable.

## Remaining deployment work

SSO, durable browser sessions, self-service credential rotation, privileged-action
reauthentication, rate limiting, access review and external audit export are not
implemented. The web client accepts operator-provisioned bearer credentials, keeps
them only in React memory, and clears them on refresh or disconnect. It does not use
cookies, local storage or IndexedDB for credentials.
