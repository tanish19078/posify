"""Inference-only YOLO11 ONNX contract. No training or implicit downloads."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from threading import Lock

import numpy as np
from fastapi import HTTPException
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field, model_validator


class DetectorManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=100)
    artifact: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    format: str = 'onnx'
    output_layout: str = 'yolo11_raw_xywh_class_scores'
    input_size: tuple[int, int] = (640, 640)  # height, width
    class_names: list[str] = Field(min_length=1, max_length=2000)
    confidence_threshold: float = Field(default=.4, ge=0, le=1, allow_inf_nan=False)
    iou_threshold: float = Field(default=.5, gt=0, le=1, allow_inf_nan=False)

    @model_validator(mode='after')
    def contract(self):
        if self.format != 'onnx' or self.output_layout != 'yolo11_raw_xywh_class_scores':
            raise ValueError('Only raw YOLO11 ONNX detection output is supported')
        if any(v < 32 or v > 2048 or v % 32 for v in self.input_size):
            raise ValueError('Input dimensions must be multiples of 32 between 32 and 2048')
        if len(set(self.class_names)) != len(self.class_names) or any(not n.strip() or len(n) > 100 for n in self.class_names):
            raise ValueError('Class names must be non-empty and unique')
        return self


class Detection(BaseModel):
    class_id: int
    label: str
    confidence: float
    box: tuple[float, float, float, float]  # original-image xyxy


def preprocess(image, size):
    target_h, target_w = size
    width, height = image.size
    ratio = min(target_w / width, target_h / height)
    new_w, new_h = round(width * ratio), round(height * ratio)
    left, top = (target_w - new_w) // 2, (target_h - new_h) // 2
    canvas = Image.new('RGB', (target_w, target_h), (114, 114, 114))
    canvas.paste(image.convert('RGB').resize((new_w, new_h), Image.Resampling.BILINEAR), (left, top))
    tensor = np.asarray(canvas, dtype=np.float32).transpose(2, 0, 1)[None] / 255.0
    return np.ascontiguousarray(tensor), (new_w / width, new_h / height, left, top)


def iou(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union else 0


def postprocess(output, manifest, original_size, transform):
    output = np.asarray(output)
    if output.ndim != 3 or output.shape[:2] != (1, 4 + len(manifest.class_names)) or output.shape[2] > 100000:
        raise HTTPException(502, 'Detector output does not match the declared raw YOLO11 contract')
    rows = output[0].T
    if not np.isfinite(rows).all() or np.any(rows[:, 4:] < 0) or np.any(rows[:, 4:] > 1):
        raise HTTPException(502, 'Detector returned invalid coordinates or class scores')
    sx, sy, pad_x, pad_y = transform
    width, height = original_size
    candidates = []
    for row in rows:
        cls = int(np.argmax(row[4:]))
        score = float(row[4 + cls])
        if score < manifest.confidence_threshold or row[2] <= 0 or row[3] <= 0:
            continue
        x, y, w, h = (float(v) for v in row[:4])
        box = (max(0., min(float(width), (x-w/2-pad_x)/sx)),
               max(0., min(float(height), (y-h/2-pad_y)/sy)),
               max(0., min(float(width), (x+w/2-pad_x)/sx)),
               max(0., min(float(height), (y+h/2-pad_y)/sy)))
        if box[2] > box[0] and box[3] > box[1]:
            candidates.append(Detection(class_id=cls, label=manifest.class_names[cls], confidence=score, box=box))
    candidates.sort(key=lambda d: (-d.confidence, d.class_id, d.box))
    selected = []
    for candidate in candidates[:3000]:
        if not any(d.class_id == candidate.class_id and iou(d.box, candidate.box) > manifest.iou_threshold for d in selected):
            selected.append(candidate)
            if len(selected) == 50:
                break
    return selected


class LocalDetector:
    def __init__(self):
        self.manifest_path = os.getenv('POSIFY_DETECTOR_MANIFEST', '')
        self.manifest = None
        self.session = None
        self._lock = Lock()

    def readiness(self):
        return {'configured': bool(self.manifest_path),
                'manifest_present': bool(self.manifest_path and Path(self.manifest_path).is_file()),
                'runtime_present': importlib.util.find_spec('onnxruntime') is not None,
                'loaded': self.session is not None, 'inference_implemented': True,
                'training': 'external_colab', 'supported_layout': 'yolo11_raw_xywh_class_scores'}

    def predict(self, image_path):
        if not self.readiness()['manifest_present'] or not self.readiness()['runtime_present']:
            raise HTTPException(503, 'Detector manifest, artifact or ONNX Runtime is not configured')
        with self._lock:
            try:
                if self.session is None:
                    path = Path(self.manifest_path).resolve()
                    self.manifest = DetectorManifest.model_validate_json(path.read_text())
                    artifact = (path.parent / self.manifest.artifact).resolve()
                    if not artifact.is_relative_to(path.parent) or artifact.suffix.lower() != '.onnx':
                        raise ValueError('Artifact must be an ONNX file within the manifest directory')
                    digest = hashlib.sha256()
                    with artifact.open('rb') as stream:
                        while chunk := stream.read(1024 * 1024):
                            digest.update(chunk)
                    if digest.hexdigest() != self.manifest.sha256.lower():
                        raise ValueError('Model digest mismatch')
                    import onnxruntime as ort
                    session = ort.InferenceSession(str(artifact), providers=['CPUExecutionProvider'])
                    inputs = session.get_inputs()
                    if len(inputs) != 1 or inputs[0].type != 'tensor(float)' or inputs[0].shape != [1, 3, *self.manifest.input_size]:
                        raise ValueError('Model must expose one static float32 NCHW input')
                    if len(session.get_outputs()) != 1:
                        raise ValueError('Model must expose one raw detection output')
                    self.session = session
                with Image.open(image_path) as image:
                    tensor, transform = preprocess(image, self.manifest.input_size)
                    output = self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0]
                    detections = postprocess(output, self.manifest, image.size, transform)
                return detections, self.manifest.model_id + '@' + self.manifest.revision
            except HTTPException:
                raise
            except Exception:
                self.session = None
                raise HTTPException(503, 'Detector failed; verify its local manifest, digest and tensor contract')
