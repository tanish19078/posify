import { useEffect, useState } from "react";

export function useLoad<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
) {
  const [data, setData] = useState<T>();
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setData(undefined);
    setError("");
    setLoading(true);
    loader(controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) setData(value);
      })
      .catch((e) => {
        if (!controller.signal.aborted)
          setError(e instanceof Error ? e.message : "Unable to load data");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [...deps, version]);
  return { data, error, loading, reload: () => setVersion((x) => x + 1) };
}
export function useRoute() {
  const read = () => location.hash.slice(1).split("/").filter(Boolean);
  const [route, setRoute] = useState(read);
  useEffect(() => {
    const listener = () => setRoute(read());
    window.addEventListener("hashchange", listener);
    return () => window.removeEventListener("hashchange", listener);
  }, []);
  return route;
}
