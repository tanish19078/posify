import { ApiError } from "./api";
import type {
  Analysis,
  Answer,
  Asset,
  Capture,
  Inspection,
  Model,
  Procedure,
  Session,
} from "./types";

const stamp = "2026-10-31T12:40:00Z";
export const demoSession: Session = {
  token: "",
  auth: "bearer",
  demo: true,
  me: {
    id: null,
    name: "Demo technician",
    type: "demo",
    is_admin: true,
    is_curator: true,
    memberships: [],
  },
  factories: [
    {
      id: "demo-pune",
      name: "Pune · Training facility",
      organization_id: "00000000-0000-4000-8000-000000000001",
      created_at: stamp,
    },
    {
      id: "demo-empty",
      name: "New facility · Empty workspace",
      organization_id: "00000000-0000-4000-8000-000000000001",
      created_at: stamp,
    },
  ],
};
export const demoAssets: Asset[] = [
  {
    id: "00000000-0000-4000-8000-000000000011",
    site_id: "demo-pune",
    tag: "CT-014",
    manufacturer: "Training Equipment Co.",
    model: "CT-15",
    serial: "DEMO-014",
    category: "Current transformer",
    location: "Electrical bay · Panel 03",
    revision: 1,
  },
  {
    id: "00000000-0000-4000-8000-000000000012",
    site_id: "demo-pune",
    tag: "P-104",
    manufacturer: "Training Equipment Co.",
    model: "P-200",
    serial: "DEMO-104",
    category: "Centrifugal pump",
    location: "Utility hall · Line 02",
    revision: 1,
  },
  {
    id: "00000000-0000-4000-8000-000000000013",
    site_id: "demo-pune",
    tag: "M-208",
    manufacturer: "Training Equipment Co.",
    model: "M-75",
    serial: "DEMO-208",
    category: "Electric motor",
    location: "Assembly floor · Line 04",
    revision: 1,
  },
];
const capture: Capture = {
  id: "00000000-0000-4000-8000-000000000021",
  site_id: "demo-pune",
  sha256: "a729433d438463bd8f2e6928070fe8ae39d718b2d30ac8f75df69ca3fe3cd5dc",
  width: 1600,
  height: 900,
  warnings: [],
  created_at: stamp,
};
export const demoAnalysis: Analysis = {
  id: "00000000-0000-4000-8000-000000000031",
  capture_id: capture.id,
  created_at: stamp,
  engine: "tesseract",
  inference_mode: "detect_ocr",
  status: "insufficient_evidence",
  requires_confirmation: true,
  candidates: [],
  identifiers: [],
  detector_revision: "nameplate-detector@v1",
  pipeline_warnings: [],
  detections: [
    {
      class_id: 0,
      label: "nameplate",
      confidence: 0.926398,
      box: [357.2186, 212.3747, 1529.6912, 838.5213],
    },
  ],
  lines: [
    { text: "Rated current ratio| 15/ 5A", confidence: 0.603, box: null },
    { text: "Rated insulation level 2", confidence: 0.121, box: null },
    { text: "Rated dynam! |", confidence: 0.68, box: null },
  ],
};
const procedure: Procedure = {
  id: "00000000-0000-4000-8000-000000000041",
  site_id: "demo-pune",
  manufacturer: demoAssets[0].manufacturer,
  model: demoAssets[0].model,
  title: "Training nameplate review",
  version: 1,
  steps: [
    {
      id: "visibility",
      instruction: "Record whether the training nameplate is readable.",
    },
    {
      id: "identity",
      instruction: "Record whether the displayed identifiers can be verified.",
    },
  ],
  source_text:
    "Synthetic training procedure. Record whether the nameplate is readable and whether identifiers can be verified. This is not an operational maintenance instruction.",
};
const models: Model[] = demoAssets.map((asset, i) => ({
  id: `00000000-0000-4000-8000-00000000005${i}`,
  manufacturer: asset.manufacturer,
  model: asset.model,
  category: asset.category,
  variant: "base",
  source_ref: "Illustrative training catalogue",
  status: "published",
  created_at: stamp,
}));
const inspection: Inspection = {
  id: "00000000-0000-4000-8000-000000000061",
  asset_id: demoAssets[0].id,
  procedure_id: procedure.id,
  status: "open",
  created_at: stamp,
};
export async function demoRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  await new Promise<void>((resolve, reject) => {
    if (init.signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(resolve, 160);
    init.signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
  if (init.method && init.method !== "GET") {
    if (path === "/v1/assistant/query")
      return {
        mode: "source_excerpts",
        answer: null,
        requires_review: true,
        retrieval_method: "lexical",
        notice:
          "Illustrative training source; connect your API to retrieve real factory knowledge.",
        citations: ["training-source"],
        sources: [
          {
            id: "training-source",
            title: procedure.title,
            version: 1,
            source_kind: "factory_procedure",
            procedure_id: procedure.id,
            excerpt: procedure.source_text,
          },
        ],
      } as Answer as T;
    throw new ApiError(
      400,
      "This is a read-only demo. Connect your backend to save changes.",
    );
  }
  const empty = path.includes("demo-empty");
  let value: unknown;
  if (path.includes("/image"))
    return (await (
      await fetch("/images/nameplate.jpg", { signal: init.signal })
    ).blob()) as T;
  if (path === "/v1/workspaces") value = demoSession.factories;
  else if (path.startsWith("/v1/assets?")) value = empty ? [] : demoAssets;
  else if (
    path.startsWith("/v1/catalog/models/") &&
    path.endsWith("/documents")
  )
    value = [];
  else if (path.startsWith("/v1/catalog/models")) value = models;
  else if (path.endsWith("/analyses")) value = [demoAnalysis];
  else if (path.endsWith("/confirm")) value = null;
  else if (path.endsWith("/catalog-link")) value = null;
  else if (path.includes("/captures/")) value = capture;
  else if (path.includes("/captures")) value = empty ? [] : [capture];
  else if (path.includes("/jobs")) value = [];
  else if (path.startsWith("/v1/procedures")) value = empty ? [] : [procedure];
  else if (path.startsWith("/v1/inspections/"))
    value = {
      ...inspection,
      site_id: "demo-pune",
      observations: [],
      capture_ids: [],
    };
  else if (path.startsWith("/v1/inspections"))
    value = empty ? [] : [inspection];
  else if (path.includes("/audit"))
    value = [
      {
        sequence: 1,
        kind: "capture.created",
        entity_id: capture.id,
        created_at: stamp,
        payload: { basis: "Demo record" },
      },
    ];
  else if (path === "/v1/runtime")
    value = {
      ocr: { configured: true, engine: "tesseract" },
      detector: { configured: true, model_id: "nameplate-detector@v1" },
      retrieval: { configured: false },
      assistant: { configured: false },
      database: { dialect: "demo" },
    };
  else
    throw new ApiError(
      404,
      "No demo data for this view. Connect your API for the full workflow.",
    );
  return value as T;
}
