"""Compute analysis separately from its transaction so workers can fence results."""
import json
import math
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image

from posify.audit import record_event
from posify.matching import extract_identifiers, match_identifiers
from posify.ocr import OCRLine
from posify.plate_reader import read_plate
from posify.recognition import ReadingAttempt, extract_fields, catalogue_candidates


class ComponentHTTPError(HTTPException):
    """Retain a bounded stage identifier without persisting exception details."""
    def __init__(self, component, cause):
        super().__init__(cause.status_code, detail=cause.detail)
        self.component = component


def run_component(component, operation, image_path):
    try:
        return operation(image_path)
    except HTTPException as exc:
        raise ComponentHTTPError(component, exc) from exc


def compute_analysis(app, database, root, site_id, capture_id, mode='ocr', analysis_id=None):
    with database.connect() as db:
        capture = db.execute('SELECT * FROM captures WHERE id=? AND site_id=?', (str(capture_id), site_id)).fetchone()
    if not capture:
        raise HTTPException(404, 'Capture not found in this factory')
    image_path = root / (capture['sha256'] + '.png')
    if not image_path.is_file():
        raise HTTPException(410, 'Capture image content is missing')
    detections, revision, warnings, attempts = [], None, [], []
    ocr = app.state.ocr
    if mode == 'detect_ocr':
        detections, revision = run_component('detector', app.state.detector.predict, image_path)
        regions = [d for d in detections if d.label.casefold() in {'nameplate', 'label'}] or detections
        if len(regions) > 8:
            warnings.append('ocr_limited_to_first_eight_regions')
        regions = regions[:8]
        if regions:
            lines = []
            remaining = 20
            deadline = time.monotonic() + 60
            with Image.open(image_path) as image, tempfile.TemporaryDirectory(prefix='posify-ocr-') as temp:
                for index, detection in enumerate(regions):
                    if time.monotonic() >= deadline:
                        warnings.append('remaining_regions_not_read');break
                    x1, y1, x2, y2 = detection.box
                    box = (math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2))
                    crop = Path(temp) / f'{index}.png'
                    image.crop(box).save(crop)
                    try:
                        selected, reads, flags = read_plate(ocr, crop, region_index=index,
                            max_attempts=max(1,min(8,remaining-(len(regions)-index-1))),
                            seconds=min(18,max(.1,deadline-time.monotonic())))
                    except HTTPException as exc:
                        raise ComponentHTTPError('ocr',exc) from exc
                    remaining -= len(reads)
                    def offset(rect):
                        return None if rect is None else (rect[0]+box[0],rect[1]+box[1],rect[2]+box[0],rect[3]+box[1])
                    def translated(line):
                        return line.model_copy(update={'box':offset(line.box),
                            'words':[word.model_copy(update={'box':offset(word.box)}) for word in line.words]})
                    lines.extend(translated(line) for line in selected)
                    for reading in reads:
                        reading.lines=[translated(line) for line in reading.lines]
                        reading.source_quad=[(x+box[0],y+box[1]) for x,y in reading.source_quad]
                    attempts.extend(reads);warnings.extend(flags)
        else:
            warnings.append('no_detections_full_image_ocr')
            lines = run_component('ocr', ocr.recognize, image_path)
    elif mode == 'ocr':
        lines = run_component('ocr', ocr.recognize, image_path)
    else:
        raise HTTPException(422, 'Unsupported analysis mode')
    if len(lines) > 2000:
        raise HTTPException(502, 'OCR returned too many lines')
    if not attempts:
        attempts=[ReadingAttempt(id='full-image-baseline',region_index=0,method='full_image_baseline',
            rotation=0,psm=None,selected=True,lines=lines)]
    identifiers = extract_identifiers(lines)
    with database.connect() as db:
        match = match_identifiers(db, site_id, identifiers)
        manufacturers=[row['manufacturer'] for row in db.execute(
            "SELECT DISTINCT manufacturer FROM catalog_models WHERE status='published' ORDER BY manufacturer LIMIT 501")]
        manufacturers += [row['manufacturer'] for row in db.execute(
            'SELECT DISTINCT manufacturer FROM assets WHERE site_id=? ORDER BY manufacturer LIMIT 501',(site_id,))]
        if len(manufacturers)>1000: warnings.append('manufacturer_vocabulary_truncated')
        fields=extract_fields(attempts,sorted(set(manufacturers[:1000])))
        equipment,status,flags=catalogue_candidates(db,fields)
        warnings.extend(flags)
        if any(field.status=='conflicting' and field.field in {'serial','asset_tag'} for field in fields):
            match={'status':'ambiguous_identifiers','candidates':[]}
            warnings.append('conflicting_physical_identifiers_across_readings')
    return dict(id=str(analysis_id or uuid4()), capture_id=str(capture_id),
                created_at=datetime.now(timezone.utc).isoformat(), engine=ocr.engine,
                lines=[line.model_dump() for line in lines], identifiers=identifiers,
                detections=[d.model_dump() for d in detections], detector_revision=revision,
                inference_mode=mode, pipeline_warnings=sorted(set(warnings)), requires_confirmation=True,
                recognition_version='plate-evidence-v1',equipment_fields=[field.model_dump() for field in fields],
                equipment_candidates=[item.model_dump(mode='json') for item in equipment],equipment_status=status,
                reading_attempts=[item.model_dump() for item in attempts],**match)


def save_analysis(db, site_id, result):
    db.execute('INSERT INTO capture_analyses VALUES(?,?,?,?)',
               (result['id'], result['capture_id'], result['created_at'], json.dumps(result)))
    record_event(db, site_id, 'capture.analyzed', result['id'],
                 {'capture_id': result['capture_id'], 'engine': result['engine'],
                  'status': result['status'], 'inference_mode': result['inference_mode']})
