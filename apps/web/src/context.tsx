import { createContext, useContext } from "react";
import { request } from "./api";
import { demoRequest } from "./demo";
import type { Session } from "./types";

export interface Workspace {
  session: Session;
  site: string;
  role: string;
  notify: (message: string) => void;
  navigate: (path: string) => void;
  api: <T>(path: string, init?: RequestInit) => Promise<T>;
}
export const WorkspaceContext = createContext<Workspace | null>(null);
export const makeApi = (session: Session): Workspace["api"] =>
  session.demo ? demoRequest : (path, init) => request(session, path, init);
export function useWorkspace() {
  const context = useContext(WorkspaceContext);
  if (!context) throw new Error("Workspace is required");
  return context;
}
