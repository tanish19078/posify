import { afterEach, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import EquipmentEvidence from "./EquipmentEvidence";
import { demoAnalysis } from "../demo";
import type { Analysis } from "../types";

afterEach(cleanup);
it("shows a field proposal as unverified evidence and opens its exact source pixels", async () => {
  const inspect = vi.fn();
  const analysis: Analysis = {
    ...demoAnalysis,
    recognition_version: "plate-evidence-v1",
    equipment_status: "partial_evidence",
    equipment_fields: [
      {
        id: "field-1",
        field: "manufacturer",
        value: "ACME",
        raw_text: "ACME",
        attempt_id: "read-1",
        region_index: 0,
        line_index: 0,
        box: [10, 20, 100, 45],
        ocr_confidence: 0.96,
        basis: "explicit_label",
        status: "observed",
        corroborating_attempts: ["read-1"],
      },
    ],
    equipment_candidates: [
      {
        catalog_model_id: "00000000-0000-4000-8000-000000000001",
        manufacturer: "ACME",
        model: "AB-123",
        variant: "base",
        category: "Test motor",
        source_ref: "Synthetic fixture",
        status: "partial_evidence",
        matched_fields: ["manufacturer"],
        missing_fields: ["model"],
        conflicting_fields: [],
        evidence_ids: ["field-1"],
        retrieval_basis: "manufacturer_only",
        requires_review: true,
      },
    ],
  };
  render(<EquipmentEvidence analysis={analysis} inspect={inspect} />);
  expect(screen.getByText("Observed text")).toBeTruthy();
  expect(screen.getByText("Not supported: model")).toBeTruthy();
  expect(
    screen.getByText(/No physical machine has been confirmed/),
  ).toBeTruthy();
  expect(screen.queryByText("96%")).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "View source" }));
  expect(inspect).toHaveBeenCalledWith([10, 20, 100, 45]);
  expect(screen.queryByRole("button", { name: /confirm/i })).toBeNull();
});
