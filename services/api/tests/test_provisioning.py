import hashlib
import json
import zipfile

import pytest

from posify.provisioning import install_bundle


def bundle(path, bad_digest=False, extra=None):
    artifact = b'controlled artifact bytes, not executable inference'
    sha = hashlib.sha256(artifact).hexdigest()
    manifest = {'model_id': 'test', 'revision': '1', 'artifact': 'model.onnx',
                'sha256': '0'*64 if bad_digest else sha, 'class_names': ['nameplate']}
    files = {'manifest.json': json.dumps(manifest).encode(), 'model.onnx': artifact,
             'export_report.json': json.dumps({'sha256': sha, 'class_names': ['nameplate']}).encode(),
             'reference_input.npy': b'reference placeholder', 'reference_raw_output.npy': b'reference placeholder'}
    with zipfile.ZipFile(path, 'w') as z:
        for name, content in files.items():
            z.writestr(name, content)
        if extra:
            z.writestr(extra, b'not extracted')


def test_bundle_install_is_atomic_replay_safe_and_refuses_changed_destination(tmp_path):
    path = tmp_path / 'bundle.zip'
    bundle(path)
    destination = tmp_path / 'models/v1'
    manifest = install_bundle(path, destination)
    assert manifest == destination / 'manifest.json'
    assert install_bundle(path, destination) == manifest
    (destination / 'model.onnx').write_bytes(b'changed')
    with pytest.raises(ValueError, match='different content'):
        install_bundle(path, destination)


@pytest.mark.parametrize('extra', ['../escape.txt', 'nested/model.onnx', 'training.pt'])
def test_bundle_rejects_unexpected_members_without_extracting(tmp_path, extra):
    path = tmp_path / 'bundle.zip'
    bundle(path, extra=extra)
    with pytest.raises(ValueError, match='five expected'):
        install_bundle(path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
    assert not (tmp_path / 'escape.txt').exists()


def test_bad_digest_is_rejected_before_provisioning(tmp_path):
    path = tmp_path / 'bundle.zip'
    bundle(path, bad_digest=True)
    with pytest.raises(ValueError, match='digest mismatch'):
        install_bundle(path, tmp_path / 'output')
    assert not (tmp_path / 'output').exists()
