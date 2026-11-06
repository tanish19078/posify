# Frontend-first redesign

## Scope

Posify is a free technical project, not a signup-led SaaS product. This milestone
improves the existing application instead of adding authentication products,
billing, training dashboards, or 3D. Existing backend authorization stays intact.

The useful journey remains: photo, reviewed evidence, confirmed asset, relevant
maintenance information, and an inspection. The current real vision capability
is nameplate detection and OCR; equipment-category models are future work.

## Design direction

- Navy navigation and image canvas: #10233F and #0B172A.
- Coral primary actions and selection accents: #FF7E6B.
- Light workspace background: #F4F6FA; white content panels.
- Navy text on coral buttons. Use the darker accent #B33B2E for links on light
  surfaces, rather than low-contrast light coral text.
- Keep success, caution, and error colors separate from brand accents.
- Reuse the existing fonts, Lucide icons, React/Vite stack, and API contracts.
- Keep photo evidence central and raw detector diagnostics expandable.

## Included in this first pass

- Central semantic theme tokens and workspace/navigation configuration.
- Posify branding and consistent navy-and-coral styling across existing pages.
- Workspace navigation: Identify equipment, Overview, Factory assets, Inspections.
- Reference navigation: Global catalogue and Knowledge.
- Signup-free, explicitly read-only demo with optional existing backend connection.
- Analysis controls before the result details, rather than beneath a long result.
- Review progress that follows capture/confirmation state instead of a fixed step.
- Responsive layouts and explicit separation between recorded demo evidence and
  analysis of a user's own photos.

## Recommended next increments

### 1. Complete the contextual workflow

Carry the selected asset and confirmed capture into inspections and knowledge
queries. Give asset details clear links to documents, evidence, and inspections.
Preserve context when returning to the photo. Keep every identity confirmation
explicit; do not create an asset automatically from OCR.

Done when a user can follow one capture through the workflow without repeatedly
searching for the same asset.

### 2. Improve practical capture and recovery

Improve mobile photo input, capture naming, and history navigation. Provide clear
routes for unreadable text, no matching asset, an unavailable worker, and missing
manuals. Support manual registry lookup without overwriting machine evidence.
Only show worker readiness when backed by a real health/heartbeat signal.

Done when recognition failure leaves an understandable next action rather than
a dead end. Add server-backed search/pagination before claiming full-registry
search beyond the current loaded-list limits.

### 3. Make maintenance information easier to reach

Show the linked model, available documents, and relevant procedure from the asset
context. Keep source references and document versions visible. Source browsing
must remain useful when the optional local AI model is not configured.

Done when the user can find applicable material and distinguish it from missing,
unverified, or unrelated content.

### 4. Validate a small real workflow

Use a small permitted set of factory assets, nameplate photos, manuals, and
procedures. Check narrow/mobile layouts, keyboard navigation, long identifiers,
empty results, connection failures, job cancellation, and confirmation rules.
Run frontend tests and the production build; review the real rendered pages.

Done when the photo-to-inspection workflow works against the configured backend,
not only the bundled demonstration records.

## Guardrails

- No signup, payment, or 3D scope in these increments.
- No pretend equipment detections, fake processing, or invented accuracy metrics.
- No browser-stored credentials or weakened API authorization.
- Preserve immutable evidence, audit history, role checks, and human confirmation.
- Add equipment-category detection only when actual model artifacts and an
  evaluated integration exist; the frontend redesign does not imply that work is done.
