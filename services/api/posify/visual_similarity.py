"""Inference-only ONNX visual appearance encoder for equipment similarity retrieval.

Visual appearance similarity is a reviewable candidate hint, never proof of
manufacturer, model, or physical asset identity.
"""
import hashlib
import importlib.util
import math
import os
import time
from pathlib import Path
from threading import Lock
from uuid import UUID

import numpy as np
from fastapi import HTTPException
from PIL import Image, ImageOps
from pydantic import BaseModel, ConfigDict, Field, model_validator

from posify.detector import runtime_version, supported_runtime


class VisionEmbedderManifest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    model_id: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=100)
    artifact: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r'^[a-fA-F0-9]{64}$')
    format: str = 'onnx'
    input_size: tuple[int, int] = (224, 224)  # height, width
    embedding_dim: int = Field(ge=32, le=4096)
    mean: tuple[float, float, float] = (0.485, 0.456, 0.406)
    std: tuple[float, float, float] = (0.229, 0.224, 0.225)
    min_similarity: float = Field(default=0.72, ge=-1.0, le=1.0, allow_inf_nan=False)

    @model_validator(mode='after')
    def validate_contract(self):
        if self.format != 'onnx':
            raise ValueError('Only ONNX visual embedder artifacts are supported')
        if any(v < 32 or v > 1024 for v in self.input_size):
            raise ValueError('Input dimensions must be between 32 and 1024')
        if any(not math.isfinite(s) or s <= 0 for s in self.std) or any(not math.isfinite(m) for m in self.mean):
            raise ValueError('Normalization mean/std must be finite and std > 0')
        return self


class VisualCandidate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    catalog_model_id: UUID
    manufacturer: str
    model: str
    variant: str
    category: str
    similarity: float = Field(ge=-1.0, le=1.0, allow_inf_nan=False)
    requires_review: bool = True


def preprocess_vision(image, size=(224, 224), mean=(0.485, 0.456, 0.406), std=(0.229, 0.224, 0.225)):
    """Resize/crop to static FP32 NCHW tensor with ImageNet-style channel normalization."""
    target_h, target_w = size
    fitted = ImageOps.fit(image.convert('RGB'), (target_w, target_h), method=Image.Resampling.BILINEAR)
    arr = np.asarray(fitted, dtype=np.float32) / 255.0
    m = np.asarray(mean, dtype=np.float32).reshape(1, 1, 3)
    s = np.asarray(std, dtype=np.float32).reshape(1, 1, 3)
    normed = (arr - m) / s
    return np.ascontiguousarray(normed.transpose(2, 0, 1)[None], dtype=np.float32)


def normalize_embedding(vector):
    arr = np.asarray(vector, dtype=np.float32).reshape(-1)
    if arr.size == 0 or not np.isfinite(arr).all():
        raise HTTPException(502, 'Visual encoder returned invalid embedding values')
    norm = float(np.linalg.norm(arr))
    if norm <= 1e-12 or not math.isfinite(norm):
        raise HTTPException(502, 'Visual encoder returned a zero-norm embedding')
    return (arr / norm).astype(np.float32)


def cosine_similarity(a, b):
    va = normalize_embedding(a)
    vb = normalize_embedding(b)
    if va.shape != vb.shape:
        raise ValueError('Embedding dimensions must match')
    score = float(np.dot(va, vb))
    return max(-1.0, min(1.0, round(score, 6)))


def rank_visual_candidates(query_embedding, references, min_similarity=0.72, top_k=5):
    """Rank published catalogue reference embeddings by cosine similarity."""
    query = normalize_embedding(query_embedding)
    scored = []
    for ref in references:
        ref_vec = ref.get('embedding')
        if ref_vec is None or len(ref_vec) != query.shape[0]:
            continue
        score = cosine_similarity(query, ref_vec)
        if score >= min_similarity:
            scored.append(VisualCandidate(
                catalog_model_id=ref['catalog_model_id'],
                manufacturer=ref['manufacturer'],
                model=ref['model'],
                variant=ref.get('variant', 'base'),
                category=ref.get('category', ''),
                similarity=score,
                requires_review=True,
            ))
    scored.sort(key=lambda c: (-c.similarity, str(c.catalog_model_id)))
    return scored[:top_k]


