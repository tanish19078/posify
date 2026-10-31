export function analysisErrorMessage(code: string | null): string {
  switch (code) {
    case "detector_http_503":
      return "The nameplate detector is unavailable in the analysis worker. Check its model manifest, ONNX file and installed ONNX Runtime, restart the worker, then run analysis again.";
    case "ocr_http_503":
      return "OCR is unavailable in the analysis worker. Enable Tesseract or provision PaddleOCR, check the engine and language/model files, restart the worker, then run analysis again.";
    case "component_http_503":
      return "An analysis component is unavailable. Check the detector and OCR setup in the worker process. The API and worker must use the same model settings. Restart the worker after configuration changes, then run analysis again.";
    case "cancelled_by_user":
      return "Analysis was cancelled. You can start a new analysis when ready.";
    case "execution_deadline":
      return "Analysis exceeded its processing deadline. Check worker health before trying again.";
    default:
      return code ? `Analysis could not finish (${code}). Check the analysis worker and try again.` : "Analysis failed. Check the configured worker and retry.";
  }
}
