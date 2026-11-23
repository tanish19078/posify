"""Image-grounded field proposals and conservative catalogue verification.

This is not a machine appearance classifier. OCR confidence is never reported as
an identification probability; even supported model candidates require review.
"""
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from posify.ocr import OCRLine


class EvidenceModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ReadingAttempt(EvidenceModel):
    id: str
    region_index: int
    method: str
    rotation: int
    psm: int | None
    selected: bool = False
    quality_score: float = 0
    source_quad: list[tuple[float, float]] = Field(default_factory=list)
    lines: list[OCRLine] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


FieldName = Literal['manufacturer', 'model', 'serial', 'asset_tag', 'voltage', 'power', 'speed', 'frequency', 'frame']


class EquipmentField(EvidenceModel):
    id: str
    field: FieldName
    value: str
    unit: str | None = None
    raw_text: str
    attempt_id: str
    region_index: int
    line_index: int
    box: tuple[int, int, int, int] | None
    ocr_confidence: float
    basis: Literal['explicit_label', 'catalogue_vocabulary', 'header_candidate', 'code_candidate', 'unit_pattern']
    status: Literal['observed', 'low_confidence', 'conflicting']
    corroborating_attempts: list[str] = Field(default_factory=list)


PLATE_LABELS = {'nameplate', 'label', 'plate', 'tag', 'rating_plate', 'data_plate'}


class EquipmentCandidate(EvidenceModel):
    catalog_model_id: UUID
    manufacturer: str
    model: str
    variant: str
    category: str
    source_ref: str
    status: Literal['evidence_supported', 'partial_evidence', 'conflicting_evidence']
    matched_fields: list[str]
    missing_fields: list[str]
    conflicting_fields: list[str]
    evidence_ids: list[str]
    retrieval_basis: Literal['exact_model', 'approximate_model', 'manufacturer_only', 'visual_category']
    requires_review: bool = True


def normalized(value):
    """Case/space normalization only. Do not silently repair S/5, O/0 or I/1."""
    value = unicodedata.normalize('NFKC', value).casefold()
    return re.sub(r'\s+', '', value).replace('–', '-').replace('—', '-')


LABELS = {
    'manufacturer': r'(?:manufacturer|mfr|maker)',
    'model': r'(?:model|type|typ)',
    'serial': r'(?:serial\s+(?:no\.?|number)|serial|s/n|fabr\.?-?\s*nr\.?)',
    'asset_tag': r'(?:asset\s*tag|asset|tag)',
    'frame': r'(?:frame)',
}
STOP_IDENTIFIER_VALUES = {'NO', 'NO.', 'NUMBER', 'NR', 'NR.', 'CODE', 'NONE', 'N/A'}
CODE = re.compile(r'(?<![\w/-])(?:[0-9]\s*)?[A-Z]{1,5}\s*[A-Z0-9]{2,}(?:\s*[-/]\s*[A-Z0-9]{1,12}){1,3}(?![\w/-])', re.I)
CORP_ENTITY = re.compile(
    r'^([A-Z][A-Z0-9 &.-]{2,60}?)\s+(?:CO\.?\s*,?\s*LTD\.?|GMBH(?:\s*&\s*CO\.?\s*KG)?|INC\.?|CORP\.?|CORPORATION|LIMITED)\.?$',
    re.I,
)
GERMAN_NR_SERIAL = re.compile(r'^(?:Fabr\.?-?\s*)?Nr\.?\s*([A-Z0-9]{1,6}(?:\s+\d{2,6}){2,5})$', re.I)
UNITS = {
    'voltage': r'V|VOLTS?', 'power': r'kW|HP',
    'speed': r'RPM|r/min|1/min', 'frequency': r'Hz',
}
NUMBER = r'\d{1,6}(?:[.,]\d{1,4})?(?:\s*[/–-]\s*\d{1,6}(?:[.,]\d{1,4})?)?'


