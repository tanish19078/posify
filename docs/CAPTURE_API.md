# Capture and inspection evidence API

All calls require `X-API-Key`. Shared-token development access is instance-wide;
site filters are not a substitute for per-user site authorization.

Register an organization/factory before uploading. See [database and ownership](DATABASE.md).

## Upload

```bash
curl -X POST http://127.0.0.1:8000/v1/sites/plant-a/captures \
  -H "X-API-Key: $POSIFY_API_TOKEN" \
  -H 'Content-Type: image/jpeg' --data-binary @nameplate.jpg
```

Send raw PNG/JPEG bytes, not multipart or base64. The service reads at most 8 MiB,
checks encoding and dimensions before full decoding (6 million pixels, maximum
4096 pixels per side), applies EXIF orientation and rewrites metadata-free PNG.
Small-image and low-contrast flags are capture heuristics, not a quality guarantee.
No blur classifier, equipment detector or QR decoder runs during upload.

The response contains `capture.id`, its site, dimensions, sanitized-content hash
and warnings. An exact sanitized-image retry within the same site returns the
original capture with `replayed: true`. Cross-site uploads have separate records.
Raw images are not committed to Git. Keep the database and image directory together
in backups. Storage files may be orphaned after a failed DB write; no GC is implemented.

## Analyze / review

- `POST /v1/sites/{site}/captures/{capture}/analyze`: run configured local OCR;
  persist a new analysis record with OCR lines, identifier evidence and candidates.
- `GET /v1/sites/{site}/captures/{capture}/analyses`: retrieve prior analyses.
- `GET /v1/sites/{site}/captures/{capture}`: capture metadata.
- `GET /v1/sites/{site}/captures/{capture}/image`: protected sanitized image bytes.

Analysis is a new inference run each time, not an idempotent observation operation.
Historical candidates are snapshots, not current authorizations or automatic asset
assignments. Empty, ambiguous and contradictory evidence is preserved explicitly.

## Confirm and attach

```http
POST /v1/sites/plant-a/captures/{capture_id}/confirm
Content-Type: application/json

{"asset_id":"<asset UUID>","asset_confirmed":true}
```

A technician may confirm a known asset manually even if OCR abstains. Confirmation
requires the capture and asset to belong to the same site. Exact retries return the
same assignment; changing the asset returns 409. Assignment correction/review is
not implemented yet.

Create an inspection through `/v1/inspections`, then attach:

```http
POST /v1/sites/plant-a/inspections/{inspection_id}/evidence
Content-Type: application/json

{"capture_id":"<capture UUID>"}
```

Only a capture confirmed for that inspection's asset can be attached. Exact retries
are safe. Submitted inspections reject new evidence. Attachment does not complete
any inspection step; record its result separately through the observation API.

Site-pack schema version 2 adds `captures`, `capture_assignments` and
`inspection_evidence`. Image bytes and OCR analyses are not embedded in packs;
a future web client must separately download/cache required image content.
The snapshot is not a delta cursor. Older clients must reject unsupported versions.

## Local walkthrough

Run `python scripts/capture_demo.py` against the local API, configured with
`POSIFY_OCR_ENGINE=tesseract`. This creates explicitly synthetic nameplate data,
verifies real OCR, confirms identity, attaches evidence and submits an inspection.
It does not train or evaluate an industrial detector.

For background OCR/detector execution, use the [job endpoints](ANALYSIS_JOBS.md). Synchronous analysis remains OCR-only.
