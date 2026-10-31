import { afterEach, describe, expect, it, vi } from "vitest";
import { json, request, segment } from "./api";

afterEach(() => vi.unstubAllGlobals());
describe("API transport", () => {
  it("sends raw images with exactly one credential scheme", async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ capture: { id: "capture" } })),
      );
    vi.stubGlobal("fetch", fetcher);
    const blob = new Blob(["image bytes"], { type: "image/jpeg" });
    await request(
      { auth: "bearer", token: "private-token" },
      "/v1/sites/plant/captures",
      { method: "POST", body: blob, headers: { "Content-Type": "image/jpeg", "X-API-Key": "must-not-be-sent" } },
    );
    const init = fetcher.mock.calls[0][1] as RequestInit;
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe("Bearer private-token");
    expect(headers.has("X-API-Key")).toBe(false);
    expect(headers.get("Content-Type")).toBe("image/jpeg");
    expect(init.body).toBe(blob);
    expect(init.cache).toBe("no-store");
  });
  it("preserves validation and revision conflict messages", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: {
              message: "Asset changed; reload before updating",
              current_revision: 2,
            },
          }),
          { status: 409 },
        ),
      ),
    );
    await expect(
      request(
        { auth: "bootstrap", token: "dev-key" },
        "/v1/assets/x",
        json({ expected_revision: 1 }, "PATCH"),
      ),
    ).rejects.toThrow("Asset changed");
  });
  it("encodes identifiers as one URL segment", () =>
    expect(segment("plant/a?site=b")).toBe("plant%2Fa%3Fsite%3Db"));
});
