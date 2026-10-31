"""Interchangeable local OCR engines. Never downloads model weights implicitly."""
import csv
import io
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from threading import Lock

from fastapi import HTTPException
from pydantic import BaseModel, Field


class OCRWord(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    box: tuple[int, int, int, int] | None = None


class OCRLine(BaseModel):
    text: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    box: tuple[int, int, int, int] | None = None
    words: list[OCRWord] = Field(default_factory=list)


def parse_tsv(tsv):
    groups = {}
    for word in csv.DictReader(io.StringIO(tsv), delimiter='\t', quoting=csv.QUOTE_NONE):
        if not word.get('text', '').strip() or float(word['conf']) < 0:
            continue
        key = tuple(word[k] for k in ['page_num', 'block_num', 'par_num', 'line_num'])
        groups.setdefault(key, []).append(word)
    lines = []
    for words in groups.values():
        left = min(int(w['left']) for w in words)
        top = min(int(w['top']) for w in words)
        right = max(int(w['left']) + int(w['width']) for w in words)
        bottom = max(int(w['top']) + int(w['height']) for w in words)
        lines.append(OCRLine(text=' '.join(w['text'] for w in words),
                             confidence=min(float(w['conf']) for w in words) / 100,
                             box=(left, top, right, bottom), words=[OCRWord(
                                 text=w['text'], confidence=float(w['conf']) / 100,
                                 box=(int(w['left']), int(w['top']), int(w['left'])+int(w['width']),
                                      int(w['top'])+int(w['height']))) for w in words]))
    return lines


class LocalOCR:
    def __init__(self):
        self.engine = os.getenv('POSIFY_OCR_ENGINE', 'disabled')
        if self.engine not in {'disabled', 'tesseract', 'paddle', 'rapidocr'}:
            raise RuntimeError('POSIFY_OCR_ENGINE must be disabled, tesseract, paddle or rapidocr')
        self.rapid_dir = os.getenv('POSIFY_RAPIDOCR_MODEL_DIR','')
        self.det_dir = os.getenv('POSIFY_PADDLE_DET_DIR', '')
        self.rec_dir = os.getenv('POSIFY_PADDLE_REC_DIR', '')
        self._pipeline = None
        self._lock = Lock()

    def readiness(self):
        if self.engine == 'tesseract':
            configured = shutil.which('tesseract') is not None
        elif self.engine == 'paddle':
            configured = bool(self.det_dir and self.rec_dir and
                              Path(self.det_dir).is_dir() and Path(self.rec_dir).is_dir() and
                              importlib.util.find_spec('paddleocr') and importlib.util.find_spec('paddle'))
        elif self.engine == 'rapidocr':
            from posify.neural_ocr import MODELS
            configured=bool(importlib.util.find_spec('rapidocr') and self.rapid_dir and
                            all((Path(self.rapid_dir)/name).is_file() for name in MODELS))
        else:
            configured = False
        return {'engine': self.engine, 'configured': bool(configured),
                'loaded': self._pipeline is not None,
                'note': 'Configuration checks do not prove inference readiness. No weights are downloaded by this service.'}

    def recognize(self, image_path: Path):
        if not self.readiness()['configured']:
            raise HTTPException(503, 'OCR is disabled or local engine/model files are missing')
        if self.engine == 'tesseract':
            return self.recognize_variant(image_path, psm=6)
        if self.engine == 'rapidocr':
            with self._lock:
                try:
                    if self._pipeline is None:
                        from posify.neural_ocr import create_reader
                        self._pipeline=create_reader(self.rapid_dir)
                    output=self._pipeline(str(image_path))
                    lines=[]
                    if output.txts is None: return lines
                    for text,score,polygon in zip(output.txts,output.scores,output.boxes,strict=True):
                        if text.strip():
                            points=list(polygon)
                            lines.append(OCRLine(text=text,confidence=float(score),box=(
                                int(min(p[0] for p in points)),int(min(p[1] for p in points)),
                                int(max(p[0] for p in points)),int(max(p[1] for p in points)))))
                    return lines
                except Exception:
                    raise HTTPException(503,'Local PP-OCRv6 failed; verify its provisioned artifacts and runtime')
        with self._lock:
            try:
                if self._pipeline is None:
                    from paddleocr import PaddleOCR
                    self._pipeline = PaddleOCR(
                        text_detection_model_name='PP-OCRv5_mobile_det',
                        text_recognition_model_name='en_PP-OCRv5_mobile_rec',
                        text_detection_model_dir=self.det_dir,
                        text_recognition_model_dir=self.rec_dir,
                        use_doc_orientation_classify=False, use_doc_unwarping=False,
                        use_textline_orientation=False, device='cpu',
                    )
                lines = []
                for result in self._pipeline.predict(str(image_path)):
                    for text, score, box in zip(result['rec_texts'], result['rec_scores'], result['rec_boxes'], strict=True):
                        if text.strip():
                            lines.append(OCRLine(text=text, confidence=float(score), box=tuple(int(v) for v in box)))
                return lines
            except Exception:
                # Do not leak runtime paths, raw images or third-party stack traces to clients.
                raise HTTPException(503, 'Local PaddleOCR failed; verify the installed runtime and model files')

    def recognize_variant(self, image_path: Path, psm=6, timeout=20, code_mode=False):
        if self.engine != 'tesseract':
            return self.recognize(image_path)
        if not self.readiness()['configured']:
            raise HTTPException(503, 'OCR is disabled or local engine/model files are missing')
        if psm not in {6, 7, 11, 13} or not 0 < timeout <= 20:
            raise ValueError('Unsupported OCR variant')
        with self._lock:
            try:
                options=['-c','load_system_dawg=0','-c','load_freq_dawg=0'] if code_mode else []
                result = subprocess.run(['tesseract', str(image_path), 'stdout', '-l', 'eng',
                                         '--psm', str(psm), *options, 'tsv'], capture_output=True, text=True,
                                        timeout=timeout, check=True)
                return parse_tsv(result.stdout)
            except (OSError, subprocess.SubprocessError, ValueError, KeyError):
                raise HTTPException(503, 'Local Tesseract OCR failed')
