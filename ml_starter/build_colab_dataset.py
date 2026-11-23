"""Download public industrial imagery and build a validated 4-class YOLO dataset.

Classes:
  0: nameplate
  1: pump
  2: valve
  3: motor

Works in Google Colab without private API keys:
- Attempts to download pinned CC-licensed Wikimedia Commons nameplate/equipment photos.
- Generates group-isolated train/valid/test industrial equipment + nameplate scenes
  with exact YOLO bounding boxes (incorporating real photo textures when available).
- Validates the resulting dataset with validate_dataset.inspect_dataset().
"""
import argparse
import hashlib
import io
import json
import random
import shutil
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageOps

from validate_dataset import inspect_dataset

CLASSES = ['nameplate', 'pump', 'valve', 'motor']

COMMONS_CATEGORIES = {
    'nameplate': ['Category:Nameplates', 'Category:Machine_nameplates'],
    'pump': ['Category:Centrifugal_pumps', 'Category:Pumps'],
    'valve': ['Category:Industrial_valves', 'Category:Gate_valves', 'Category:Ball_valves'],
    'motor': ['Category:Electric_motors', 'Category:Induction_motors'],
}

PUBLIC_COMMONS_SOURCES = [
    {
        'id': 'electrolux',
        'url': 'https://upload.wikimedia.org/wikipedia/commons/4/4c/Motor_Nameplate.jpg',
        'kind': 'nameplate',
    },
    {
        'id': 'current-transformer',
        'url': 'https://upload.wikimedia.org/wikipedia/commons/1/19/Nameplate_of_a_CT.jpg',
        'kind': 'nameplate',
    },
    {
        'id': 'malmbergs',
        'url': 'https://upload.wikimedia.org/wikipedia/commons/f/f9/Motor_nameplate_Malmbergs.jpg',
        'kind': 'nameplate',
    },
    {
        'id': 'westinghouse',
        'url': 'https://upload.wikimedia.org/wikipedia/commons/a/af/Nameplate_for_one_of_Fireboat_Firefighter_%27s_600V_DC_Marine_Motors.jpg',
        'kind': 'nameplate',
    },
]


def _fetch_real_plates(cache_dir, timeout=8):
    """Best-effort download of public CC nameplate & equipment images from Wikimedia Commons."""
    bank = {cls: [] for cls in CLASSES}
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    headers = {'User-Agent': 'PosifyMLStarter/2.0 (https://github.com/tanish19078/posify)'}
    for item in PUBLIC_COMMONS_SOURCES:
        target = cache_dir / f"{item['id']}.jpg"
        try:
            if not target.is_file():
                req = urllib.request.Request(item['url'], headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    target.write_bytes(resp.read())
            with Image.open(target) as img:
                rgb = ImageOps.exif_transpose(img).convert('RGB')
                rgb.thumbnail((480, 320), Image.Resampling.LANCZOS)
                bank['nameplate'].append(rgb.copy())
        except Exception:
            continue

    for cls_name, categories in COMMONS_CATEGORIES.items():
        for cat in categories:
            if len(bank[cls_name]) >= 18:
                break
            params = urllib.parse.urlencode({
                'action': 'query',
                'generator': 'categorymembers',
                'gcmtitle': cat,
                'gcmtype': 'file',
                'gcmlimit': '20',
                'prop': 'imageinfo',
                'iiprop': 'url|mime',
                'iiurlwidth': '640',
                'format': 'json',
            })
            api_url = f'https://commons.wikimedia.org/w/api.php?{params}'
            try:
                req = urllib.request.Request(api_url, headers=headers)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode('utf-8'))
                pages = (payload.get('query') or {}).get('pages') or {}
                for page_id, page in sorted(pages.items()):
                    if len(bank[cls_name]) >= 18:
                        break
                    infos = page.get('imageinfo') or []
                    if not infos:
                        continue
                    mime = infos[0].get('mime', '')
                    thumb_url = infos[0].get('thumburl') or infos[0].get('url')
                    if mime not in {'image/jpeg', 'image/png'} or not thumb_url:
                        continue
                    img_file = cache_dir / f'{cls_name}_{page_id}.jpg'
                    if not img_file.is_file():
                        img_req = urllib.request.Request(thumb_url, headers=headers)
                        with urllib.request.urlopen(img_req, timeout=timeout) as img_resp:
                            img_file.write_bytes(img_resp.read())
                    with Image.open(img_file) as opened:
                        rgb = ImageOps.exif_transpose(opened).convert('RGB')
                        if min(rgb.size) >= 64:
                            rgb.thumbnail((480, 480), Image.Resampling.LANCZOS)
                            bank[cls_name].append(rgb.copy())
            except Exception:
                continue
    return bank


