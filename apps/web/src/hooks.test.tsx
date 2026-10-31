import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { useLoad } from "./hooks";

afterEach(cleanup);
it("clears old factory data and ignores a stale response after switching factories", async () => {
  const pending = new Map<string, (value: string) => void>();
  const { result, rerender } = renderHook(
    ({ site }) =>
      useLoad(
        () => new Promise<string>((resolve) => pending.set(site, resolve)),
        [site],
      ),
    { initialProps: { site: "plant-a" } },
  );
  rerender({ site: "plant-b" });
  act(() => pending.get("plant-b")!("Plant B assets"));
  await waitFor(() => expect(result.current.data).toBe("Plant B assets"));
  act(() => pending.get("plant-a")!("Private Plant A assets"));
  expect(result.current.data).toBe("Plant B assets");
  rerender({ site: "plant-c" });
  expect(result.current.data).toBeUndefined();
});