def _confidence(line, value):
    # Use only tokens supporting this value, never a high score from another line.
    target = normalized(value)
    supporting = [word for word in line.words if normalized(word.text.strip(',:;|'))
                  and normalized(word.text.strip(',:;|')) in target]
    joined = ''.join(normalized(word.text.strip(',:;|')) for word in supporting)
    return min(word.confidence for word in supporting) if supporting and target in joined else line.confidence


def _value_box(line, value):
    target=normalized(value)
    words=[word for word in line.words if word.box and normalized(word.text.strip(',:;|'))
           and normalized(word.text.strip(',:;|')) in target]
    joined=''.join(normalized(word.text.strip(',:;|')) for word in words)
    if not words or target not in joined: return line.box
    return (min(w.box[0] for w in words), min(w.box[1] for w in words),
            max(w.box[2] for w in words), max(w.box[3] for w in words))


def extract_fields(attempts, manufacturers):
    proposals = []
    vocabulary = [(name, re.compile(r'(?<!\w)' + r'\s*'.join(re.escape(part) for part in name.split()) + r'(?!\w)', re.I)) for name in manufacturers]
    header_stop = {'MOTOR','MODEL','TYPE','SERIAL','THREE','PHASE','INDUCTION','ELECTRIC','CURRENT',
                   'VOLTAGE','FREQUENCY','INSULATION','POWER','SPEED','FRAME','RATED','MADE','GERMANY','CHINA'}
    for attempt in attempts:
        for index, line in enumerate(attempt.lines):
            text = unicodedata.normalize('NFKC', line.text)
            found = []
            for field, label in LABELS.items():
                # Colon without a following space is common on real nameplates.
                pattern = rf'(?<!\w){label}(?!\s*(?:no\.?|number|nr\.?)\b)\s*(?:[:#=]\s*|\s+)([A-Z0-9][A-Z0-9 ._/-]{{0,79}})'
                match = re.search(pattern, text, re.I)
                if match:
                    value = re.split(r'\s+(?:serial|model|type|tag|volts?|rpm|hz)\b|[|;]', match[1], flags=re.I)[0].strip(' .')
                    # Identifier proposals never absorb a whole technical sentence.
                    if field != 'manufacturer':
                        parts=value.split()
                        if field=='model' and len(parts)>1 and re.fullmatch(r'\d',parts[0]) and re.match(r'[A-Z]+\d',parts[1],re.I):
                            value=' '.join(parts[:2])
                        elif field=='serial' and len(parts)>1 and all(re.fullmatch(r'\d+',part) for part in parts[1:]):
                            value=' '.join(parts[:6])
                        else:
                            value=parts[0] if parts else ''
                    if value and value.upper() not in STOP_IDENTIFIER_VALUES:
                        found.append((field, value, None, 'explicit_label'))
            for manufacturer, expression in vocabulary:
                if expression.search(text):
                    found.append(('manufacturer', manufacturer, None, 'catalogue_vocabulary'))
            if not any(f[0] == 'manufacturer' for f in found):
                corp_match = CORP_ENTITY.match(text.strip())
                if corp_match:
                    found.append(('manufacturer', corp_match[1].strip(' ,.-'), None, 'header_candidate'))
            if not any(f[0] == 'serial' for f in found):
                nr_match = GERMAN_NR_SERIAL.match(text.strip())
                if nr_match:
                    found.append(('serial', nr_match[1].strip(), None, 'explicit_label'))
            if index < 2:
                possible = [word for word in line.words if re.fullmatch('[A-Z]{4,24}',word.text)
                            and word.text not in header_stop and word.confidence >= .65]
                if len(possible)==1:
                    found.append(('manufacturer', possible[0].text, None, 'header_candidate'))
                elif not line.words and re.fullmatch('[A-Z]{4,24}',text.strip()) and text.strip() not in header_stop:
                    found.append(('manufacturer',text.strip(),None,'header_candidate'))
            if index < 4 and not re.search(r'\b(?:serial|s/n|asset|frame)\b', text, re.I):
                scan_text = re.sub(r'\b(Mot)\.?(?=\d)', r'\1 ', text, flags=re.I)
                for match in CODE.finditer(scan_text):
                    value = re.sub(r'\s+', '', match[0])
                    has_digits = sum(c.isdigit() for c in value) >= 3 or bool(
                        re.fullmatch(r'[A-Z]{3,8}-\d{2,6}(?:-[A-Z0-9]+)*', value, re.I)
                    )
                    if has_digits and sum(c.isalpha() for c in value) >= 2 and not re.match(r'^(?:IEC|ISO|DIN|EN|NEMA|IEEE|ANSI|IP|IM|IC)\d', value, re.I):
                        found.append(('model', value, None, 'code_candidate'))
            for field, unit_pattern in UNITS.items():
                patterns = [rf'(?<![\w.])({NUMBER})\s*({unit_pattern})(?!\w)',
                            rf'(?<!\w)({unit_pattern})\s*[:=]?\s*({NUMBER})(?!\w)']
                for position, pattern in enumerate(patterns):
                    for match in re.finditer(pattern, text, re.I):
                        value, unit = (match[1], match[2]) if position == 0 else (match[2], match[1])
                        found.append((field, value.replace(',', '.'), unit, 'unit_pattern'))
            for field, value, unit, basis in found:
                confidence = _confidence(line, value)
                proposals.append(EquipmentField(id=f'field-{len(proposals)+1}', field=field, value=value,
                    unit=unit, raw_text=line.text, attempt_id=attempt.id, region_index=attempt.region_index,
                    line_index=index, box=_value_box(line,value), ocr_confidence=confidence, basis=basis,
                    status='observed' if confidence >= .75 else 'low_confidence'))
        # Spatially aligned two-cell tabular pairs (unique vertical unit->number or horizontal label->value).
        for u_idx, u_line in enumerate(attempt.lines):
            if not u_line.box:
                continue
            u_text = unicodedata.normalize('NFKC', u_line.text).strip()
            for field, unit_pattern in UNITS.items():
                if not re.fullmatch(unit_pattern, u_text, re.I):
                    continue
                ux1, uy1, ux2, uy2 = u_line.box
                u_h = max(1, uy2 - uy1)
                uc_y = (uy1 + uy2) / 2
                matches = []
                for v_idx, v_line in enumerate(attempt.lines):
                    if v_idx == u_idx or not v_line.box:
                        continue
                    v_text = unicodedata.normalize('NFKC', v_line.text).strip()
                    if not re.fullmatch(NUMBER, v_text):
                        continue
                    vx1, vy1, vx2, vy2 = v_line.box
                    inter_x = max(0, min(ux2, vx2) - max(ux1, vx1))
                    min_w = max(1, min(ux2 - ux1, vx2 - vx1))
                    vc_y = (vy1 + vy2) / 2
                    if inter_x / min_w >= 0.65 and 0 < (vc_y - uc_y) <= 2.5 * u_h and vy1 >= uy1:
                        matches.append((v_idx, v_line, v_text))
                if len(matches) == 1:
                    v_idx, v_line, v_text = matches[0]
                    vx1, vy1, vx2, vy2 = v_line.box
                    conf = min(u_line.confidence, v_line.confidence)
                    proposals.append(EquipmentField(
                        id=f'field-{len(proposals)+1}', field=field, value=v_text.replace(',', '.'),
                        unit=u_text, raw_text=f'{v_line.text} {u_line.text}', attempt_id=attempt.id,
                        region_index=attempt.region_index, line_index=v_idx,
                        box=(min(ux1, vx1), min(uy1, vy1), max(ux2, vx2), max(uy2, vy2)),
                        ocr_confidence=conf, basis='unit_pattern',
                        status='observed' if conf >= .75 else 'low_confidence',
                    ))
        for l_idx, l_line in enumerate(attempt.lines):
            if not l_line.box:
                continue
            l_text = unicodedata.normalize('NFKC', l_line.text).strip()
            for field, label in LABELS.items():
                if not re.search(rf'(?<!\w){label}\s*[:#=-]?\s*$', l_text, re.I):
                    continue
                lx1, ly1, lx2, ly2 = l_line.box
                l_h = max(1, ly2 - ly1)
                matches = []
                for v_idx, v_line in enumerate(attempt.lines):
                    if v_idx == l_idx or not v_line.box:
                        continue
                    v_text = unicodedata.normalize('NFKC', v_line.text).strip()
                    if not re.fullmatch(r'[A-Z0-9][A-Z0-9._/-]{1,39}', v_text, re.I) or v_text.upper() in STOP_IDENTIFIER_VALUES:
                        continue
                    vx1, vy1, vx2, vy2 = v_line.box
                    inter_y = max(0, min(ly2, vy2) - max(ly1, vy1))
                    min_h = max(1, min(ly2 - ly1, vy2 - vy1))
                    dx = vx1 - lx2
                    if inter_y / min_h >= 0.5 and -0.5 * l_h <= dx <= 2.5 * l_h and vx1 > lx1:
                        matches.append((v_idx, v_line, v_text))
                if len(matches) == 1:
                    v_idx, v_line, v_text = matches[0]
                    conf = min(l_line.confidence, v_line.confidence)
                    proposals.append(EquipmentField(
                        id=f'field-{len(proposals)+1}', field=field, value=v_text,
                        unit=None, raw_text=f'{l_line.text} {v_line.text}', attempt_id=attempt.id,
                        region_index=attempt.region_index, line_index=v_idx,
                        box=v_line.box, ocr_confidence=conf, basis='explicit_label',
                        status='observed' if conf >= .75 else 'low_confidence',
                    ))
    # Repeated readings are corroboration, not independent measurements of accuracy.
    groups = {}
    for p in proposals:
        groups.setdefault((p.region_index, p.field, normalized(p.value), (p.unit or '').casefold()), []).append(p)
    result = []
    for group in groups.values():
        primary = max(group, key=lambda p: (p.ocr_confidence, p.basis == 'explicit_label'))
        primary.corroborating_attempts = sorted({p.attempt_id for p in group})
        result.append(primary)
    for p in result:
        if p.status == 'observed' and any(other.region_index == p.region_index and other.field == p.field
             and other.status != 'low_confidence' and normalized(other.value) != normalized(p.value)
             and (other.unit or '').casefold() == (p.unit or '').casefold() for other in result):
            p.status = 'conflicting'
    return result[:100]


