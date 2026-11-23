"""Export static FP32 raw YOLO11 ONNX plus the manifest required by posify."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--weights', required=True)
    parser.add_argument('--output', default='/content/backend_export')
    parser.add_argument('--model-id', default='nameplate-detector')
    parser.add_argument('--revision', default='v1')
    parser.add_argument('--imgsz', type=int, default=640)
    parser.add_argument('--reference-image')
    args = parser.parse_args()
    if args.imgsz < 32 or args.imgsz > 2048 or args.imgsz % 32:
        parser.error('Image size must be a multiple of 32 between 32 and 2048')
    out = Path(args.output).resolve()
    if out.exists() and any(out.iterdir()): parser.error('Output directory must be empty')
    out.mkdir(parents=True, exist_ok=True)
    import numpy as np
    import onnx
    import onnxruntime as ort
    from PIL import Image
    from ultralytics import YOLO
    import ultralytics
    model = YOLO(args.weights)
    if model.task != 'detect': parser.error('Only detection checkpoints are supported')
    names = model.names
    classes = [names[i] for i in range(len(names))] if isinstance(names,dict) else list(names)
    exported = Path(model.export(format='onnx', imgsz=args.imgsz, batch=1, dynamic=False,
                                  half=False, simplify=False, nms=False, opset=17, device='cpu'))
    # Consolidate external tensor data into a single portable ONNX file.
    graph = onnx.load(str(exported), load_external_data=True)
    onnx.checker.check_model(graph)
    artifact = out/'model.onnx'
    onnx.save_model(graph, str(artifact), save_as_external_data=False)
    session = ort.InferenceSession(str(artifact), providers=['CPUExecutionProvider'])
    inputs, outputs = session.get_inputs(), session.get_outputs()
    expected = [1,3,args.imgsz,args.imgsz]
    if len(inputs) != 1 or inputs[0].shape != expected or inputs[0].type != 'tensor(float)' or len(outputs) != 1:
        raise RuntimeError('Export does not match the backend static float32 input/output contract')
    if args.reference_image:
        with Image.open(args.reference_image) as source:
            image=source.convert('RGB'); w,h=image.size; ratio=min(args.imgsz/w,args.imgsz/h)
            nw,nh=round(w*ratio),round(h*ratio)
            canvas=Image.new('RGB',(args.imgsz,args.imgsz),(114,114,114))
            canvas.paste(image.resize((nw,nh),Image.Resampling.BILINEAR),((args.imgsz-nw)//2,(args.imgsz-nh)//2))
            tensor=np.ascontiguousarray(np.asarray(canvas,dtype=np.float32).transpose(2,0,1)[None]/255.)
    else:
        tensor=np.zeros(expected,dtype=np.float32)
    prediction=session.run(None,{inputs[0].name:tensor})[0]
    if prediction.ndim != 3 or prediction.shape[:2] != (1,4+len(classes)):
        raise RuntimeError(f'Unsupported output shape: {prediction.shape}; expected [1,4+C,N] without embedded NMS')
    if not np.isfinite(prediction).all() or np.any(prediction[:,4:,:] < 0) or np.any(prediction[:,4:,:] > 1):
        raise RuntimeError('Export produced invalid coordinates or class probabilities')
    digest=hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest={'model_id':args.model_id,'revision':args.revision,'artifact':'model.onnx','sha256':digest,
              'format':'onnx','output_layout':'yolo11_raw_xywh_class_scores','input_size':[args.imgsz,args.imgsz],
              'class_names':classes,'confidence_threshold':.4,'iou_threshold':.5}
    (out/'manifest.json').write_text(json.dumps(manifest,indent=2))
    np.save(out/'reference_input.npy',tensor)
    np.save(out/'reference_raw_output.npy',prediction)
    (out/'export_report.json').write_text(json.dumps({'ultralytics':ultralytics.__version__,
        'input_shape':expected,'output_shape':list(prediction.shape),'class_names':classes,
        'sha256':digest,'reference':'supplied_image' if args.reference_image else 'zeros_conformance_only'},indent=2))
    archive=shutil.make_archive(str(out),'zip',root_dir=out)
    print('Backend artifact bundle:',archive)
    print('No accuracy claim is made by a successful ONNX conformance check.')


if __name__ == '__main__': main()
