# PDF document ingestion and page citations

The core requirements include pinned `pypdf`. No training, remote URL fetch or
PDF script execution is performed. Imports require a global curator or administrator;
factory manager permission alone cannot publish shared manufacturer knowledge.

```bash
curl -X POST 'http://127.0.0.1:8000/v1/catalog/models/MODEL_UUID/pdf?title=Manual&revision=1&source_ref=Manufacturer-manual' \
  -H "Authorization: Bearer $POSIFY_USER_TOKEN" \
  -H 'Content-Type: application/pdf' --data-binary @manual.pdf
```

The response contains a new draft document, the SHA-256 of the original PDF,
its page count and page numbers with no extracted text. Inspect the extracted
`source_text` through the catalogue document API before explicitly publishing the
revision. A PDF title/revision conflict returns 409; choose another revision for a
new import. Importing a document never publishes its catalogue model.

Limits: 8 MiB original bytes, 100 pages and 30,000 extracted characters including
page separators. Split larger manuals into deliberately labelled sections. Extraction
runs in a Linux resource-limited subprocess (768 MiB address space, 5 CPU seconds,
12-second wall timeout). Unsupported resource-limit environments return 503; use the
Linux container runtime for deployment. Invalid, encrypted and image-only PDFs are
rejected. Mixed documents report empty pages explicitly. PDF OCR and visual diagram
interpretation are not implemented; do not assume empty pages contain no instructions.

Original PDF files are stored by content hash under `POSIFY_DOCUMENT_DIR`, defaulting
to a `documents` directory beside the configured local DB path. Compose mounts
`/data/documents` as a separate persistent volume. Store backups together with the
database and captures. Failed database writes may leave an orphan file; automatic
storage garbage collection and retention policies remain pending.

`GET /v1/catalog/documents/{document}/pdf` downloads the original as an attachment.
Curators/admins can access drafts; other authenticated users can download only a
published document belonging to a published model. Responses disable caching and
content sniffing. An absent original returns 410. A supplied source reference and
content digest record provenance, not authenticity or manufacturer approval.

Applicable published PDF pages enter retrieval through the installed asset's
confirmed catalogue link. Returned source excerpts include the original one-based
`page_number` and IDs such as `document-uuid:p2:0`; chunks do not cross page boundaries.
Plain text catalogue documents retain null page numbers. Historical PDF revisions
remain immutable and inspection execution still uses its pinned factory procedure.
Global documents and original PDFs are not embedded in site-pack snapshots.

E5 passage caching remains downstream of factory/model applicability filtering.
The database stores normalized vectors keyed by model fingerprint and passage hash,
not user questions or answer drafts. Removing/replacing a model creates a new cache
namespace after process restart. Cache pruning and ANN indexing are separate future
operating tasks; the semantic candidate limit remains 256 chunks.
