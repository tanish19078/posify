# External YOLO11 ONNX inference contract

Training stays in a separate Colab workflow. This repository contains only input
preprocessing, artifact validation, inference integration and output decoding.
No detector weights are committed, downloaded or trained.

Install the optional inference runtime with `pip install -e '.[detector]'` and
point `POSIFY_DETECTOR_MANIFEST` at a local JSON manifest. It must contain:

```json
{
  "model_id": "your-equipment-detector",
  "revision": "your-reviewed-revision",
  "artifact": "detector.onnx",
  "sha256": "REPLACE_WITH_64_HEX_DIGITS_FROM_YOUR_EXPORT",
  "format": "onnx",
  "output_layout": "yolo11_raw_xywh_class_scores",
  "input_size": [640, 640],
  "class_names": ["pump", "valve", "nameplate"],
  "confidence_threshold": 0.4,
  "iou_threshold": 0.5
}
```

This is a template, not a valid manifest or selected class list. Use the exact
ordered class map from your export and its computed digest. The artifact must be
an ONNX file within the manifest directory. Only trusted operator-provisioned
artifacts are accepted; there is no public model-upload endpoint.

Supported input: one static float32 NCHW tensor `[1,3,H,W]`; RGB channels, [0,1]
normalization and centered letterboxing with fill 114. The resized dimensions are
rounded and coordinate remapping uses the actual horizontal/vertical resize scale.
Supported output: one tensor `[1,4+C,N]`, pixel-space center-x/center-y/width/height
plus C class scores in [0,1]. This is the raw detection layout without embedded NMS.
End-to-end/NMS exports, objectness columns, dynamic input shapes, segmentation,
pose and quantized integer inputs are rejected rather than guessed.

The adapter checks the SHA-256 before loading with ONNX Runtime's CPU provider.
It validates shapes/nonfinite scores, clips boxes to the original image, suppresses
same-class duplicates and returns at most 50 detections. Candidate preselection is
bounded to 3000 score-ranked boxes. Thresholds are heuristics pending your evaluation.
Category recognition does not establish a physical asset's identity.

Verification here covers manifests, letterboxing, decoding, classwise NMS and
crop/OCR coordinate mapping with controlled outputs. A trained ONNX artifact has
not been provided; actual equipment accuracy, export conformance and inference
latency must be validated against your reference examples before enabling it.
