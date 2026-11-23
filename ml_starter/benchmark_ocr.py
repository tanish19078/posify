"""Benchmark pretrained/local PaddleOCR on human-transcribed nameplate images."""
import argparse
import json
import re
from pathlib import Path


def distance(a, b):
    previous = list(range(len(b)+1))
    for i, char in enumerate(a, 1):
        current = [i]
        for j, other in enumerate(b, 1):
            current.append(min(current[-1]+1, previous[j]+1, previous[j-1]+(char!=other)))
        previous = current
    return previous[-1]


def normalize(text): return ' '.join(text.split())


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--labels',required=True,help='JSONL: image,text and optional serial fields')
    parser.add_argument('--images',required=True)
    parser.add_argument('--output',default='ocr_evaluation.json')
    parser.add_argument('--det-dir')
    parser.add_argument('--rec-dir')
    parser.add_argument('--device',default='cpu')
    args=parser.parse_args()
    if bool(args.det_dir) != bool(args.rec_dir): parser.error('Supply both local model directories or neither')
    rows=[json.loads(line) for line in Path(args.labels).read_text().splitlines() if line.strip()]
    if not rows: parser.error('Ground-truth labels are empty')
    from paddleocr import PaddleOCR
    config=dict(text_detection_model_name='PP-OCRv5_mobile_det',
                text_recognition_model_name='en_PP-OCRv5_mobile_rec',
                use_doc_orientation_classify=False,use_doc_unwarping=False,
                use_textline_orientation=False,device=args.device)
    if args.det_dir:
        config.update(text_detection_model_dir=args.det_dir,text_recognition_model_dir=args.rec_dir)
    model=PaddleOCR(**config)
    root=Path(args.images).resolve()
    predictions=[]; edits=chars=exact=serial_count=serial_correct=0
    for row in rows:
        path=(root/row['image']).resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise ValueError('Image is missing or outside image root')
        expected=normalize(row['text'])
        if not expected: raise ValueError('Ground truth must be non-empty')
        parts=[]
        for result in model.predict(str(path)): parts.extend(result['rec_texts'])
        predicted=normalize('\n'.join(parts))
        error=distance(expected,predicted)
        edits+=error; chars+=len(expected); exact+=int(expected==predicted)
        found=set(re.findall(r'(?:serial(?:\s+(?:no\.?|number))?|s/n)\s*[:#=]\s*([A-Za-z0-9][A-Za-z0-9._/-]*)',predicted,re.I))
        serial=next(iter(found)) if len(found)==1 else None
        if row.get('serial') is not None:
            serial_count+=1; serial_correct+=int(serial==row['serial'])
        predictions.append({'image':row['image'],'expected':expected,'predicted':predicted,
                            'character_edits':error,'predicted_serial':serial})
    report={'images':len(rows),'character_error_rate':edits/chars,'exact_text_accuracy':exact/len(rows),
            'serial_exact_accuracy':serial_correct/serial_count if serial_count else None,
            'serial_examples':serial_count,'predictions':predictions,
            'note':'Human labels required. Synthetic examples or model-generated labels are not a field-accuracy benchmark.'}
    Path(args.output).write_text(json.dumps(report,indent=2,ensure_ascii=False))
    print(json.dumps({k:v for k,v in report.items() if k!='predictions'},indent=2))


if __name__=='__main__': main()
