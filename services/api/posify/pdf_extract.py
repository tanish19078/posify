"""Isolated, bounded text extraction; invoked only with operator-approved code."""
import io
import json
import sys

MAX_BYTES = 8 * 1024 * 1024
MAX_PAGES = 100
MAX_TEXT = 30000


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
