"""Reviewable local model bundle provisioning; no API uploads or executable PT loads."""
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from posify.detector import DetectorManifest

FILES = {'manifest.json', 'model.onnx', 'export_report.json', 'reference_input.npy', 'reference_raw_output.npy'}


def install_bundle(bundle, destination):
    destination = Path(destination)
    with zipfile.ZipFile(bundle) as archive:
        members = archive.infolist()
        if len(members) != len(FILES) or {member.filename for member in members} != FILES:
            raise ValueError('Bundle must contain exactly the five expected root-level export files')
        if sum(member.file_size for member in members) > 64 * 1024 * 1024:
            raise ValueError('Bundle exceeds the 64 MiB uncompressed limit')
        payloads = {name: archive.read(name) for name in FILES}
    manifest = DetectorManifest.model_validate_json(payloads['manifest.json'])
    if manifest.artifact != 'model.onnx':
        raise ValueError('Export bundle manifest must reference model.onnx')
    if hashlib.sha256(payloads['model.onnx']).hexdigest() != manifest.sha256.lower():
        raise ValueError('Model digest mismatch')
    report = json.loads(payloads['export_report.json'])
    if report.get('sha256') != manifest.sha256 or report.get('class_names') != manifest.class_names:
        raise ValueError('Export report does not match the manifest')
    if destination.exists():
        if destination.is_dir() and all((destination / name).is_file() and
              hashlib.sha256((destination / name).read_bytes()).digest() == hashlib.sha256(data).digest()
              for name, data in payloads.items()):
            return destination / 'manifest.json'
        raise ValueError('Destination exists with different content; use a new revision directory')
    destination.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix='.provision-', dir=destination.parent))
    try:
        for name, data in payloads.items():
            (staging / name).write_bytes(data)
        os.rename(staging, destination)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return destination / 'manifest.json'
