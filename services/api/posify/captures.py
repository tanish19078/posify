"""Bounded image decoding and content-addressed, metadata-free image storage."""
import hashlib
import io
import os
import tempfile
import warnings
from pathlib import Path

from fastapi import HTTPException
from PIL import Image, ImageOps, ImageStat, UnidentifiedImageError

MAX_UPLOAD = 8 * 1024 * 1024
MAX_PIXELS = 6_000_000
MAX_SIDE = 4096


def sanitize_image(raw: bytes, content_type: str):
    if content_type not in {'image/png', 'image/jpeg'}:
        raise HTTPException(415, 'Send raw image/png or image/jpeg bytes')
    if not raw or len(raw) > MAX_UPLOAD:
        raise HTTPException(413, 'Image must be between 1 byte and 8 MiB')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as source:
                expected = {'image/png': 'PNG', 'image/jpeg': 'JPEG'}[content_type]
                if source.format != expected:
                    raise HTTPException(415, 'Image encoding does not match Content-Type')
                w, h = source.size
                if w * h > MAX_PIXELS or max(w, h) > MAX_SIDE:
                    raise HTTPException(413, 'Image exceeds 6 megapixels or 4096 pixels per side')
                source.load()
                oriented = ImageOps.exif_transpose(source).convert('RGB')
                # A new image discards EXIF, comments, profiles and all source metadata.
                clean = Image.new('RGB', oriented.size)
                clean.paste(oriented)
                w, h = clean.size
                flags = []
                if min(w, h) < 320:
                    flags.append('small_image')
                if ImageStat.Stat(clean.convert('L')).stddev[0] < 10:
                    flags.append('low_contrast')
                output = io.BytesIO()
                clean.save(output, format='PNG')
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise HTTPException(422, 'Image could not be decoded safely')
    payload = output.getvalue()
    if len(payload) > 20 * 1024 * 1024:
        raise HTTPException(413, 'Decoded image is too large')
    return payload, w, h, flags


def persist_image(root: Path, data: bytes):
    digest = hashlib.sha256(data).hexdigest()
    root.mkdir(parents=True, exist_ok=True)
    target = root / (digest + '.png')
    if not target.exists():
        fd, temp_name = tempfile.mkstemp(dir=root, prefix='.capture-')
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.replace(temp_name, target)
            except OSError:
                # Another writer may have installed this immutable digest first.
                if not target.is_file():
                    raise
        finally:
            Path(temp_name).unlink(missing_ok=True)
    return digest


def capture_row(row):
    import json
    data = dict(row)
    data['warnings'] = json.loads(data['warnings'])
    return data