def _draw_background(rng, size=640):
    base_r = rng.randint(35, 175)
    base_g = max(25, min(200, base_r + rng.randint(-18, 18)))
    base_b = max(25, min(210, base_r + rng.randint(-15, 25)))
    arr = np.zeros((size, size, 3), dtype=np.float32)
    y_grad = np.linspace(0.85, 1.15, size, dtype=np.float32)[:, None]
    x_grad = np.linspace(0.92, 1.08, size, dtype=np.float32)[None, :]
    arr[:, :, 0] = base_r * y_grad * x_grad
    arr[:, :, 1] = base_g * y_grad * x_grad
    arr[:, :, 2] = base_b * y_grad * x_grad
    noise = rng.normal(0, rng.uniform(4.0, 11.0), (size, size, 3)).astype(np.float32)
    arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
    img = Image.fromarray(arr, mode='RGB')
    draw = ImageDraw.Draw(img)
    # Background structural pipes / panel seams
    for _ in range(rng.randint(2, 5)):
        if rng.random() < 0.5:
            y = rng.randint(20, size - 20)
            h = rng.randint(4, 16)
            c = tuple(max(10, min(240, base_r + rng.randint(-35, 35))) for _ in range(3))
            draw.rectangle([0, y, size, y + h], fill=c)
        else:
            x = rng.randint(20, size - 20)
            w = rng.randint(4, 16)
            c = tuple(max(10, min(240, base_r + rng.randint(-35, 35))) for _ in range(3))
            draw.rectangle([x, 0, x + w, size], fill=c)
    return img


def _get_crops(real_crops, kind):
    if isinstance(real_crops, dict):
        return real_crops.get(kind) or []
    return real_crops if kind == 'nameplate' and isinstance(real_crops, list) else []