def _category_matches(category_text, equipment_labels):
    for label in equipment_labels:
        term = re.sub(r'[_-]+', ' ', label).strip()
        if not term:
            continue
        pattern = r'(?<!\w)' + r'\s+'.join(re.escape(part) for part in term.split()) + r's?(?!\w)'
        if re.search(pattern, category_text or '', re.I):
            return True
    return False


def catalogue_candidates(db, fields, detections=None):
    reliable = [p for p in fields if p.status != 'low_confidence']
    searches = sorted({p.value for p in fields if p.field in {'manufacturer', 'model'}}, key=len, reverse=True)[:12]
    equipment_labels = sorted({
        d.label.strip().casefold()
        for d in (detections or [])
        if getattr(d, 'label', None) and d.label.strip().casefold() not in PLATE_LABELS
    })
    category_terms = [re.sub(r'[_-]+', ' ', label).strip() for label in equipment_labels if label][:6]
    if not searches and not category_terms:
        return [], 'insufficient_evidence', []
    clauses, params = [], []
    for value in searches:
        escaped = value.casefold().replace('!', '!!').replace('%', '!%').replace('_', '!_')
        clauses.append("(lower(manufacturer) LIKE ? ESCAPE '!' OR lower(model) LIKE ? ESCAPE '!')")
        params.extend(['%' + escaped + '%'] * 2)
    for term in category_terms:
        escaped = term.casefold().replace('!', '!!').replace('%', '!%').replace('_', '!_')
        clauses.append("(lower(category) LIKE ? ESCAPE '!')")
        params.append('%' + escaped + '%')
    # Manufacturer and visual-category retrieval include suggestions, never automatic acceptance.
    rows = db.execute("SELECT * FROM catalog_models WHERE status='published' AND (" + ' OR '.join(clauses)
                      + ') ORDER BY manufacturer,model,variant,id LIMIT 201', params).fetchall()
    warnings = ['catalogue_retrieval_truncated'] if len(rows) > 200 else []
    candidates = []
    regions = sorted({p.region_index for p in fields}) or [0]
    for row in rows[:200]:
        row = dict(row)
        cat_match = _category_matches(row['category'], equipment_labels)
        for region in regions:
            observed = {kind: [p for p in reliable if p.field == kind and p.region_index == region]
                        for kind in ['manufacturer', 'model']}
            matched, missing, conflicts, evidence = [], [], [], []
            for kind in ['manufacturer', 'model']:
                agreeing = [p for p in observed[kind] if normalized(p.value) == normalized(row[kind])]
                differing = [p for p in observed[kind] if normalized(p.value) != normalized(row[kind])]
                if agreeing:
                    matched.append(kind); evidence.extend(p.id for p in agreeing)
                if differing:
                    conflicts.append(kind); evidence.extend(p.id for p in differing)
                if not agreeing:
                    missing.append(kind)
            codes = [p for p in fields if p.field == 'model' and p.region_index == region]
            exact = any(normalized(p.value) == normalized(row['model']) for p in codes)
            similarity = max([SequenceMatcher(None, normalized(p.value), normalized(row['model'])).ratio() for p in codes] or [0])
            if 'manufacturer' not in matched and not exact:
                if cat_match and not searches:
                    candidate = EquipmentCandidate(
                        catalog_model_id=row['id'], manufacturer=row['manufacturer'],
                        model=row['model'], variant=row['variant'], category=row['category'],
                        source_ref=row['source_ref'], status='partial_evidence',
                        matched_fields=['category'], missing_fields=['manufacturer', 'model'],
                        conflicting_fields=conflicts, evidence_ids=[],
                        retrieval_basis='visual_category',
                    )
                    candidates.append((candidate, 0.0))
                continue
            state = 'conflicting_evidence' if conflicts else 'evidence_supported' if not missing else 'partial_evidence'
            matched_with_cat = matched + (['category'] if cat_match else [])
            candidate = EquipmentCandidate(catalog_model_id=row['id'],manufacturer=row['manufacturer'],
                model=row['model'],variant=row['variant'],category=row['category'],source_ref=row['source_ref'],
                status=state,matched_fields=matched_with_cat,missing_fields=missing,conflicting_fields=conflicts,
                evidence_ids=sorted(set(evidence)),retrieval_basis='exact_model' if exact else 'approximate_model' if similarity >= .65 else 'manufacturer_only')
            candidates.append((candidate, similarity))
    # Keep distinct variants visible; a shared model does not identify a physical asset.
    unique = {}
    for item, similarity in candidates:
        key = str(item.catalog_model_id)
        priority = ({'evidence_supported':2,'partial_evidence':1,'conflicting_evidence':0}[item.status], len(item.matched_fields), similarity)
        if key not in unique or priority > unique[key][0]: unique[key] = (priority, item)
    ranked = [item for _,item in sorted(unique.values(), key=lambda value:value[0], reverse=True)][:5]
    supported = [item for item in ranked if item.status == 'evidence_supported']
    status = 'supported_model_candidate' if len(supported)==1 else 'ambiguous_model_candidates' if supported else 'conflicting_evidence' if ranked and all(c.status=='conflicting_evidence' for c in ranked) else 'partial_evidence' if ranked else 'insufficient_evidence'
    if len({p.region_index for p in fields if p.status!='low_confidence' and p.field in {'manufacturer','model'}}) > 1:
        status = 'multiple_nameplates'; warnings.append('select_one_physical_machine_before_confirmation')
    return ranked, status, warnings
