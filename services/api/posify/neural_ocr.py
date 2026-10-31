"""Explicit offline provisioning for the pinned PP-OCRv6 CPU reader."""
import hashlib
import importlib.util
import json
import os
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path

MODELS = {
    'PP-OCRv6_det_small.onnx':'090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f',
    'PP-OCRv6_rec_small.onnx':'6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884',
    'ch_ppocr_mobile_v2.0_cls_mobile.onnx':'e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c',
}


def verified_models(directory):
    root=Path(directory)
    if not directory or not root.is_dir(): raise ValueError('Provision the local PP-OCRv6 model directory')
    paths={}
    for name,digest in MODELS.items():
        path=root/name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise ValueError('OCR artifact missing or digest mismatch')
        paths[name]=str(path.resolve())
    return paths


def install_models(destination):
    if version('rapidocr')!='3.10.0': raise ValueError('Install the pinned rapidocr==3.10.0 package')
    package=Path(importlib.util.find_spec('rapidocr').origin).parent
    source=verified_models(str(package/'models'))
    root=Path(destination)
    if root.exists():
        verified_models(str(root));return root
    root.parent.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.ocr-provision-',dir=root.parent))
    try:
        for name,path in source.items(): shutil.copyfile(path,staging/name)
        (staging/'reader.json').write_text(json.dumps({'runtime':'rapidocr==3.10.0','models':MODELS,
            'source':'Models bundled in the pinned RapidAI/RapidOCR PyPI release',
            'license':'Apache-2.0; retain upstream license and model notices'},indent=2)+'\n')
        os.rename(staging,root)
    finally:
        if staging.exists(): shutil.rmtree(staging)
    return root


def create_reader(directory):
    paths=verified_models(directory)
    if version('rapidocr')!='3.10.0': raise ValueError('Unsupported OCR runtime version')
    from rapidocr import RapidOCR
    return RapidOCR(params={
        'Det.model_path':paths['PP-OCRv6_det_small.onnx'],
        'Rec.model_path':paths['PP-OCRv6_rec_small.onnx'],
        'Cls.model_path':paths['ch_ppocr_mobile_v2.0_cls_mobile.onnx'],
        'Global.model_root_dir':str(Path(directory).resolve()),
        'Global.text_score':.1,'Global.log_level':'error',
        'EngineConfig.onnxruntime.intra_op_num_threads':1,
        'EngineConfig.onnxruntime.inter_op_num_threads':1,
        'EngineConfig.onnxruntime.use_cuda':False,
    })
