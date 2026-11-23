"""Fine-tune a YOLO11 detection model on a validated local YOLO dataset."""
import argparse
import json
from pathlib import Path

from validate_dataset import inspect_dataset


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True)
    parser.add_argument('--groups')
    parser.add_argument('--weights', default='yolo11n.pt')
    parser.add_argument('--epochs', type=int, default=60)
    parser.add_argument('--batch', type=int, default=8)
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--device', default='0')
    parser.add_argument('--project', default='/content/runs')
    parser.add_argument('--name', default='nameplate_yolo11n')
    args = parser.parse_args()
    if args.epochs < 1 or args.batch < 1 or args.imgsz < 32 or args.imgsz % 32:
        parser.error('Use positive epochs/batch and an image size divisible by 32')
    import yaml
    config, report = inspect_dataset(args.data, args.groups)
    import torch
    from ultralytics import YOLO
    if args.device != 'cpu' and not torch.cuda.is_available():
        parser.error('Enable a GPU runtime in Colab or pass --device cpu')
    target = Path(args.project).resolve() / args.name
    if target.exists(): parser.error('Run directory exists; choose a fresh --name to avoid overwriting artifacts')
    prepared = Path(args.project).resolve() / (args.name + '_inputs')
    prepared.mkdir(parents=True, exist_ok=False)
    normalized = prepared / 'data.yaml'
    normalized.write_text(yaml.safe_dump(config, sort_keys=False))
    (prepared / 'dataset_report.json').write_text(json.dumps(report, indent=2))
    model = YOLO(args.weights)  # Official YOLO11 pretrained weights download when absent.
    if model.task != 'detect': parser.error('Only object detection checkpoints are supported')
    model.train(data=str(normalized), epochs=args.epochs, imgsz=args.imgsz, batch=args.batch,
                device=args.device, project=str(Path(args.project).resolve()), name=args.name,
                seed=42, deterministic=True, workers=2, patience=15, exist_ok=False,
                amp=True, hsv_h=.01, hsv_s=.3, hsv_v=.3, degrees=8,
                translate=.1, scale=.3, fliplr=0, flipud=0, mosaic=.5, close_mosaic=10)
    # Avoid mirror augmentation for nameplate OCR. No accuracy target is assumed.
    print('Training complete. Inspect:', target)
    print('Best checkpoint:', target / 'weights' / 'best.pt')


if __name__ == '__main__': main()
