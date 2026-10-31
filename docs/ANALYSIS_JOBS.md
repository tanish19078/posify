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
GET `/v1/sites/{site}/jobs` lists recent records. Individual credentials require membership in the requested factory.

Run the worker with the same database, capture root, authentication mode and model environment:

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
A heartbeat renews the current unexpired claim every third of the lease duration.
Renewal stops after `POSIFY_JOB_DEADLINE_SECONDS` (default 1800) or loss of ownership.
Results arriving after that deadline are discarded/failed, and expired claims remain
reclaimable. Renewal does not resurrect expired/cancelled claims. Supervise and
terminate hung native worker processes separately; heartbeats are not process isolation.

Transient component failures retry up to three attempts with bounded exponential
backoff. Invalid/missing input fails without retry. A failed job remains failed;
submit a new UUID for an intentional retry after fixing the component. Claims,
reclaims, results and exhaustion are auditable. Public responses do not contain
worker claim tokens or raw exception traces. Outstanding jobs are bounded per factory by `POSIFY_QUEUE_LIMIT` (default 100).
New jobs over capacity return 429; exact retries remain safe. Job retention is pending.

`detect_ocr` runs the configured detector, then OCR on up to eight regions.
Nameplate/label detections take priority; otherwise equipment regions are used.
Coordinates are remapped to the original image. Empty detections trigger explicitly
labelled whole-image OCR. A missing detector is an error, not an OCR-only success.
The existing synchronous `/analyze` endpoint remains OCR-only for compatibility.

## Cancellation

`POST /v1/sites/{site}/jobs/{job}/cancel` requires technician permission. It clears
the claim and records terminal `status=failed`, `error_code=cancelled_by_user`.
Repeated cancellation is safe. Completed successes and other failures return 409.
Cancellation fences any in-flight result; it does not terminate native inference
already running in the worker process. No analysis is saved by a cancelled claim.
The synchronous OCR compatibility endpoint does not use the queue capacity limit.