class LocalVisionEmbedder:
    def __init__(self):
        self.manifest_path = os.getenv('POSIFY_VISION_EMBEDDER_MANIFEST', '')
        self.manifest = None
        self.session = None
        self._lock = Lock()
        self.threads = int(os.getenv('POSIFY_DETECTOR_THREADS', '1'))
        if not 1 <= self.threads <= 8:
            raise RuntimeError('POSIFY_DETECTOR_THREADS must be between 1 and 8')
        self.successful_inferences = 0
        self.last_inference_ms = None

    def readiness(self):
        installed = runtime_version()
        return {
            'configured': bool(self.manifest_path),
            'manifest_present': bool(self.manifest_path and Path(self.manifest_path).is_file()),
            'runtime_present': importlib.util.find_spec('onnxruntime') is not None,
            'runtime_version': installed,
            'runtime_compatible': supported_runtime(installed),
            'loaded': self.session is not None,
            'successful_inferences': self.successful_inferences,
            'last_inference_ms': self.last_inference_ms,
            'model_id': self.manifest.model_id if self.manifest else None,
            'revision': self.manifest.revision if self.manifest else None,
            'embedding_dim': self.manifest.embedding_dim if self.manifest else None,
            'note': 'Visual appearance similarity is a reviewable hint, never proof of equipment identity.',
        }

    def load(self):
        with self._lock:
            self._load_locked()
        return self.manifest, self.session

    def embed(self, image_path):
        state = self.readiness()
        if not state['manifest_present'] or not state['runtime_present']:
            raise HTTPException(503, 'Visual embedder manifest, artifact or ONNX Runtime is not configured')
        with self._lock:
            try:
                self._load_locked()
                with Image.open(image_path) as image:
                    tensor = preprocess_vision(image, self.manifest.input_size, self.manifest.mean, self.manifest.std)
                started = time.perf_counter()
                output = self.session.run(None, {self.session.get_inputs()[0].name: tensor})[0]
                elapsed = (time.perf_counter() - started) * 1000
                arr = np.asarray(output)
                if arr.ndim != 2 or arr.shape != (1, self.manifest.embedding_dim):
                    raise HTTPException(502, 'Visual embedder output shape does not match manifest contract')
                vec = normalize_embedding(arr[0])
                self.successful_inferences += 1
                self.last_inference_ms = round(elapsed, 3)
                return vec.tolist(), f'{self.manifest.model_id}@{self.manifest.revision}'
            except HTTPException:
                raise
            except Exception:
                self.session = None
                raise HTTPException(503, 'Visual embedder failed; verify its local manifest, digest and tensor contract')

    def _load_locked(self):
        if self.session is None:
            if not supported_runtime(runtime_version()):
                raise ValueError('Install the supported CPU runtime from requirements-inference.lock')
            path = Path(self.manifest_path).resolve()
            self.manifest = VisionEmbedderManifest.model_validate_json(path.read_text())
            artifact = (path.parent / self.manifest.artifact).resolve()
            if not artifact.is_relative_to(path.parent) or artifact.suffix.lower() != '.onnx':
                raise ValueError('Artifact must be an ONNX file within the manifest directory')
            digest = hashlib.sha256()
            with artifact.open('rb') as stream:
                while chunk := stream.read(1024 * 1024):
                    digest.update(chunk)
            if digest.hexdigest() != self.manifest.sha256.lower():
                raise ValueError('Visual embedder digest mismatch')
            import onnxruntime as ort
            options = ort.SessionOptions()
            options.intra_op_num_threads = self.threads
            options.inter_op_num_threads = 1
            session = ort.InferenceSession(str(artifact), sess_options=options, providers=['CPUExecutionProvider'])
            inputs = session.get_inputs()
            if len(inputs) != 1 or inputs[0].type != 'tensor(float)' or inputs[0].shape != [1, 3, *self.manifest.input_size]:
                raise ValueError('Visual embedder must expose one static float32 NCHW input')
            outputs = session.get_outputs()
            if len(outputs) != 1 or outputs[0].type != 'tensor(float)' or outputs[0].shape != [1, self.manifest.embedding_dim]:
                raise ValueError('Visual embedder must expose one static [1, embedding_dim] float32 output')
            self.session = session
