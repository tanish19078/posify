import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import App from "./App";

afterEach(() => {
  cleanup();
  location.hash = "";
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

it("opens a signup-free identification demo with grouped navigation", async () => {
  vi.stubGlobal("scrollTo", vi.fn());
  URL.createObjectURL = vi.fn().mockReturnValue("blob:demo-image");
  URL.revokeObjectURL = vi.fn();
  const fetchImage = vi.fn(
    async (_input: RequestInfo | URL) =>
      new Response("demo-image", { headers: { "Content-Type": "image/jpeg" } }),
  );
  vi.stubGlobal("fetch", fetchImage);

  render(<App />);

  expect(
    screen.getByRole("heading", { name: "Identify equipment" }),
  ).toBeTruthy();
  expect(screen.getByText(/No signup needed/)).toBeTruthy();
  const navigation = within(
    screen.getByRole("navigation", { name: "Main navigation" }),
  );
  expect(navigation.getByText("Workspace")).toBeTruthy();
  expect(navigation.getByText("Reference")).toBeTruthy();
  expect(
    navigation
      .getByRole("link", { name: "Identify equipment" })
      .getAttribute("aria-current"),
  ).toBe("page");
  expect(
    navigation
      .getByRole("link", { name: "Global catalogue" })
      .getAttribute("href"),
  ).toBe("#/catalogue");
  expect(screen.queryByRole("dialog")).toBeNull();

  const analyze = await screen.findByRole("button", { name: "Run again" });
  expect((analyze as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/Recorded demo result/)).toBeTruthy();
  await waitFor(() => expect(fetchImage).toHaveBeenCalled());
  expect(
    fetchImage.mock.calls.every(([input]) => String(input).startsWith("/images/")),
  ).toBe(true);
});

it("opens the global catalogue for a curator without factory access", async () => {
  vi.stubGlobal("scrollTo", vi.fn());
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL) => {
      const path = String(input);
      const body = path.endsWith("/v1/me")
        ? {
            id: "curator-1",
            name: "Catalogue curator",
            type: "user",
            is_admin: false,
            is_curator: true,
            memberships: [],
          }
        : path.endsWith("/v1/workspaces") ||
            path.startsWith("/v1/catalog/models")
          ? []
          : null;
      return new Response(JSON.stringify(body), {
        status: body === null ? 404 : 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );

  render(<App />);
  const user = userEvent.setup();
  fireEvent.click(
    screen.getByRole("button", { name: "Connection settings" }),
  );
  await screen.findByRole("heading", { name: "Connect your backend" });
  await user.type(
    await screen.findByLabelText(/Access credential/),
    "curator-token",
  );
  await user.click(screen.getByRole("button", { name: /Connect workspace/ }));

  expect(
    await screen.findByRole("heading", { name: "One catalogue. Many factories." }),
  ).toBeTruthy();
  expect(screen.getByText("Global catalogue access")).toBeTruthy();
  expect(screen.queryByText("No factory access yet")).toBeNull();
  expect(screen.queryByRole("button", { name: "Find an asset" })).toBeNull();
});
