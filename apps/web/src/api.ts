import type { Session } from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
export async function request<T>(
  session: Pick<Session, "token" | "auth">,
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const headers = new Headers(init.headers);
  headers.delete(session.auth === "bootstrap" ? "Authorization" : "X-API-Key");
  headers.set(
    session.auth === "bootstrap" ? "X-API-Key" : "Authorization",
    session.auth === "bootstrap" ? session.token : `Bearer ${session.token}`,
  );
  if (init.body && !(init.body instanceof Blob))
    headers.set("Content-Type", "application/json");
  const signal = init.signal
    ? AbortSignal.any([init.signal, AbortSignal.timeout(90000)])
    : AbortSignal.timeout(90000);
  const response = await fetch(path, {
    ...init,
    signal,
    headers,
    cache: "no-store",
  });
  if (!response.ok) {
    let detail: unknown;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = response.statusText;
    }
    const message =
      typeof detail === "string"
        ? detail
        : Array.isArray(detail)
          ? detail.map((x) => x.msg).join("; ")
          : JSON.stringify(detail);
    throw new ApiError(
      response.status,
      message || `Request failed (${response.status})`,
    );
  }
  if (init.headers && new Headers(init.headers).get("Accept") === "image/png")
    return (await response.blob()) as T;
  return response.status === 204
    ? (undefined as T)
    : ((await response.json()) as T);
}
export const json = (body: unknown, method = "POST"): RequestInit => ({
  method,
  body: JSON.stringify(body),
});
export const segment = (value: string) => encodeURIComponent(value);
export const sitePath = (site: string) => `/v1/sites/${segment(site)}`;
export const readable = (value: string) => value.replaceAll("_", " ");
export const date = (value: string) =>
  new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
