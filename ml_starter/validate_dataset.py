"""Validate YOLO boxes and detect exact image/group leakage before training."""
import argparse
import csv
import hashlib
import json
import math
from pathlib import Path

EXTENSIONS = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}


def inspect_dataset(config_path, groups_path=None):
    import yaml
    from PIL import Image
    config_path = Path(config_path).resolve()
    config = yaml.safe_load(config_path.read_text())
    if not isinstance(config, dict) or 'download' in config:
        raise ValueError('Use a plain local dataset YAML without a download directive')
    names = config.get('names')
    if isinstance(names, dict):
        if sorted(names) != list(range(len(names))):
            raise ValueError('Class IDs must be contiguous integers starting at zero')
        names = [names[i] for i in range(len(names))]
    if not isinstance(names, list) or not names or len(set(names)) != len(names) or any(not isinstance(n, str) or not n.strip() for n in names):
        raise ValueError('names must contain unique non-empty class labels')
    root = Path(config.get('path') or config_path.parent)
    if not root.is_absolute(): root = config_path.parent / root
    root = root.resolve()
    image_rows, counts, errors, hashes, all_paths = [], {}, [], {}, set()
    normalized = {'path': str(root), 'names': names}
    for split in ['train', 'val', 'test']:
        value = config.get(split)
        if not value:
            if split != 'test': errors.append(f'Missing {split} split')
            continue
        if not isinstance(value, str) or '://' in value:
            raise ValueError('This starter expects local directory paths for each split')
        folder = Path(value)
        folder = (root / folder).resolve() if not folder.is_absolute() else folder.resolve()
        if not folder.is_dir():
            errors.append(f'{split} directory does not exist: {folder}. Fix paths in data.yaml.')
            continue
        normalized[split] = str(folder)
        images = sorted(p for p in folder.rglob('*') if p.suffix.lower() in EXTENSIONS)
        counts[split] = {'images': len(images), 'objects': [0]*len(names), 'negatives': 0}
        if not images: errors.append(f'{split} has no images')
        for image in images:
            resolved = str(image.resolve())
            if resolved in all_paths: errors.append(f'Image path appears in multiple splits: {image}')
            all_paths.add(resolved)
            try:
                with Image.open(image) as opened: opened.verify()
            except Exception:
                errors.append(f'Cannot decode image: {image}')
                continue
            digest = hashlib.sha256(image.read_bytes()).hexdigest()
            if digest in hashes:
                errors.append(f'Duplicate image bytes: {image} and {hashes[digest][1]}')
            hashes[digest] = (split, str(image))
            parts = list(image.parts)
            positions = [i for i, part in enumerate(parts[:-1]) if part == 'images']
            if not positions:
                errors.append(f'Image path must contain an images directory: {image}')
                continue
            parts[positions[-1]] = 'labels'
            label = Path(*parts).with_suffix('.txt')
            if not label.is_file():
                errors.append(f'Missing label file: {label}. Use an empty TXT for an intentional negative.')
                continue
            lines = [line for line in label.read_text().splitlines() if line.strip()]
            if not lines: counts[split]['negatives'] += 1
            for number, line in enumerate(lines, 1):
                try:
                    fields = line.split()
                    if len(fields) != 5: raise ValueError('Expected class xc yc width height')
                    cls = int(fields[0]); x,y,w,h = map(float, fields[1:])
                    if not 0 <= cls < len(names): raise ValueError('Unknown class ID')
                    if not all(math.isfinite(v) for v in (x,y,w,h)): raise ValueError('Nonfinite box')
                    if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1): raise ValueError('Box is not normalized')
                    if min(x-w/2,y-h/2) < -1e-5 or max(x+w/2,y+h/2) > 1+1e-5: raise ValueError('Box crosses image boundary')
                    counts[split]['objects'][cls] += 1
                except ValueError as exc:
                    errors.append(f'{label}:{number}: {exc}')
            image_rows.append({'path': str(image), 'split': split, 'sha256': digest})
    notes = ['Near-duplicates are not detected by byte hashes. Split by physical asset/capture session before augmentation.']
    if groups_path:
        group_map = {}
        with Path(groups_path).open(newline='') as stream:
            reader = csv.DictReader(stream)
            if not {'image', 'group_id'} <= set(reader.fieldnames or []):
                raise ValueError('Groups CSV requires image,group_id columns; paths are relative to dataset root')
            for row in reader:
                key = str((root / row['image']).resolve())
                if key in group_map or not row['group_id'].strip(): errors.append(f'Duplicate/empty grouping entry: {key}')
                group_map[key] = row['group_id']
        seen = {}
        for image in image_rows:
            group = group_map.get(image['path'])
            if not group:
                errors.append(f'Missing group for {image["path"]}')
            elif group in seen and seen[group] != image['split']:
                errors.append(f'Group {group} crosses {seen[group]} and {image["split"]}')
            else: seen[group] = image['split']
    else:
        notes.append('No groups CSV supplied: asset/session leakage has NOT been checked.')
    if 'train' in counts and any(n == 0 for n in counts['train']['objects']): errors.append('At least one class has no training boxes')
    if errors: raise ValueError('\n'.join(errors[:50]))
    pairs = []
    for image in image_rows:
        parts = list(Path(image['path']).parts); positions = [i for i,p in enumerate(parts[:-1]) if p == 'images']
        parts[positions[-1]] = 'labels'
        label_hash = hashlib.sha256(Path(*parts).with_suffix('.txt').read_bytes()).hexdigest()
        pairs.append((image['split'], image['sha256'], label_hash))
    fingerprint = hashlib.sha256(json.dumps({'pairs': sorted(pairs), 'names': names},sort_keys=True).encode()).hexdigest()
    return normalized, {'classes': names, 'splits': counts, 'fingerprint': fingerprint, 'notes': notes}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', required=True)
    parser.add_argument('--groups')
    parser.add_argument('--report', default='dataset_report.json')
    args = parser.parse_args()
    try: _, report = inspect_dataset(args.data, args.groups)
    except ValueError as exc: parser.exit(2, str(exc)+'\n')
    Path(args.report).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))


if __name__ == '__main__': main()
