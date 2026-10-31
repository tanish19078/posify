"""Exact, explicitly scoped field metrics. No OCR confidence-to-accuracy conversion."""
from posify.recognition import normalized


def field_metrics(cases):
    correct=wrong=missing=0
    for case in cases:
        fields=case['predicted_fields']
        for name,expected in case['expected_fields'].items():
            values={normalized(field['value']) for field in fields if field['field']==name and field['status']=='observed'}
            if values=={normalized(expected)}: correct+=1
            elif len(values)==1: wrong+=1;missing+=1
            else: missing+=1
    return {'correct':correct,'wrong':wrong,'missing_or_wrong':missing,
            'precision':correct/(correct+wrong) if correct+wrong else None,
            'recall':correct/(correct+missing) if correct+missing else None,
            'coverage':(correct+wrong)/(correct+missing) if correct+missing else None,
            'scope':'Only explicitly annotated fields; ambiguous and low-confidence fields abstain.'}
