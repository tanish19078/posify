import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { WorkspaceContext, type Workspace } from "../context";
import { demoAssets, demoSession } from "../demo";
import type { Capture, InspectionDetail, Procedure } from "../types";
import { Inspections } from "./Inspections";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("loads evidence choices already confirmed for the inspection asset", async () => {
  const procedure: Procedure = {
    id: "00000000-0000-4000-8000-000000000041",
    site_id: "demo-pune",
    manufacturer: demoAssets[0].manufacturer,
    model: demoAssets[0].model,
    title: "Nameplate check",
    version: 1,
    steps: [],
    source_text: "Inspect the nameplate.",
  };
  const detail: InspectionDetail = {
    id: "00000000-0000-4000-8000-000000000061",
    site_id: "demo-pune",
    asset_id: demoAssets[0].id,
    procedure_id: procedure.id,
    status: "open",
    created_at: "2026-10-31T12:40:00Z",
    observations: [],
    capture_ids: [],
  };
  const capture: Capture = {
    id: "00000000-0000-4000-8000-000000000021",
    site_id: "demo-pune",
    sha256: "digest",
    width: 1600,
    height: 900,
    warnings: [],
    created_at: "2026-10-31T12:00:00Z",
  };
  let capturePath = "";
  const api = vi.fn(async (path: string) => {
    if (path.startsWith("/v1/assets?")) return demoAssets;
    if (path.startsWith("/v1/procedures?")) return [procedure];
    if (path.includes("/reviews")) return [];
    if (path.includes("/captures?")) {
      capturePath = path;
      return [capture];
    }
    if (path.startsWith(`/v1/inspections/${detail.id}?`)) return detail;
    throw new Error(`Unexpected request: ${path}`);
  }) as Workspace["api"];

  render(
    <WorkspaceContext.Provider
      value={{
        api,
        site: "demo-pune",
        role: "technician",
        session: { ...demoSession, demo: false },
        notify: vi.fn(),
        navigate: vi.fn(),
      }}
    >
      <Inspections inspectionId={detail.id} />
    </WorkspaceContext.Provider>,
  );

  expect(await screen.findByRole("option", { name: /00000000/ })).toBeTruthy();
  await waitFor(() =>
    expect(capturePath).toContain(`asset_id=${demoAssets[0].id}`),
  );
});
