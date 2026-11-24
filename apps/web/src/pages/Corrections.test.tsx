import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { WorkspaceContext, type Workspace } from "../context";
import { demoAssets, demoSession } from "../demo";
import type { Correction, Model } from "../types";
import { Corrections } from "./Corrections";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const models: Model[] = [
  {
    id: "00000000-0000-4000-8000-000000000101",
    manufacturer: demoAssets[0].manufacturer,
    model: demoAssets[0].model,
    variant: "base",
    category: demoAssets[0].category,
    source_ref: "Manual v1",
    status: "published",
    created_at: "2026-11-01T10:00:00Z",
  },
  {
    id: "00000000-0000-4000-8000-000000000102",
    manufacturer: demoAssets[0].manufacturer,
    model: demoAssets[0].model,
    variant: "tropicalized",
    category: demoAssets[0].category,
    source_ref: "Manual v2",
    status: "published",
    created_at: "2026-11-01T10:00:00Z",
  },
];

function setupMocks() {
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
}

it("blocks requester from self-approving a pending correction", async () => {
  setupMocks();
  const requesterId = "11111111-1111-4111-8111-111111111111";
  const pending: Correction = {
    id: "22222222-2222-4222-8222-222222222222",
    site_id: "demo-pune",
    entity_kind: "asset_catalog",
    entity_id: demoAssets[0].id,
    expected_revision: 1,
    before_value: models[0].id,
    after_value: models[1].id,
    reason: "Physical plate shows tropicalized variant",
    requested_by: requesterId,
    status: "pending",
    reviewed_by: null,
    review_note: null,
    created_at: "2026-11-02T09:00:00Z",
    reviewed_at: null,
  };
  const api = vi.fn(async (path: string) => {
    if (path.includes("/corrections")) return [pending];
    if (path.startsWith("/v1/assets?")) return demoAssets;
    if (path.includes("/captures?")) return [];
    if (path.startsWith("/v1/catalog/models")) return models;
    throw new Error(`Unexpected request: ${path}`);
  }) as Workspace["api"];

  render(
    <WorkspaceContext.Provider
      value={{
        api,
        site: "demo-pune",
        role: "manager",
        session: {
          ...demoSession,
          demo: false,
          me: { ...demoSession.me, id: requesterId, is_admin: false },
        },
        notify: vi.fn(),
        navigate: vi.fn(),
      }}
    >
      <Corrections />
    </WorkspaceContext.Provider>,
  );

  expect(
    await screen.findByText(/Self-review blocked/i),
  ).toBeTruthy();
  const approve = screen.getByRole("button", { name: "Approve" }) as HTMLButtonElement;
  const reject = screen.getByRole("button", { name: "Reject" }) as HTMLButtonElement;
  expect(approve.disabled).toBe(true);
  expect(reject.disabled).toBe(true);
});

it("allows an independent supervisor to approve a pending correction with a review note", async () => {
  setupMocks();
  const requesterId = "11111111-1111-4111-8111-111111111111";
  const supervisorId = "33333333-3333-4333-8333-333333333333";
  let current: Correction = {
    id: "22222222-2222-4222-8222-222222222222",
    site_id: "demo-pune",
    entity_kind: "asset_catalog",
    entity_id: demoAssets[0].id,
    expected_revision: 1,
    before_value: models[0].id,
    after_value: models[1].id,
    reason: "Physical plate shows tropicalized variant",
    requested_by: requesterId,
    status: "pending",
    reviewed_by: null,
    review_note: null,
    created_at: "2026-11-02T09:00:00Z",
    reviewed_at: null,
  };
  const api = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.endsWith("/decision") && init?.method === "POST") {
      const payload = JSON.parse(init.body as string);
      current = {
        ...current,
        status: payload.decision,
        review_note: payload.note,
        reviewed_by: supervisorId,
        reviewed_at: "2026-11-02T10:00:00Z",
      };
      return current;
    }
    if (path.includes("/corrections")) return [current];
    if (path.startsWith("/v1/assets?")) return demoAssets;
    if (path.includes("/captures?")) return [];
    if (path.startsWith("/v1/catalog/models")) return models;
    throw new Error(`Unexpected request: ${path}`);
  }) as Workspace["api"];

  render(
    <WorkspaceContext.Provider
      value={{
        api,
        site: "demo-pune",
        role: "supervisor",
        session: {
          ...demoSession,
          demo: false,
          me: { ...demoSession.me, id: supervisorId, is_admin: false },
        },
        notify: vi.fn(),
        navigate: vi.fn(),
      }}
    >
      <Corrections />
    </WorkspaceContext.Provider>,
  );

  const user = userEvent.setup();
  const approve = (await screen.findByRole("button", {
    name: "Approve",
  })) as HTMLButtonElement;
  expect(approve.disabled).toBe(false);
  await user.click(approve);
  await user.type(
    screen.getByLabelText("Review note"),
    "Verified variant stamp on site",
  );
  await user.click(screen.getByRole("button", { name: /Confirm approval/ }));

  await waitFor(() =>
    expect(screen.getByText("Approved")).toBeTruthy(),
  );
  const postCalls = vi
    .mocked(api)
    .mock.calls.filter(([, init]) => init?.method === "POST");
  expect(postCalls).toHaveLength(1);
  expect(postCalls[0][0]).toBe(
    `/v1/sites/demo-pune/corrections/${current.id}/decision`,
  );
  expect(JSON.parse(postCalls[0][1]!.body as string)).toEqual({
    decision: "approved",
    note: "Verified variant stamp on site",
  });
});
