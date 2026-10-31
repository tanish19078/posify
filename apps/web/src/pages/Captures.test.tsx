import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { WorkspaceContext, type Workspace } from "../context";
import { demoAnalysis, demoAssets, demoSession } from "../demo";
import Captures from "./Captures";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
it("requires asset selection, physical attestation and a final confirmation before assigning evidence", async () => {
  URL.createObjectURL = vi.fn().mockReturnValue("blob:test");
  URL.revokeObjectURL = vi.fn();
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  let confirmed = false;
  const capture = {
    id: "capture-1",
    site_id: "demo-pune",
    sha256: "digest",
    width: 1600,
    height: 900,
    warnings: [],
    created_at: "2026-10-31T12:00:00Z",
  };
  const api = vi.fn(async (path: string, init?: RequestInit) => {
    if (path.includes("/jobs?")) return [];
    if (path.endsWith("/confirm")) {
      if (init?.method === "POST") confirmed = true;
      return confirmed
        ? {
            capture_id: capture.id,
            asset_id: demoAssets[0].id,
            confirmed_at: capture.created_at,
          }
        : null;
    }
    if (path.includes("/analyses")) return [demoAnalysis];
    if (path.includes("/image")) return new Blob(["image"]);
    if (path.startsWith("/v1/assets?")) return demoAssets;
    if (path.includes("/captures?")) return [capture];
    return capture;
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
      <Captures />
    </WorkspaceContext.Provider>,
  );
  const user = userEvent.setup();
  const button = await screen.findByRole("button", { name: /Confirm asset/ });
  expect((button as HTMLButtonElement).disabled).toBe(true);
  await user.selectOptions(
    screen.getByRole("combobox", { name: "Factory asset" }),
    demoAssets[0].id,
  );
  expect((button as HTMLButtonElement).disabled).toBe(true);
  await user.click(
    screen.getByRole("checkbox", {
      name: "I checked the physical asset against this record.",
    }),
  );
  expect((button as HTMLButtonElement).disabled).toBe(false);
  await user.click(button);
  expect(confirmed).toBe(false);
  await user.click(screen.getByRole("button", { name: "Confirm identity" }));
  await waitFor(() => expect(confirmed).toBe(true));
  const calls = vi
    .mocked(api)
    .mock.calls.filter(([, init]) => init?.method === "POST");
  expect(calls).toHaveLength(1);
  expect(JSON.parse(calls[0][1]!.body as string)).toEqual({
    asset_id: demoAssets[0].id,
    asset_confirmed: true,
  });
});
