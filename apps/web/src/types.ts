import type { components } from "./contracts";
type S = components["schemas"];
export type Asset = S["Asset"];
export type Capture = S["Capture"];
export type Analysis = S["CaptureAnalysis"];
export type Job = S["AnalysisJob"];
export type Assignment = S["CaptureAssignment"];
export type Model = S["CatalogModel"];
export type Document = S["CatalogDocument"];
export type Procedure = S["Procedure"];
export type Inspection = S["Inspection"];
export type InspectionDetail = S["InspectionDetail"];
export type Answer = S["AssistantResponse"];
export type Factory = S["Factory"];
export interface Principal {
  id: string | null;
  name: string | null;
  type: string;
  is_admin: boolean;
  is_curator: boolean;
  memberships: { site_id: string; role: string }[];
}
export interface Session {
  token: string;
  auth: "bearer" | "bootstrap";
  demo: boolean;
  me: Principal;
  factories: Factory[];
}
