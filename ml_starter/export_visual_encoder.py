"""Export a pretrained vision backbone to a static FP32 ONNX embedding bundle for Posify.

Run in Google Colab (or a PyTorch environment with torchvision, onnx, onnxruntime):
  python export_visual_encoder.py --backbone mobilenet_v3_small --output /content/vision_export --revision v1
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


BACKBONES = ('mobilenet_v3_small', 'mobilenet_v3_large', 'resnet18')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backbone', choices=BACKBONES, default='mobilenet_v3_small')
    parser.add_argument('--output', default='/content/vision_embedder_export')
    parser.add_argument('--model-id', default='equipment-vision-embedder')
    parser.add_argument('--revision', default='v1')
    parser.add_argument('--imgsz', type=int, default=224)
    args = parser.parse_args()
    if not 32 <= args.imgsz <= 1024:
        parser.error('imgsz must be between 32 and 1024')
    out = Path(args.output).resolve()
    if out.exists() and any(out.iterdir()):
        parser.error('Output directory must be empty')
    out.mkdir(parents=True, exist_ok=True)

    import numpy as np
    import onnx
    import onnxruntime as ort
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import torchvision.models as models

    class NormalizedBackbone(nn.Module):
        def __init__(self, name):
            super().__init__()
            if name == 'mobilenet_v3_small':
                base = models.mobilenet_v3_small(weights=models.MobileNet_V3_Small_Weights.DEFAULT)
                self.features = base.features
                self.pool = base.avgpool
            elif name == 'mobilenet_v3_large':
                base = models.mobilenet_v3_large(weights=models.MobileNet_V3_Large_Weights.DEFAULT)
                self.features = base.features
                self.pool = base.avgpool
            else:
                base = models.resnet18(weights=models.ResNet18_Weights.DEFAULT)
                self.features = nn.Sequential(*list(base.children())[:-2])
                self.pool = base.avgpool

        def forward(self, x):
            feat = self.pool(self.features(x)).flatten(1)
            return F.normalize(feat, p=2, dim=1)

    module = NormalizedBackbone(args.backbone).eval()
    sample = torch.zeros(1, 3, args.imgsz, args.imgsz, dtype=torch.float32)
    artifact = out / 'model.onnx'
    torch.onnx.export(
        module,
        sample,
        str(artifact),
        input_names=['image'],
        output_names=['embedding'],
        opset_version=17,
        do_constant_folding=True,
        dynamic_axes=None,
    )
    graph = onnx.load(str(artifact), load_external_data=True)
    onnx.checker.check_model(graph)
    onnx.save_model(graph, str(artifact), save_as_external_data=False)

    session = ort.InferenceSession(str(artifact), providers=['CPUExecutionProvider'])
    ref_in = np.zeros((1, 3, args.imgsz, args.imgsz), dtype=np.float32)
    ref_out = session.run(None, {session.get_inputs()[0].name: ref_in})[0]
    if ref_out.ndim != 2 or ref_out.shape[0] != 1 or not np.isfinite(ref_out).all():
        raise RuntimeError(f'Unexpected embedding output shape: {ref_out.shape}')
    dim = int(ref_out.shape[1])
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = {
        'model_id': args.model_id,
        'revision': args.revision,
        'artifact': 'model.onnx',
        'sha256': digest,
        'format': 'onnx',
        'input_size': [args.imgsz, args.imgsz],
        'embedding_dim': dim,
        'mean': [0.485, 0.456, 0.406],
        'std': [0.229, 0.224, 0.225],
        'min_similarity': 0.72,
    }
    (out / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    np.save(out / 'reference_input.npy', ref_in)
    np.save(out / 'reference_output.npy', ref_out)
    (out / 'export_report.json').write_text(json.dumps({
        'backbone': args.backbone,
        'input_shape': [1, 3, args.imgsz, args.imgsz],
        'output_shape': [1, dim],
        'sha256': digest,
    }, indent=2))
    archive = shutil.make_archive(str(out), 'zip', root_dir=out)
    print('Visual embedder bundle:', archive)


if __name__ == '__main__':
    main()
