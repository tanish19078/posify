"""Isolated, bounded text extraction; invoked only with operator-approved code."""
import io
import json
import sys
import tempfile
from pathlib import Path

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 100
MAX_TEXT = 30000
MAX_OCR_PAGES = 8
MAX_IMAGE_SIDE = 4096
MAX_IMAGE_PIXELS = 6_000_000


def extract(raw):
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(raw), strict=True)
    if reader.is_encrypted:
        return {'error': 'encrypted_pdf'}
    if len(reader.pages) > MAX_PAGES:
        return {'error': 'pdf_page_limit'}
    pages, empty, total = [], [], 0
    for number, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or '').strip()
        total += len(text)
        if total > MAX_TEXT:
            return {'error': 'pdf_text_limit'}
        if text:
            pages.append({'page_number': number, 'source_text': text})
        else:
            empty.append(number)
    if not pages:
        return {'error': 'pdf_has_no_text'}
    return {'pages': pages, 'page_count': len(reader.pages), 'empty_pages': empty}


def ocr_empty_pages(raw, parsed, ocr, max_ocr_pages=MAX_OCR_PAGES):
    """Run configured local OCR on embedded images of text-empty PDF pages."""
    if ocr is None:
        return parsed
    readiness = getattr(ocr, 'readiness', None)
    if callable(readiness) and not readiness().get('configured'):
        return parsed
    if parsed.get('error') not in {None, 'pdf_has_no_text'}:
        return parsed
    if 'error' not in parsed and not parsed.get('empty_pages'):
        return parsed
    from PIL import Image, ImageOps
    from pypdf import PdfReader
    try:
        reader = PdfReader(io.BytesIO(raw), strict=True)
    except Exception:
        return parsed
    if reader.is_encrypted or len(reader.pages) > MAX_PAGES:
        return parsed
    pages_by_num = {p['page_number']: p['source_text'] for p in parsed.get('pages', [])}
    targets = parsed.get('empty_pages') if 'error' not in parsed else list(range(1, len(reader.pages) + 1))
    with tempfile.TemporaryDirectory(prefix='posify-pdf-ocr-') as temp:
        for page_num in targets[:max_ocr_pages]:
            page = reader.pages[page_num - 1]
            try:
                images = list(page.images)[:4]
            except Exception:
                continue
            recovered = []
            for img_idx, img_obj in enumerate(images):
                data = getattr(img_obj, 'data', None)
                if not data or len(data) > MAX_BYTES:
                    continue
                try:
                    with Image.open(io.BytesIO(data)) as opened:
                        opened.verify()
                    with Image.open(io.BytesIO(data)) as opened:
                        rgb = ImageOps.exif_transpose(opened).convert('RGB')
                        if max(rgb.size) > MAX_IMAGE_SIDE or rgb.width * rgb.height > MAX_IMAGE_PIXELS:
                            continue
                        img_path = Path(temp) / f'p{page_num}_{img_idx}.png'
                        rgb.save(img_path, format='PNG')
                except Exception:
                    continue
                lines = ocr.recognize(img_path)
                recovered.extend(line.text.strip() for line in lines if line.text.strip())
            if recovered:
                pages_by_num[page_num] = '\n'.join(recovered)
    if not pages_by_num:
        return {'error': 'pdf_has_no_text'}
    pages = [{'page_number': n, 'source_text': pages_by_num[n]} for n in sorted(pages_by_num)]
    if sum(len(p['source_text']) for p in pages) > MAX_TEXT:
        return {'error': 'pdf_text_limit'}
    empty = [n for n in range(1, len(reader.pages) + 1) if n not in pages_by_num]
    return {'pages': pages, 'page_count': len(reader.pages), 'empty_pages': empty}


def main():
    try:
        import resource
    except ImportError:
        print(json.dumps({'error': 'resource_limits_unavailable'}))
        return
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (5, 5))
    try:
        raw = sys.stdin.buffer.read(MAX_BYTES + 1)
        result = {'error': 'pdf_byte_limit'} if len(raw) > MAX_BYTES else extract(raw)
    except Exception:
        result = {'error': 'invalid_pdf'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
