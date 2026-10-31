# Architecture decisions

- Modular monolith: one FastAPI service, SQLite, explicit HTTP contracts. Avoid
  premature distributed transactions and infrastructure dependencies.
- Asset identity is site + tag, with optional site-unique serial. Visual category
  never establishes exact identity. Identifier matches always require confirmation.
- Procedures are immutable and scoped to site, manufacturer and model. Each
  inspection pins its procedure ID and version; future procedures do not alter it.
- Every observation has a client-generated UUID. Exact retries return the original;
  changed reuse returns 409. Writes and audit events commit in one transaction.
- Workflow state is deterministic: open -> submitted. Each step needs one explicit
  observation; unknown and failed findings are preserved, not treated as passes.
  Submitted records are immutable. Submission means recorded, not supervisor-approved.
- Site packs are transactionally consistent JSON snapshots, not signed packages or
  incremental sync feeds. Clients must not interpret a snapshot timestamp as a delta cursor.
- Language-model drafts have no mutation tools. Source excerpts are returned
  separately. Deterministic excerpt mode is the default and is labelled as such.
- Instance token protects all business endpoints. Health is public; docs require
  the token for business calls. Shared token has no user attribution or per-site RBAC.
- No CORS wildcard, arbitrary URL fetch, document upload, shell tools or machine control.
- Local HTTP inference is optional; the runtime URL is trusted operator configuration.
  The application does not fetch model names, credentials or endpoints from user text.
