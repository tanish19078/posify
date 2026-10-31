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
    retrieval_basis: Literal['exact_model', 'approximate_model', 'manufacturer_only']
    requires_review: bool = True


def normalized(value):
    """Case/space normalization only. Do not silently repair S/5, O/0 or I/1."""
    value = unicodedata.normalize('NFKC', value).casefold()
    return re.sub(r'\s+', '', value).replace('–', '-').replace('—', '-')


LABELS = {
    'manufacturer': r'(?:manufacturer|mfr|maker)',
    'model': r'(?:model|type|typ)',
    'serial': r'(?:serial(?:\s*(?:no\.?|number))?|s/n)',
    'asset_tag': r'(?:asset\s*tag|asset|tag)',
    'frame': r'(?:frame)',
}
CODE = re.compile(r'(?<![\w/-])(?:[0-9]\s*)?[A-Z]{1,5}\s*[A-Z0-9]{2,}(?:\s*[-/]\s*[A-Z0-9]{1,12}){1,3}(?![\w/-])', re.I)
UNITS = {
    'voltage': r'V|VOLTS?', 'power': r'kW|HP',
    'speed': r'RPM|r/min', 'frequency': r'Hz',
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
                pattern = rf'(?<!\w){label}\s*(?:[:#=]\s*|\s+)([A-Z0-9][A-Z0-9 ._/-]{{0,79}})'
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
                    if value:
                        found.append((field, value, None, 'explicit_label'))
            for manufacturer, expression in vocabulary:
                if expression.search(text):
                    found.append(('manufacturer', manufacturer, None, 'catalogue_vocabulary'))
            if index < 2:
                possible = [word for word in line.words if re.fullmatch('[A-Z]{4,24}',word.text)
                            and word.text not in header_stop and word.confidence >= .65]
                if len(possible)==1:
                    found.append(('manufacturer', possible[0].text, None, 'header_candidate'))
                elif not line.words and re.fullmatch('[A-Z]{4,24}',text.strip()) and text.strip() not in header_stop:
                    found.append(('manufacturer',text.strip(),None,'header_candidate'))
            if index < 4 and not re.search(r'\b(?:serial|s/n|asset|frame)\b', text, re.I):
                for match in CODE.finditer(text):
                    value = re.sub(r'\s+', '', match[0])
                    if sum(c.isdigit() for c in value) >= 3 and sum(c.isalpha() for c in value) >= 2 and not re.match(r'^(?:IEC|ISO|DIN|EN)\d', value, re.I):
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


def catalogue_candidates(db, fields):
    reliable = [p for p in fields if p.status != 'low_confidence']
    searches = sorted({p.value for p in fields if p.field in {'manufacturer', 'model'}}, key=len, reverse=True)[:12]
    if not searches:
        return [], 'insufficient_evidence', []
    clauses, params = [], []
    for value in searches:
        escaped = value.casefold().replace('!', '!!').replace('%', '!%').replace('_', '!_')
        clauses.append("(lower(manufacturer) LIKE ? ESCAPE '!' OR lower(model) LIKE ? ESCAPE '!')")
        params.extend(['%' + escaped + '%'] * 2)
    # Manufacturer retrieval includes approximate model suggestions, never acceptance.
    rows = db.execute("SELECT * FROM catalog_models WHERE status='published' AND (" + ' OR '.join(clauses)
                      + ') ORDER BY manufacturer,model,variant,id LIMIT 201', params).fetchall()
    warnings = ['catalogue_retrieval_truncated'] if len(rows) > 200 else []
    candidates = []
    for row in rows[:200]:
        row = dict(row)
        for region in sorted({p.region_index for p in fields}):
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
                continue
            state = 'conflicting_evidence' if conflicts else 'evidence_supported' if not missing else 'partial_evidence'
            candidate = EquipmentCandidate(catalog_model_id=row['id'],manufacturer=row['manufacturer'],
                model=row['model'],variant=row['variant'],category=row['category'],source_ref=row['source_ref'],
                status=state,matched_fields=matched,missing_fields=missing,conflicting_fields=conflicts,
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
