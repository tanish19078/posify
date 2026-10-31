"""Prepare local Brag assets from measured detector results and licensed sources."""
import argparse
import json
import hashlib
import math
import os
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageOps
from posify.ocr import LocalOCR


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--brag-dir', required=True, type=Path)
    parser.add_argument('--hyperframes-dir', type=Path)
    parser.add_argument('--output', type=Path, default=Path('brag-output/composition'))
    parser.add_argument('--report', type=Path, default=Path('var/nameplate-integration.json'))
    parser.add_argument('--images', type=Path, default=Path('var/public-nameplates'))
    parser.add_argument('--fonts', type=Path, default=Path('/usr/share/fonts/truetype/dejavu'))
    args = parser.parse_args()
    if args.hyperframes_dir is None:
        executable = shutil.which('hyperframes')
        if not executable:
            parser.error('Run inside npx --package=hyperframes@0.8.223 -c, or supply --hyperframes-dir')
        args.hyperframes_dir = Path(executable).resolve().parents[1]
    report = json.loads(args.report.read_text())
    case = next(row for row in report['cases'] if row['source']['id'] == 'current-transformer')
    source = args.images / 'current-transformer.jpg'
    if hashlib.sha256(source.read_bytes()).hexdigest() != case['source']['sha256']:
        raise ValueError('Photo does not match the measured source digest')
    assets = args.output / 'assets'
    for folder in ['fonts', 'music', 'sfx', 'vendor']:
        (assets / folder).mkdir(parents=True, exist_ok=True)
    copies = {
        args.fonts / 'DejaVuSans-Bold.ttf': 'fonts/display.ttf',
        args.fonts / 'DejaVuSans.ttf': 'fonts/body.ttf',
        args.fonts / 'DejaVuSansMono.ttf': 'fonts/mono.ttf',
        args.brag_dir / 'assets/music/happy-beats-business-moves-vol-12-by-ende-dot-app.mp3': 'music/bed.mp3',
        args.brag_dir / 'assets/sfx/interface/click_003.ogg': 'sfx/click.ogg',
        args.brag_dir / 'assets/sfx/impact/impactSoft_medium_001.ogg': 'sfx/reveal.ogg',
        args.hyperframes_dir / 'dist/vendor/npm/gsap@3.15.0/dist/gsap.min.js': 'vendor/gsap.min.js',
    }
    for original, relative in copies.items():
        shutil.copyfile(original, assets / relative)
    with Image.open(source) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
        image.save(assets / 'nameplate.jpg', quality=95)
    with Image.open(assets / 'nameplate.jpg') as image:
        x1, y1, x2, y2 = case['detections'][0]['box']
        image.crop((math.floor(x1), math.floor(y1), math.ceil(x2), math.ceil(y2))).save(assets / 'crop.png')
    os.environ['POSIFY_OCR_ENGINE'] = 'tesseract'
    lines = LocalOCR().recognize(assets / 'crop.png')
    if len(lines) != case['ocr_lines'] or len(lines) < 5:
        raise ValueError('OCR differs from the demo evidence; review copy before rebuilding')
    (assets / 'evidence.json').write_text(json.dumps({'case': case, 'ocr': [line.model_dump() for line in lines]}, indent=2)+'\n')
    helper = args.hyperframes_dir / 'dist/skills/media-use/audio/scripts/extract-audio-data.py'
    subprocess.run(['python3', str(helper), str(assets / 'music/bed.mp3'), '--fps', '30', '--bands', '8',
                    '-o', str(assets / 'music/audio-data.json')], check=True)
    print('Licensed photo/audio and actual OCR evidence prepared locally.')


if __name__ == '__main__':
    main()
