import { expect, it } from "vitest";
import { analysisErrorMessage } from "./analysisErrors";

it("explains the failed worker component and supports older stored failures", () => {
  expect(analysisErrorMessage("detector_http_503")).toContain("ONNX Runtime");
  expect(analysisErrorMessage("ocr_http_503")).toContain("Tesseract");
  expect(analysisErrorMessage("component_http_503")).toContain("same model settings");
  expect(analysisErrorMessage("cancelled_by_user")).toContain("cancelled");
});
