"""Evaluate local reading against explicit labels; never downloads or trains a model."""
import argparse
import hashlib
import io
import json
import os
import tempfile
import time
from pathlib import Path
from uuid import uuid4

from fastapi.testclient import TestClient
from PIL import Image, ImageOps

from posify.app import create_app
from posify.jobs import work_once
from posify.ocr import LocalOCR
from posify.recognition import ReadingAttempt, extract_fields
from posify.recognition_evaluation import field_metrics


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cases',required=True,type=Path)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--output',type=Path,default=Path('var/recognition-evaluation.json'))
    parser.add_argument('--reader',choices=['tesseract','rapidocr'],default='tesseract')
    parser.add_argument('--ocr-model-dir',type=Path)
    args=parser.parse_args()
    packet=json.loads(args.cases.read_text())
    if not 1<=len(packet['cases'])<=200: parser.error('Supply 1–200 explicitly labelled cases')
    os.environ['POSIFY_DETECTOR_MANIFEST']=str(args.manifest.resolve())
    os.environ['POSIFY_OCR_ENGINE']=args.reader
    if args.ocr_model_dir: os.environ['POSIFY_RAPIDOCR_MODEL_DIR']=str(args.ocr_model_dir.resolve())
    os.environ['POSIFY_AUTH_MODE']='development'
    os.environ['POSIFY_AUTO_MIGRATE']='true'
    results=[]
    with tempfile.TemporaryDirectory(prefix='posify-recognition-eval-') as temporary:
        os.environ['POSIFY_CAPTURE_DIR']=temporary+'/captures'
        os.environ['POSIFY_DOCUMENT_DIR']=temporary+'/documents'
        app=create_app(temporary+'/evaluation.db','isolated-recognition-evaluation')
        baseline_ocr=LocalOCR();baseline_ocr.engine='tesseract'
        with TestClient(app,headers={'X-API-Key':'isolated-recognition-evaluation'}) as client:
            def call(method,path,**kwargs):
                response=client.request(method,path,**kwargs);response.raise_for_status();return response.json()
            org=call('POST','/v1/organizations',json={'name':'Isolated evaluation fixtures'})
            call('POST','/v1/factories',json={'id':'evaluation','name':'Evaluation fixture','organization_id':org['id']})
            for model in packet.get('catalogue',[]):
                item=call('POST','/v1/catalog/models',json=model)
                call('POST',f"/v1/catalog/models/{item['id']}/publish")
            brands=sorted({item['manufacturer'] for item in packet.get('catalogue',[])})
            for case in packet['cases']:
                path=(args.cases.resolve().parent/case['image']).resolve()
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                if case.get('sha256') and digest!=case['sha256']: raise ValueError('Evaluation image digest mismatch: '+case['id'])
                with Image.open(path) as original:
                    direct=original.format in {'PNG','JPEG'} and path.stat().st_size<=8*1024*1024 and max(original.size)<=4096 and original.width*original.height<=6_000_000
                    media='image/png' if original.format=='PNG' else 'image/jpeg'
                    image=ImageOps.exif_transpose(original).convert('RGB');image.thumbnail((2400,2400),Image.Resampling.LANCZOS)
                buffer=io.BytesIO();image.save(buffer,format='JPEG',quality=95)
                capture=call('POST','/v1/sites/evaluation/captures',content=path.read_bytes() if direct else buffer.getvalue(),headers={'Content-Type':media if direct else 'image/jpeg'})['capture']
                with Image.open(app.state.capture_root/(capture['sha256']+'.png')) as uploaded:
                    image=uploaded.copy()
                job=call('POST',f"/v1/sites/evaluation/captures/{capture['id']}/jobs",json={'id':str(uuid4()),'mode':'detect_ocr'})
                start=time.perf_counter();work_once(app);elapsed=time.perf_counter()-start
                result=call('GET','/v1/sites/evaluation/jobs/'+job['id'])
                if result['status']!='succeeded': raise RuntimeError('Evaluation component failed: '+str(result['error_code']))
                analysis=result['result']
                baseline=[];baseline_lines=[]
                start=time.perf_counter()
                for region,detection in enumerate(analysis['detections'][:8]):
                    box=detection['box'];crop=Path(temporary)/'baseline.png'
                    image.crop((int(box[0]),int(box[1]),int(box[2]+.999),int(box[3]+.999))).save(crop)
                    lines=baseline_ocr.recognize(crop)
                    def offset(rect):
                        return None if rect is None else (rect[0]+int(box[0]),rect[1]+int(box[1]),rect[2]+int(box[0]),rect[3]+int(box[1]))
                    lines=[line.model_copy(update={'box':offset(line.box),'words':[word.model_copy(update={'box':offset(word.box)}) for word in line.words]}) for line in lines]
                    baseline_lines.extend(line.model_dump() for line in lines)
                    baseline.append(ReadingAttempt(id=f'baseline-{region}',region_index=region,method='original_psm6',rotation=0,psm=6,selected=True,lines=lines))
                if not baseline:
                    full=Path(temporary)/'baseline.png';image.save(full)
                    lines=baseline_ocr.recognize(full);baseline_lines=[line.model_dump() for line in lines]
                    baseline=[ReadingAttempt(id='baseline-full',region_index=0,method='original_psm6',rotation=0,psm=6,selected=True,lines=lines)]
                baseline_seconds=time.perf_counter()-start
                baseline_fields=[field.model_dump() for field in extract_fields(baseline,brands)]
                results.append({'id':case['id'],'source_sha256':digest,'expected_fields':case['expected_fields'],
                    'predicted_fields':analysis['equipment_fields'],'baseline_fields':baseline_fields,
                    'baseline_raw_lines':baseline_lines,'analysis':analysis,'pipeline_seconds':round(elapsed,3),
                    'baseline_ocr_seconds':round(baseline_seconds,3)})
        app.state.database.engine.dispose()
    report={'reader':args.reader,'split':packet.get('split','unspecified'),'training_overlap':packet.get('training_overlap','unknown'),
        'notice':'Metrics use the supplied labels only. A smoke set with unknown training overlap is not an independent accuracy benchmark. Pipeline and baseline timings cover different work.',
        'pipeline':field_metrics(results),'baseline':field_metrics([{**case,'predicted_fields':case['baseline_fields']} for case in results]),'cases':results}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps({key:report[key] for key in ['split','training_overlap','pipeline','baseline']},indent=2))
    print('Evidence report:',args.output)


if __name__=='__main__': main()
