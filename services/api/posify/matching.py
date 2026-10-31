"""Conservative label parsing; OCR scores are not identity probabilities."""
import re

PATTERN = re.compile(
    r'(?<!\w)(asset\s+tag|asset|tag|serial(?:\s+(?:no\.?|number))?|s/n)'
    r'\s*[:#=]\s*([A-Za-z0-9][A-Za-z0-9._/\-]{0,79})(?![A-Za-z0-9._/\-])', re.I)


def extract_identifiers(lines, threshold=0.75):
    found = []
    for index, line in enumerate(lines):
        if line.confidence < threshold:
            continue
        for match in PATTERN.finditer(line.text):
            label, value = match.groups()
            kind = 'serial' if label.lower().startswith(('serial', 's/n')) else 'tag'
            found.append({'kind': kind, 'value': value, 'line_index': index,
                          'confidence': line.confidence})
    return found


def match_identifiers(db, site_id, identifiers):
    values = {kind: {item['value'] for item in identifiers if item['kind'] == kind}
              for kind in ['tag', 'serial']}
    if not any(values.values()):
        return {'status': 'insufficient_evidence', 'candidates': []}
    if any(len(v) > 1 for v in values.values()):
        return {'status': 'ambiguous_identifiers', 'candidates': []}
    clauses, args = ['site_id=?'], [site_id]
    for kind, candidates in values.items():
        if candidates:
            clauses.append(kind + '=?')
            args.append(next(iter(candidates)))
    rows = db.execute('SELECT * FROM assets WHERE ' + ' AND '.join(clauses), args).fetchall()
    return {'status': 'candidate_found' if rows else 'no_match', 'candidates': [dict(row) for row in rows]}
