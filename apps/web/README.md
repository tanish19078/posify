# Field workspace

The web client for equipment evidence, factory assets and traceable inspections.
React, TypeScript and Vite; self-hosted DM Sans / Manrope fonts and Lucide icons.
The Warm Workbench design uses a light canvas, olive actions and explicit review
boundaries. It includes responsive navigation, keyboard search, native modal
dialogs, empty/error states and reduced-motion support.

## Run

Use Node.js 24 and the existing Python backend. From this directory:

```bash
npm ci
npm run dev
```

Open the printed Vite URL. The initial workspace is a clearly labelled,
read-only demo. Registry records are fictional; the motor image and structured evidence come from the recorded local PP-OCRv6
recognition smoke run. Model catalogue references are photo transcriptions, with
an explicitly synthetic near-code distractor. They are not manufacturer verification.
Photo attribution is in [public/images/CREDITS.md](public/images/CREDITS.md).
No model runs in the browser and demo mode never pretends to analyze an upload.

Start the API and a separate analysis worker using the root README. Choose
**Connection settings**, select an individual bearer token or development
bootstrap key, and paste its credential. The Vite proxy defaults to
`http://127.0.0.1:8000`; override its server-side target with `POSIFY_API_URL`
before starting Vite. Use a trusted target. Credentials are never built into JS,
written to browser storage, or included in URLs. Refresh clears the connection.
Factories are discovered through the authenticated membership-scoped endpoint.
Accounts without factory access can still browse the global catalogue; curators can
also create and publish global records without a factory membership.

## Workflows

- **Captures:** raw PNG/JPEG uploads, bounded history, image zoom/crop, measured
  detection overlays, structured source-linked fields, catalogue agreement checks, raw OCR, durable worker jobs, cancellation and explicit
  human confirmation. A score never establishes asset identity.
- **Factory assets:** filter and register physical assets, inspect records,
  update location/category with revision protection and reason, and confirm a
  shared model link. Manager operations remain enforced by the backend.
- **Global catalogue:** browse published models; curators can create drafts,
  import PDFs, review extracted text and explicitly publish models/documents.
- **Knowledge:** browse versioned procedures and retrieve source-labelled,
  cited excerpts for a selected asset. Optional model drafts remain reviewable.
- **Inspections:** select matching procedures, confirm physical identity,
  record pass/fail/unknown findings, attach confirmed captures and submit an
  immutable record. Independent supervisor reviews use individual credentials.
- **Activity:** inspect the first 100 factory audit events in sequence.

Lists show their loading bounds. This first client does not yet provide deep
pagination, organization/user provisioning or the reviewed correction workflow.
Those backend functions remain available through the API. Provision factories,
memberships and individual tokens before using a production connection.

## Contracts and checks

```bash
npm run contracts       # regenerate src/contracts.d.ts from the tracked OpenAPI
npm run contracts:check
npm test
npm run build
```

Generated schema types come from `packages/contracts/openapi.json`; API runtime
errors remain explicit. Factory changes unmount scoped state, abort reads and
discard late responses. Capture images are fetched with authorization and shown
through object URLs that are revoked on replacement/unmount.

## Deployment

From the repository root, `docker compose up --build` includes the web service
at `http://127.0.0.1:8080`. Nginx serves the compiled client and forwards `/v1/`
and `/health` to the API on the same origin. The API and worker keep model weights,
database access and inference separate from the browser. Configure TLS at your
deployment ingress and use individual credentials for production.

The frontend Docker build is self-contained; fonts and image assets are local.
No third-party analytics, external font calls or browser API credentials are
included. The local development preview is not a production deployment.
