"""Prepare, remap, and merge YOLO datasets into a validated multi-class layout.

Supports:
1. Canonical class ordering (e.g. nameplate, pump, valve, motor).
2. Remapping source-specific class names/IDs (e.g. '0' -> 'pump', 'open'/'close' -> 'valve').
3. Merging annotations when the same image (by SHA-256) is annotated across sources.
4. Deterministic creation of missing val/test splits without cross-split leakage.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

from validate_dataset import EXTENSIONS, inspect_dataset


def _load_names(data_cfg):
    names = data_cfg.get('names')
    if isinstance(names, dict):
        if sorted(int(k) for k in names) != list(range(len(names))):
            raise ValueError('Source class IDs must be contiguous integers starting at zero')
        return [str(names[i]) if i in names else str(names[str(i)]) for i in range(len(names))]
    if isinstance(names, list) and names:
        return [str(n) for n in names]
    raise ValueError('Source data.yaml must define a non-empty names list or mapping')


def _find_split_dirs(root, data_cfg):
    found = {}
    for canonical, candidates in [('train', ['train']), ('val', ['val', 'valid']), ('test', ['test'])]:
        configured = None
        for key in candidates:
            if data_cfg.get(key):
                configured = Path(data_cfg[key])
                break
        if configured is not None:
            folder = (root / configured).resolve() if not configured.is_absolute() else configured.resolve()
            if not folder.is_dir():
                for key in candidates:
                    alt = (root / key / 'images').resolve()
                    if alt.is_dir():
                        folder = alt
                        break
            if folder.is_dir():
                found[canonical] = folder
                continue
        for key in candidates:
            alt = (root / key / 'images').resolve()
            if alt.is_dir():
                found[canonical] = alt
                break
    if 'train' not in found:
        raise ValueError(f'No train images folder found under {root}')
    return found


def _label_path_for(image_path):
    parts = list(image_path.parts)
    positions = [i for i, part in enumerate(parts[:-1]) if part == 'images']
    if not positions:
        raise ValueError(f'Image path must contain an images directory: {image_path}')
    parts[positions[-1]] = 'labels'
    return Path(*parts).with_suffix('.txt')


def _box_iou(a, b):
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    inter = max(0.0, min(ax2, bx2) - max(ax1, bx1)) * max(0.0, min(ay2, by2) - max(ay1, by1))
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def _assign_missing_splits(records, need_val, need_test):
    """Deterministically partition train records by SHA-256 into train/val/test when splits are absent."""
    train_items = sorted([r for r in records.values() if r['split'] == 'train'], key=lambda r: r['sha256'])
    n = len(train_items)
    if (need_val or need_test) and n < 3:
        raise ValueError('Need at least 3 training images to carve out missing val/test splits')
    test_count = max(1, round(n * 0.10)) if need_test else 0
    val_count = max(1, round(n * 0.15)) if need_val else 0
    if test_count + val_count >= n:
        raise ValueError('Not enough training images to allocate distinct train, val, and test splits')
    for idx, item in enumerate(train_items):
        if idx < test_count:
            item['split'] = 'test'
        elif idx < test_count + val_count:
            item['split'] = 'val'


def prepare_multiclass(sources, target_classes, output_dir, ensure_splits=True):
    """Merge and remap one or more YOLO datasets into output_dir.

    sources: list of dicts:
      - path: path to source dataset root or data.yaml
      - class_map: optional dict mapping source class name (or stringified ID) -> target class name (or None to drop)
      - prefix: optional filename prefix (defaults to s0, s1, ...)
    target_classes: ordered list of unique target class names
    """
    import yaml
    if not isinstance(target_classes, list) or not target_classes or len(set(target_classes)) != len(target_classes):
        raise ValueError('target_classes must be a non-empty list of unique class names')
    target_index = {name: idx for idx, name in enumerate(target_classes)}
    out = Path(output_dir).resolve()
    if out.exists() and any(out.iterdir()):
        raise ValueError(f'Output directory must be empty: {out}')

    records = {}  # sha256 -> {'split': str, 'path': Path, 'name': str, 'boxes': list[(cls_id, x, y, w, h)], 'sources': set}
    source_summaries = []
    has_val = False
    has_test = False

    for src_idx, src in enumerate(sources):
        src_path = Path(src['path']).resolve()
        yaml_path = src_path if src_path.is_file() else src_path / 'data.yaml'
        if not yaml_path.is_file():
            raise ValueError(f'Missing data.yaml at {yaml_path}')
        root = yaml_path.parent
        cfg = yaml.safe_load(yaml_path.read_text())
        if not isinstance(cfg, dict) or 'download' in cfg:
            raise ValueError(f'Invalid or unsafe data.yaml in {yaml_path}')
        src_names = _load_names(cfg)
        raw_map = src.get('class_map') or {name: name for name in src_names}
        resolved_map = {}
        for cls_id, cls_name in enumerate(src_names):
            mapped = raw_map.get(cls_name, raw_map.get(str(cls_id), cls_name if not src.get('class_map') else None))
            if mapped is not None:
                if mapped not in target_index:
                    raise ValueError(f'Mapped class {mapped!r} from {yaml_path} is not in target_classes {target_classes}')
                resolved_map[cls_id] = target_index[mapped]
        if not resolved_map:
            raise ValueError(f'Source {yaml_path} maps no classes into target_classes')

        split_dirs = _find_split_dirs(root, cfg)
        if 'val' in split_dirs:
            has_val = True
        if 'test' in split_dirs:
            has_test = True

        prefix = src.get('prefix') or f'src{src_idx}'
        src_counts = {'source': str(root), 'source_classes': src_names, 'images_read': 0, 'boxes_kept': 0}

        for split, folder in split_dirs.items():
            images = sorted(p for p in folder.rglob('*') if p.suffix.lower() in EXTENSIONS)
            for image_path in images:
                label_path = _label_path_for(image_path)
                if not label_path.is_file():
                    raise ValueError(f'Missing label file: {label_path}')
                digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
                parsed_boxes = []
                for line_no, line in enumerate(label_path.read_text().splitlines(), 1):
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) != 5:
                        raise ValueError(f'{label_path}:{line_no}: expected 5 fields')
                    src_cls = int(parts[0])
                    if not 0 <= src_cls < len(src_names):
                        raise ValueError(f'{label_path}:{line_no}: unknown source class {src_cls}')
                    if src_cls not in resolved_map:
                        continue
                    dst_cls = resolved_map[src_cls]
                    coords = tuple(float(v) for v in parts[1:])
                    parsed_boxes.append((dst_cls, *coords))

                src_counts['images_read'] += 1
                src_counts['boxes_kept'] += len(parsed_boxes)

                if digest in records:
                    existing = records[digest]
                    if existing['split'] != split:
                        raise ValueError(
                            f'Cross-split duplicate image (sha256={digest[:12]}): '
                            f'{existing["path"]} ({existing["split"]}) vs {image_path} ({split})'
                        )
                    for box in parsed_boxes:
                        if not any(b[0] == box[0] and _box_iou(b[1:], box[1:]) > 0.95 for b in existing['boxes']):
                            existing['boxes'].append(box)
                    existing['sources'].add(prefix)
                else:
                    records[digest] = {
                        'sha256': digest,
                        'split': split,
                        'path': image_path,
                        'name': f'{prefix}_{image_path.stem}_{digest[:8]}{image_path.suffix.lower()}',
                        'boxes': parsed_boxes,
                        'sources': {prefix},
                    }
        source_summaries.append(src_counts)

    if ensure_splits and (not has_val or not has_test):
        _assign_missing_splits(records, need_val=not has_val, need_test=not has_test)

    out.mkdir(parents=True, exist_ok=True)
    for split in ['train', 'valid', 'test']:
        (out / split / 'images').mkdir(parents=True, exist_ok=True)
        (out / split / 'labels').mkdir(parents=True, exist_ok=True)

    for item in sorted(records.values(), key=lambda r: (r['split'], r['name'])):
        folder_name = 'valid' if item['split'] == 'val' else item['split']
        dst_img = out / folder_name / 'images' / item['name']
        dst_lbl = out / folder_name / 'labels' / Path(item['name']).with_suffix('.txt')
        shutil.copy2(item['path'], dst_img)
        lines = [f'{cls_id} {x:.6f} {y:.6f} {w:.6f} {h:.6f}' for cls_id, x, y, w, h in item['boxes']]
        dst_lbl.write_text('\n'.join(lines) + ('\n' if lines else ''))

    data_yaml = {
        'path': str(out),
        'train': 'train/images',
        'val': 'valid/images',
        'test': 'test/images',
        'names': {i: name for i, name in enumerate(target_classes)},
    }
    yaml_out = out / 'data.yaml'
    yaml_out.write_text(yaml.safe_dump(data_yaml, sort_keys=False))
    _, validation_report = inspect_dataset(yaml_out)
    validation_report['sources'] = source_summaries
    (out / 'prepare_report.json').write_text(json.dumps(validation_report, indent=2))
    return yaml_out, validation_report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--spec', help='JSON file with {"target_classes": [...], "sources": [...]}')
    parser.add_argument('--source', action='append', default=[],
                        help='Dataset directory or data.yaml (can be passed multiple times)')
    parser.add_argument('--classes', help='Comma-separated canonical target classes, e.g. nameplate,pump,valve,motor')
    parser.add_argument('--remap', action='append', default=[],
                        help='Optional class mapping old=new (applies to all --source arguments unless --spec is used)')
    parser.add_argument('--output', required=True, help='Empty output directory for prepared dataset')
    parser.add_argument('--no-ensure-splits', action='store_true',
                        help='Do not automatically carve out missing val/test splits from train')
    args = parser.parse_args()

    if args.spec:
        spec = json.loads(Path(args.spec).read_text())
        target_classes = spec['target_classes']
        sources = spec['sources']
    else:
        if not args.source or not args.classes:
            parser.error('Provide either --spec or both --source and --classes')
        target_classes = [c.strip() for c in args.classes.split(',') if c.strip()]
        remap = {}
        for item in args.remap:
            if '=' not in item:
                parser.error(f'Invalid --remap {item!r}; expected old=new')
            k, v = item.split('=', 1)
            remap[k.strip()] = v.strip() or None
        sources = [{'path': s, 'class_map': remap or None} for s in args.source]

    yaml_out, report = prepare_multiclass(
        sources=sources,
        target_classes=target_classes,
        output_dir=args.output,
        ensure_splits=not args.no_ensure_splits,
    )
    print(json.dumps(report, indent=2))
    print('Prepared multi-class dataset config:', yaml_out)


if __name__ == '__main__':
    main()