def _draw_nameplate(draw, img, box, rng, real_crops):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    w, h = max(24, x2 - x1), max(18, y2 - y1)
    plates = _get_crops(real_crops, 'nameplate')
    if plates and rng.random() < 0.65:
        src = plates[rng.randint(0, len(plates) - 1)]
        patch = src.resize((w, h), Image.Resampling.BILINEAR)
        if rng.random() < 0.5:
            patch = ImageOps.autocontrast(patch, cutoff=1)
        img.paste(patch, (x1, y1))
        draw.rectangle([x1, y1, x2, y2], outline=(35, 35, 40), width=2)
        return

    style = rng.choice(['dark_anodized', 'brushed_silver', 'industrial_brass', 'blue_header'])
    if style == 'dark_anodized':
        bg, fg, accent = (28, 32, 38), (230, 234, 240), (200, 65, 50)
    elif style == 'brushed_silver':
        bg, fg, accent = (212, 218, 224), (22, 28, 36), (25, 75, 145)
    elif style == 'industrial_brass':
        bg, fg, accent = (195, 168, 98), (30, 24, 15), (140, 35, 25)
    else:
        bg, fg, accent = (228, 232, 238), (20, 26, 34), (18, 62, 130)

    draw.rectangle([x1, y1, x2, y2], fill=bg, outline=(55, 60, 68), width=2)
    draw.rectangle([x1 + 3, y1 + 3, x2 - 3, y2 - 3], outline=fg, width=1)
    # Corner rivets
    for rx, ry in [(x1 + 6, y1 + 6), (x2 - 6, y1 + 6), (x1 + 6, y2 - 6), (x2 - 6, y2 - 6)]:
        draw.ellipse([rx - 2, ry - 2, rx + 2, ry + 2], fill=(120, 125, 132), outline=(40, 40, 45))
    # Header banner
    hdr_h = max(6, int(h * 0.22))
    draw.rectangle([x1 + 5, y1 + 5, x2 - 5, y1 + 5 + hdr_h], fill=accent)
    draw.rectangle([x1 + 9, y1 + 7, x1 + int(w * 0.55), y1 + 3 + hdr_h], fill=(245, 245, 248))
    # Technical rating table rows and cells
    rows = rng.randint(3, 6)
    top_start = y1 + 8 + hdr_h
    avail_h = max(12, y2 - 6 - top_start)
    row_h = max(3, avail_h // (rows + 1))
    for r in range(rows):
        ry = top_start + r * row_h
        if ry + 2 >= y2 - 5:
            break
        draw.line([(x1 + 6, ry), (x2 - 6, ry)], fill=fg, width=1)
        # Simulated text blocks
        cols = rng.randint(2, 4)
        col_w = max(8, (w - 16) // cols)
        for c in range(cols):
            cx = x1 + 8 + c * col_w
            tw = rng.randint(max(4, col_w // 3), max(5, col_w - 4))
            draw.rectangle([cx, ry + 2, min(x2 - 7, cx + tw), min(y2 - 6, ry + max(2, row_h - 2))], fill=fg)


def _draw_motor(draw, img, box, rng, real_crops):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    w, h = x2 - x1, y2 - y1
    motors = _get_crops(real_crops, 'motor')
    if motors and rng.random() < 0.55:
        src = motors[rng.randint(0, len(motors) - 1)]
        patch = src.resize((max(32, w), max(32, h)), Image.Resampling.BILINEAR)
        img.paste(patch, (x1, y1))
        if w >= 120 and h >= 95 and rng.random() < 0.75:
            pw = rng.randint(int(w * 0.25), int(w * 0.42))
            ph = rng.randint(int(h * 0.20), int(h * 0.34))
            px1 = x1 + rng.randint(14, max(15, w - pw - 14))
            py1 = y1 + rng.randint(14, max(15, h - ph - 14))
            plate_box = (px1, py1, px1 + pw, py1 + ph)
            _draw_nameplate(draw, img, plate_box, rng, real_crops)
            return [plate_box]
        return []
    body_color = rng.choice([(42, 78, 118), (52, 88, 72), (68, 74, 84), (35, 95, 135)])
    dark_trim = tuple(max(10, c - 30) for c in body_color)
    light_trim = tuple(min(245, c + 35) for c in body_color)

    # Mounting feet
    foot_h = max(6, int(h * 0.10))
    draw.rectangle([x1 + int(w * 0.12), y2 - foot_h, x2 - int(w * 0.18), y2], fill=dark_trim, outline=(25, 25, 30))
    # Main stator cylinder
    body_x1, body_y1 = x1 + int(w * 0.08), y1 + int(h * 0.14)
    body_x2, body_y2 = x2 - int(w * 0.16), y2 - foot_h
    draw.rounded_rectangle([body_x1, body_y1, body_x2, body_y2], radius=10, fill=body_color, outline=dark_trim, width=3)
    # Fan cowl (left)
    draw.rounded_rectangle([x1, body_y1 + 4, body_x1 + 8, body_y2 - 4], radius=8, fill=dark_trim, outline=(20, 20, 25), width=2)
    # Drive shaft (right)
    shaft_y1 = (body_y1 + body_y2) // 2 - max(4, int(h * 0.07))
    shaft_y2 = (body_y1 + body_y2) // 2 + max(4, int(h * 0.07))
    draw.rectangle([body_x2 - 2, shaft_y1, x2, shaft_y2], fill=(185, 192, 200), outline=(70, 75, 80), width=2)
    # Cooling fins
    fin_count = rng.randint(5, 9)
    for idx in range(fin_count):
        fy = body_y1 + 8 + idx * max(4, (body_y2 - body_y1 - 16) // fin_count)
        draw.line([(body_x1 + 10, fy), (body_x2 - 10, fy)], fill=light_trim, width=2)
    # Top terminal box
    tbox_x1 = body_x1 + int((body_x2 - body_x1) * 0.28)
    tbox_x2 = body_x1 + int((body_x2 - body_x1) * 0.68)
    draw.rectangle([tbox_x1, y1, tbox_x2, body_y1 + 4], fill=dark_trim, outline=(25, 25, 30), width=2)

    # Optional mounted nameplate on motor body
    if w >= 120 and h >= 95 and rng.random() < 0.75:
        pw = rng.randint(int(w * 0.25), int(w * 0.42))
        ph = rng.randint(int(h * 0.20), int(h * 0.34))
        px1 = body_x1 + rng.randint(12, max(13, (body_x2 - body_x1) - pw - 12))
        py1 = body_y1 + rng.randint(10, max(11, (body_y2 - body_y1) - ph - 10))
        plate_box = (px1, py1, px1 + pw, py1 + ph)
        _draw_nameplate(draw, img, plate_box, rng, real_crops)
        return [plate_box]
    return []


def _draw_pump(draw, img, box, rng, real_crops):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    w, h = x2 - x1, y2 - y1
    pumps = _get_crops(real_crops, 'pump')
    if pumps and rng.random() < 0.55:
        src = pumps[rng.randint(0, len(pumps) - 1)]
        patch = src.resize((max(32, w), max(32, h)), Image.Resampling.BILINEAR)
        img.paste(patch, (x1, y1))
        if w >= 120 and h >= 100 and rng.random() < 0.65:
            pw = rng.randint(int(w * 0.24), int(w * 0.38))
            ph = rng.randint(int(h * 0.18), int(h * 0.28))
            px1 = x1 + (w - pw) // 2
            py1 = y1 + max(10, h - ph - 14)
            plate_box = (px1, py1, px1 + pw, py1 + ph)
            _draw_nameplate(draw, img, plate_box, rng, real_crops)
            return [plate_box]
        return []
    pump_color = rng.choice([(25, 110, 165), (38, 128, 98), (165, 65, 45), (55, 85, 140)])
    dark = tuple(max(10, c - 35) for c in pump_color)
    flange_gray = (155, 162, 172)

    # Baseplate
    base_h = max(8, int(h * 0.11))
    draw.rectangle([x1 + int(w * 0.05), y2 - base_h, x2 - int(w * 0.05), y2], fill=(60, 65, 72), outline=(30, 32, 36), width=2)
    # Top discharge neck & flange
    neck_x1 = x1 + int(w * 0.34)
    neck_x2 = x1 + int(w * 0.62)
    draw.rectangle([neck_x1, y1 + 10, neck_x2, y1 + int(h * 0.38)], fill=pump_color, outline=dark, width=2)
    draw.rectangle([neck_x1 - 8, y1, neck_x2 + 8, y1 + 12], fill=flange_gray, outline=(50, 55, 60), width=2)
    # Circular volute casing
    vol_x1, vol_y1 = x1 + int(w * 0.14), y1 + int(h * 0.22)
    vol_x2, vol_y2 = x2 - int(w * 0.14), y2 - base_h + 2
    draw.ellipse([vol_x1, vol_y1, vol_x2, vol_y2], fill=pump_color, outline=dark, width=3)
    # Inner impeller hub ring
    cx, cy = (vol_x1 + vol_x2) // 2, (vol_y1 + vol_y2) // 2
    rad = max(10, min(vol_x2 - vol_x1, vol_y2 - vol_y1) // 4)
    draw.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], fill=flange_gray, outline=dark, width=2)
    # Suction flange (left)
    draw.rectangle([x1, cy - rad, vol_x1 + 8, cy + rad], fill=flange_gray, outline=(45, 50, 55), width=2)

    if w >= 120 and h >= 100 and rng.random() < 0.65:
        pw = rng.randint(int(w * 0.24), int(w * 0.38))
        ph = rng.randint(int(h * 0.18), int(h * 0.28))
        px1 = cx - pw // 2
        py1 = min(y2 - ph - 6, vol_y2 - ph - 8)
        plate_box = (px1, py1, px1 + pw, py1 + ph)
        _draw_nameplate(draw, img, plate_box, rng, real_crops)
        return [plate_box]
    return []


def _draw_valve(draw, img, box, rng, real_crops):
    x1, y1, x2, y2 = [int(round(v)) for v in box]
    w, h = x2 - x1, y2 - y1
    valves = _get_crops(real_crops, 'valve')
    if valves and rng.random() < 0.55:
        src = valves[rng.randint(0, len(valves) - 1)]
        patch = src.resize((max(32, w), max(32, h)), Image.Resampling.BILINEAR)
        img.paste(patch, (x1, y1))
        if w >= 115 and h >= 105 and rng.random() < 0.55:
            pw = rng.randint(int(w * 0.25), int(w * 0.40))
            ph = rng.randint(int(h * 0.16), int(h * 0.24))
            px1 = x1 + (w - pw) // 2
            py1 = y1 + (h - ph) // 2
            plate_box = (px1, py1, px1 + pw, py1 + ph)
            _draw_nameplate(draw, img, plate_box, rng, real_crops)
            return [plate_box]
        return []
    wheel_color = rng.choice([(195, 45, 40), (215, 135, 25), (40, 105, 175)])
    body_metal = rng.choice([(135, 142, 152), (95, 112, 128), (155, 145, 125)])
    dark_metal = tuple(max(20, c - 35) for c in body_metal)

    cx = (x1 + x2) // 2
    body_y1 = y1 + int(h * 0.52)
    body_y2 = y2 - int(h * 0.06)
    # Left and right pipe flanges
    flange_w = max(8, int(w * 0.11))
    draw.rectangle([x1, body_y1 - 6, x1 + flange_w, body_y2 + 6], fill=body_metal, outline=dark_metal, width=2)
    draw.rectangle([x2 - flange_w, body_y1 - 6, x2, body_y2 + 6], fill=body_metal, outline=dark_metal, width=2)
    # Valve globe/gate body
    draw.rectangle([x1 + flange_w, body_y1 + 4, x2 - flange_w, body_y2 - 4], fill=body_metal, outline=dark_metal, width=2)
    draw.ellipse([cx - int(w * 0.22), body_y1 - 2, cx + int(w * 0.22), body_y2 + 2], fill=body_metal, outline=dark_metal, width=3)
    # Stem & yoke bonnet
    stem_w = max(6, int(w * 0.10))
    wheel_h = max(12, int(h * 0.16))
    draw.rectangle([cx - stem_w, y1 + wheel_h, cx + stem_w, body_y1 + 4], fill=dark_metal, outline=(30, 35, 40), width=2)
    # Top handwheel
    draw.ellipse([x1 + int(w * 0.15), y1, x2 - int(w * 0.15), y1 + wheel_h], fill=wheel_color, outline=(35, 20, 20), width=3)

    if w >= 115 and h >= 105 and rng.random() < 0.55:
        pw = rng.randint(int(w * 0.25), int(w * 0.40))
        ph = rng.randint(int(h * 0.16), int(h * 0.24))
        px1 = cx - pw // 2
        py1 = body_y1 + max(4, (body_y2 - body_y1 - ph) // 2)
        plate_box = (px1, py1, px1 + pw, py1 + ph)
        _draw_nameplate(draw, img, plate_box, rng, real_crops)
        return [plate_box]
    return []


def _to_yolo(cls_id, box, size=640):
    x1, y1, x2, y2 = box
    x1, y1 = max(0.0, min(float(size), float(x1))), max(0.0, min(float(size), float(y1)))
    x2, y2 = max(0.0, min(float(size), float(x2))), max(0.0, min(float(size), float(y2)))
    w, h = (x2 - x1) / size, (y2 - y1) / size
    xc, yc = (x1 + x2) / (2.0 * size), (y1 + y2) / (2.0 * size)
    return f'{cls_id} {xc:.6f} {yc:.6f} {w:.6f} {h:.6f}'


def build_dataset(output_dir, train_count=80, val_count=20, test_count=20, size=640, fetch_remote=True):
    import yaml
    out = Path(output_dir).resolve()
    if out.exists():
        shutil.rmtree(out)
    for split in ['train', 'valid', 'test']:
        (out / split / 'images').mkdir(parents=True, exist_ok=True)
        (out / split / 'labels').mkdir(parents=True, exist_ok=True)

    cache_dir = out.parent / '_public_cache'
    real_crops = _fetch_real_plates(cache_dir) if fetch_remote else []

    split_specs = [('train', train_count, 1001), ('valid', val_count, 2002), ('test', test_count, 3003)]
    for split, count, seed in split_specs:
        rng = random.Random(seed)
        np_rng = np.random.default_rng(seed)

        class _CombinedRng:
            def randint(self, a, b): return rng.randint(a, b)
            def uniform(self, a, b): return rng.uniform(a, b)
            def random(self): return rng.random()
            def choice(self, seq): return rng.choice(seq)
            def normal(self, loc, scale, shape): return np_rng.normal(loc, scale, shape)

        crng = _CombinedRng()
        for idx in range(count):
            img = _draw_background(crng, size=size)
            draw = ImageDraw.Draw(img)
            labels = []

            # Keep ~5% intentional negatives
            if idx % 20 == 19:
                pass
            elif idx % 4 == 0:
                # Close-up nameplate scene (1 to 2 plates)
                num_plates = 1 if rng.random() < 0.7 else 2
                slots = [(60, 80, 560, 500)] if num_plates == 1 else [(40, 50, 310, 270), (290, 310, 590, 560)]
                for sx1, sy1, sx2, sy2 in slots:
                    pw = rng.randint(max(120, (sx2 - sx1) // 2), sx2 - sx1)
                    ph = rng.randint(max(80, (sy2 - sy1) // 2), sy2 - sy1)
                    px1 = rng.randint(sx1, max(sx1, sx2 - pw))
                    py1 = rng.randint(sy1, max(sy1, sy2 - ph))
                    pbox = (px1, py1, px1 + pw, py1 + ph)
                    _draw_nameplate(draw, img, pbox, crng, real_crops)
                    labels.append(_to_yolo(0, pbox, size))
            else:
                # Multi-object equipment + nameplate scene (1 or 2 equipment items)
                quadrants = [
                    (35, 45, 315, 315),
                    (325, 45, 605, 315),
                    (35, 325, 315, 595),
                    (325, 325, 605, 595),
                ]
                rng.shuffle(quadrants)
                num_items = 2 if rng.random() < 0.65 else 1
                chosen_quads = quadrants[:num_items] if num_items == 2 else [(70, 70, 570, 570)]
                for q_idx, (qx1, qy1, qx2, qy2) in enumerate(chosen_quads):
                    eq_cls = ((idx + q_idx) % 3) + 1  # 1: pump, 2: valve, 3: motor
                    ew = rng.randint(max(130, int((qx2 - qx1) * 0.62)), qx2 - qx1)
                    eh = rng.randint(max(120, int((qy2 - qy1) * 0.62)), qy2 - qy1)
                    ex1 = rng.randint(qx1, max(qx1, qx2 - ew))
                    ey1 = rng.randint(qy1, max(qy1, qy2 - eh))
                    ebox = (ex1, ey1, ex1 + ew, ey1 + eh)
                    if eq_cls == 1:
                        plates = _draw_pump(draw, img, ebox, crng, real_crops)
                    elif eq_cls == 2:
                        plates = _draw_valve(draw, img, ebox, crng, real_crops)
                    else:
                        plates = _draw_motor(draw, img, ebox, crng, real_crops)
                    labels.append(_to_yolo(eq_cls, ebox, size))
                    for pbox in plates:
                        labels.append(_to_yolo(0, pbox, size))

            if rng.random() < 0.25:
                img = img.filter(ImageFilter.GaussianBlur(radius=rng.uniform(0.3, 0.8)))

            img_path = out / split / 'images' / f'{split}_{idx:04d}.jpg'
            lbl_path = out / split / 'labels' / f'{split}_{idx:04d}.txt'
            img.save(img_path, format='JPEG', quality=94)
            lbl_path.write_text('\n'.join(labels) + ('\n' if labels else ''))

    data_yaml = {
        'path': str(out),
        'train': 'train/images',
        'val': 'valid/images',
        'test': 'test/images',
        'names': {i: name for i, name in enumerate(CLASSES)},
    }
    yaml_path = out / 'data.yaml'
    yaml_path.write_text(yaml.safe_dump(data_yaml, sort_keys=False))
    _, report = inspect_dataset(yaml_path)
    report['real_commons_textures_loaded'] = (
        {k: len(v) for k, v in real_crops.items()} if isinstance(real_crops, dict) else len(real_crops)
    )
    (out / 'dataset_report.json').write_text(json.dumps(report, indent=2))
    return yaml_path, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='/content/dataset', help='Target directory for YOLO dataset')
    parser.add_argument('--train-count', type=int, default=80)
    parser.add_argument('--val-count', type=int, default=20)
    parser.add_argument('--test-count', type=int, default=20)
    parser.add_argument('--no-remote', action='store_true', help='Skip downloading Wikimedia Commons textures')
    args = parser.parse_args()
    yaml_path, report = build_dataset(
        output_dir=args.output,
        train_count=args.train_count,
        val_count=args.val_count,
        test_count=args.test_count,
        fetch_remote=not args.no_remote,
    )
    print(json.dumps(report, indent=2))
    print('Dataset ready at:', yaml_path)


if __name__ == '__main__':
    main()
