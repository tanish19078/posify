"""Compute analysis separately from its transaction so workers can fence results."""
import json
import math
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image

from posify.matching import extract_identifiers, match_identifiers
from posify.ocr import OCRLine


def compute_analysis(app, database, root, site_id, capture_id, mode='ocr', analysis_id=None):
    with database.connect() as db:
        capture = db.execute('SELECT * FROM captures WHERE id=? AND site_id=?', (str(capture_id), site_id)).fetchone()
    if not capture:
        raise HTTPException(404, 'Capture not found in this factory')
    image_path = root / (capture['sha256'] + '.png')
    if not image_path.is_file():
        raise HTTPException(410, 'Capture image content is missing')
    detections, revision, warnings = [], None, []
    ocr = app.state.ocr
    if mode == 'detect_ocr':
        detections, revision = app.state.detector.predict(image_path)
        regions = [d for d in detections if d.label.casefold() in {'nameplate', 'label'}] or detections
        if len(regions) > 8:
            warnings.append('ocr_limited_to_first_eight_regions')
        regions = regions[:8]
        if regions:
            lines = []
            with Image.open(image_path) as image, tempfile.TemporaryDirectory(prefix='posify-ocr-') as temp:
                for index, detection in enumerate(regions):
                    x1, y1, x2, y2 = detection.box
                    box = (math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2))
                    crop = Path(temp) / f'{index}.png'
                    image.crop(box).save(crop)
                    for line in ocr.recognize(crop):
                        mapped = None if line.box is None else (line.box[0]+box[0], line.box[1]+box[1],
                                                               line.box[2]+box[0], line.box[3]+box[1])
                        lines.append(OCRLine(text=line.text, confidence=line.confidence, box=mapped))
        else:
            warnings.append('no_detections_full_image_ocr')
            lines = ocr.recognize(image_path)
    elif mode == 'ocr':
        lines = ocr.recognize(image_path)
    else:
        raise HTTPException(422, 'Unsupported analysis mode')
    if len(lines) > 2000:
        raise HTTPException(502, 'OCR returned too many lines')
    identifiers = extract_identifiers(lines)
    with database.connect() as db:
        match = match_identifiers(db, site_id, identifiers)
    return dict(id=str(analysis_id or uuid4()), capture_id=str(capture_id),
                created_at=datetime.now(timezone.utc).isoformat(), engine=ocr.engine,
                lines=[line.model_dump() for line in lines], identifiers=identifiers,
                detections=[d.model_dump() for d in detections], detector_revision=revision,
                inference_mode=mode, pipeline_warnings=warnings, requires_confirmation=True, **match)


def save_analysis(db, site_id, result):
    db.execute('INSERT INTO capture_analyses VALUES(?,?,?,?)',
               (result['id'], result['capture_id'], result['created_at'], json.dumps(result)))
    db.execute('INSERT INTO audit(site_id,kind,entity_id,created_at,payload) VALUES(?,?,?,?,?)',
               (site_id, 'capture.analyzed', result['id'], result['created_at'],
                json.dumps({'capture_id': result['capture_id'], 'engine': result['engine'],
                            'status': result['status'], 'inference_mode': result['inference_mode']})))
