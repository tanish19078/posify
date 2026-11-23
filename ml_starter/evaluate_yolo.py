"""Evaluate a trained detector on validation or a previously untouched test split."""
import argparse
import json
from pathlib import Path

from validate_dataset import inspect_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', required=True)
    parser.add_argument('--data', required=True)
    parser.add_argument('--groups')
    parser.add_argument('--split', choices=['val','test'], default='test')
    parser.add_argument('--device', default='0')
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--output', default='detector_evaluation.json')
    args = parser.parse_args()
    config, report = inspect_dataset(args.data, args.groups)
    if args.split not in config: parser.error('Requested split is absent; prepare a held-out test set first')
    import tempfile
    import yaml
    from ultralytics import YOLO
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp)/'data.yaml'; path.write_text(yaml.safe_dump(config))
        result = YOLO(args.weights).val(data=str(path), split=args.split, device=args.device,
                                       imgsz=args.imgsz, batch=8, plots=True)
    metrics = {k: float(v) for k,v in result.results_dict.items()}
    per_class = {}
    box_metrics = getattr(result, 'box', None)
    if box_metrics is not None and hasattr(box_metrics, 'ap_class_index'):
        for idx_pos, cls_idx in enumerate(box_metrics.ap_class_index):
            cls_id = int(cls_idx)
            cls_name = report['classes'][cls_id] if 0 <= cls_id < len(report['classes']) else str(cls_id)
            p, r, ap50, ap = box_metrics.class_result(idx_pos)
            per_class[cls_name] = {
                'class_id': cls_id,
                'precision': float(p),
                'recall': float(r),
                'map50': float(ap50),
                'map50_95': float(ap),
            }
    output = {'split': args.split, 'dataset': report, 'metrics': metrics, 'per_class': per_class,
              'note': 'Detection metrics do not establish exact asset identity or OCR accuracy.'}
    Path(args.output).write_text(json.dumps(output, indent=2, allow_nan=False))
    print(json.dumps(output, indent=2))


if __name__ == '__main__': main()
