# Background capture analysis

A durable SQL queue allows API and inference to run as separate processes without
an additional message broker. It currently supports `ocr` and `detect_ocr` jobs.
It does not schedule model training, embedding builds or LLM chat requests.

## Request and poll

```http
POST /v1/sites/{site}/captures/{capture}/jobs
X-API-Key: <instance token>
Content-Type: application/json

{"id":"<client-generated UUID>","mode":"detect_ocr"}
```

202 returns the persistent job. Exact ID replays return the same job; changed
capture, factory or mode returns 409. GET `/v1/sites/{site}/jobs/{id}` reports
queued/running/succeeded/failed status, attempts and a typed analysis result.
GET `/v1/sites/{site}/jobs` lists recent records. The site filter is not user RBAC.

Run the worker with the same database, capture root, API token and model environment:

```bash
python -m posify.worker
# Process at most one eligible job, useful for controlled smoke checks:
python -m posify.worker --once
```

## Execution

A worker atomically claims a job, increments attempts and obtains a fencing token
with a default 300-second lease. Inference runs outside the database transaction.
Only the current unexpired claimant can publish an analysis and completed job in
one transaction. Crashed workers leave reclaimable jobs; stale results are discarded.
No per-job heartbeat is implemented. Configure the lease above measured job duration
and supervise/terminate hung worker processes separately.

Transient component failures retry up to three attempts with bounded exponential
backoff. Invalid/missing input fails without retry. A failed job remains failed;
submit a new UUID for an intentional retry after fixing the component. Claims,
reclaims, results and exhaustion are auditable. Public responses do not contain
worker claim tokens or raw exception traces. Queue quotas, cancellation and job
retention are not implemented.

`detect_ocr` runs the configured detector, then OCR on up to eight regions.
Nameplate/label detections take priority; otherwise equipment regions are used.
Coordinates are remapped to the original image. Empty detections trigger explicitly
labelled whole-image OCR. A missing detector is an error, not an OCR-only success.
The existing synchronous `/analyze` endpoint remains OCR-only for compatibility.
