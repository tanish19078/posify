# Operations and recovery

## Runtime signals

`GET /health` is a public database connectivity check. Administrators can read
`GET /v1/runtime` for model/configuration status and `GET /v1/operations` for
per-factory queue counts, pending submitted-inspection reviews and pending correction
requests. These JSON endpoints can feed a monitoring system; they do not configure
an external collector, alert routing, model accuracy checks or disk-capacity alarms.

Worker claims renew at one third of their lease duration. Renewal ends at the
configured job deadline, on cancellation, on expiry or after database-contact loss.
A cancelled/stale claimant cannot commit an analysis. Native inference is not forcibly
terminated; use process supervision for hung runtimes. Apply schema migrations with
one operator before API/worker startup; never migrate while taking a snapshot.

## Portable application snapshots

The existing dependency stack provides operator-run snapshot tools for SQLite and
PostgreSQL. A snapshot includes all application tables, credential digests, referenced
capture PNGs and original imported PDFs. Model weights and runtime configuration
are provisioned separately and are not copied. Output directories are created with
mode 0700 and files with mode 0600. An existing snapshot directory is never overwritten.

```bash
mkdir -p backups
python scripts/snapshot.py backup backups/checkpoint-001
```

`POSIFY_DB` / `POSIFY_DATABASE_URL`, `POSIFY_CAPTURE_DIR` and `POSIFY_DOCUMENT_DIR`
select the stores. Keep the resulting directory private and use encrypted storage
and your organization's access/retention rules. It contains confidential records;
Git ignores `backups/`. Checksums detect accidental modification, not an attacker
able to rewrite the manifest. The snapshot is not signed or encrypted by the tool.

The database is read under a consistent snapshot. Referenced evidence is immutable
and content-addressed, so subsequent uploads do not change the exported evidence.
All referenced files must exist and match their stored digest or backup fails.
A failed backup may leave an incomplete directory; do not treat it as a checkpoint.
The manifest is written last. The current exporter materializes table rows in memory;
large installations should use a measured native database backup strategy.

## Restore rehearsal

Stop API/worker processes for the restore target. Configure a fresh database and
empty capture/document directories. PostgreSQL targets must be migrated separately;
SQLite targets auto-migrate. The target schema revision must match the snapshot.

```bash
export POSIFY_DB=var/rehearsal.db
export POSIFY_CAPTURE_DIR=var/rehearsal-captures
export POSIFY_DOCUMENT_DIR=var/rehearsal-documents
python scripts/snapshot.py restore backups/checkpoint-001
```

If `POSIFY_DATABASE_URL` is set, it takes precedence over `POSIFY_DB`; point it at
the intended empty restore database/schema. Restore refuses nonempty application
tables or evidence directories. It checks table/column sets, row counts, evidence
references and file checksums before loading records. PostgreSQL audit sequences
are advanced beyond restored events. No existing application records are replaced.
Database inserts are transactional; a filesystem failure can leave newly copied
orphan files after rollback. Recreate the empty rehearsal target before retrying.

After restore, verify counts, protected image/PDF downloads, named access and a
new audit write before exposing the target. Restored credential/revocation state
matches snapshot time; review access before reopening service. Old running jobs
become reclaimable after their restored leases expire. Automated restore rehearsal
covers both supported databases in CI; deployment-volume and host recovery remain
operator responsibilities.

Automatic evidence deletion, cache pruning, record retention and production backup
scheduling are intentionally unset until the operator specifies a retention policy.
