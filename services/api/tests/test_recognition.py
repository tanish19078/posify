import numpy as np
import pytest
from fastapi import HTTPException
from PIL import Image

from posify.ocr import OCRLine, OCRWord, parse_tsv, LocalOCR
from posify.plate_reader import map_box, prepare, read_plate
from posify.recognition import ReadingAttempt, catalogue_candidates, extract_fields
from posify.recognition_evaluation import field_metrics
from posify.matching import extract_identifiers
from test_api import client


def test_tsv_literal_quotes_do_not_swallow_following_rows():
    header='level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n'
    payload=header+'5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t80\t"\n'+'5\t1\t1\t1\t2\t1\t10\t20\t60\t12\t95\tSIEMENS\n'
    lines=parse_tsv(payload)
    assert len(lines)==2 and lines[1].text=='SIEMENS'
    assert '\t' not in lines[0].text and lines[1].words[0].confidence==.95


def test_recorded_web_recognition_fixture_matches_the_api_contract():
    from pathlib import Path
    from posify.schemas import CaptureAnalysis
    path=Path(__file__).resolve().parents[3]/'apps/web/src/demoRecognition.json'
    fixture=CaptureAnalysis.model_validate_json(path.read_text())
    assert fixture.recognition_version=='plate-evidence-v1'
    assert fixture.requires_confirmation
    assert all(candidate.requires_review for candidate in fixture.equipment_candidates)


def test_neural_reader_is_explicit_digest_checked_and_offline(tmp_path,monkeypatch):
    pytest.importorskip('rapidocr')
    import requests
    from posify.neural_ocr import install_models, verified_models
    root=install_models(tmp_path/'ocr')
    monkeypatch.setenv('POSIFY_OCR_ENGINE','rapidocr')
    monkeypatch.setenv('POSIFY_RAPIDOCR_MODEL_DIR',str(root))
    def no_network(*args,**kwargs): raise AssertionError('OCR must not download during inference')
    monkeypatch.setattr(requests.sessions.Session,'request',no_network)
    from pathlib import Path
    image=Path(__file__).resolve().parents[3]/'apps/web/public/images/machine.jpg'
    lines=LocalOCR().recognize(image)
    assert lines and all(0<=line.confidence<=1 and line.box for line in lines)
    with (root/'PP-OCRv6_rec_small.onnx').open('r+b') as artifact: artifact.write(b'changed')
    with pytest.raises(ValueError,match='digest'): verified_models(str(root))


def attempt(lines, name='first', region=0):
    return ReadingAttempt(id=name,region_index=region,method='fixture',rotation=0,psm=6,
        selected=True,lines=[OCRLine(text=line,confidence=.96,box=(10,20,200,40)) for line in lines])


def model(c, code='AB-123', variant='base', publish=True):
    row=c.post('/v1/catalog/models',json={'manufacturer':'ACME','model':code,'variant':variant,
        'category':'Fixture motor','source_ref':'Synthetic evaluation fixture'}).json()
    if publish: c.post('/v1/catalog/models/'+row['id']+'/publish').raise_for_status()
    return row


def test_value_confidence_and_source_are_local_to_supporting_words():
    reading=attempt([])
    reading.lines=[OCRLine(text='junk SIEMENS',confidence=.01,box=(0,0,200,50),words=[
        OCRWord(text='junk',confidence=.01,box=(0,0,40,20)),
        OCRWord(text='SIEMENS',confidence=.96,box=(60,0,180,30))])]
    fields=extract_fields([reading],['SIEMENS'])
    manufacturer=next(field for field in fields if field.field=='manufacturer')
    assert manufacturer.status=='observed' and manufacturer.ocr_confidence==.96
    assert manufacturer.box==(60,0,180,30)
    reading.lines[0].words[1].confidence=.12
    assert extract_fields([reading],['SIEMENS'])[0].status=='low_confidence'


def test_structured_values_preserve_labels_units_and_identifier_characters():
    fields=extract_fields([attempt(['Manufacturer: ACME','Model: 1 HU3054-0AC01-Z',
        'Serial: E782 4058 01 001','Voltage: 230/400 V','Power: 0.37 kW','Speed: 2730 RPM','Frequency: 50 Hz'])],['ACME'])
    values={(f.field,f.value,f.unit) for f in fields}
    assert ('model','1 HU3054-0AC01-Z',None) in values
    assert ('serial','E782 4058 01 001',None) in values
    assert ('voltage','230/400','V') in values
    assert ('power','0.37','kW') in values
    assert ('speed','2730','RPM') in values
    assert ('frequency','50','Hz') in values
    assert extract_identifiers([OCRLine(text='Serial: E782 4058',confidence=.99)])==[]


def test_exact_catalogue_support_does_not_assign_a_factory_asset(client):
    item=model(client)
    fields=extract_fields([attempt(['ACME','Model: AB-123'])],['ACME'])
    with client.app.state.database.connect() as db:
        candidates,status,_=catalogue_candidates(db,fields)
        assert status=='supported_model_candidate'
        assert str(candidates[0].catalog_model_id)==item['id']
        assert candidates[0].requires_review
        assert db.execute('SELECT COUNT(*) AS n FROM capture_assignments').fetchone()['n']==0


@pytest.mark.parametrize('other',['AB-12S','AB123'])
def test_near_codes_and_punctuation_are_not_silently_corrected(client,other):
    model(client)
    fields=extract_fields([attempt(['ACME','Model: '+other])],['ACME'])
    with client.app.state.database.connect() as db:
        candidates,status,_=catalogue_candidates(db,fields)
    assert candidates and status!='supported_model_candidate'
    assert candidates[0].status=='conflicting_evidence'
    assert 'model' in candidates[0].conflicting_fields


def test_conflicting_readings_and_variants_abstain(client):
    model(client)
    model(client,variant='alternate')
    fields=extract_fields([attempt(['ACME','Model: AB-123'])],['ACME'])
    with client.app.state.database.connect() as db:
        candidates,status,_=catalogue_candidates(db,fields)
    assert len(candidates)==2 and status=='ambiguous_model_candidates'
    fields=extract_fields([attempt(['ACME','Model: AB-123']),attempt(['ACME','Model: AB-125'],'second')],['ACME'])
    assert all(f.status=='conflicting' for f in fields if f.field=='model')
    with client.app.state.database.connect() as db:
        assert catalogue_candidates(db,fields)[1]=='conflicting_evidence'


def test_unpublished_models_and_cross_plate_field_combinations_are_rejected(client):
    model(client,publish=False)
    fields=extract_fields([attempt(['ACME','Model: AB-123'])],['ACME'])
    with client.app.state.database.connect() as db:
        assert catalogue_candidates(db,fields)[0]==[]
    client.post('/v1/catalog/models/'+client.get('/v1/catalog/models?include_drafts=true').json()[0]['id']+'/publish').raise_for_status()
    fields=extract_fields([attempt(['ACME'],region=0),attempt(['Model: AB-123'],'second',region=1)],['ACME'])
    with client.app.state.database.connect() as db:
        candidates,status,_=catalogue_candidates(db,fields)
    assert status=='multiple_nameplates'
    assert not any(c.status=='evidence_supported' for c in candidates)


def test_rotation_padding_and_scale_map_back_to_original_pixels():
    image=Image.new('RGB',(100,60),'white')
    _,transform=prepare(image,np.eye(3),90)
    original=np.array([[10,20,1],[50,20,1],[50,40,1],[10,40,1]]).T
    projected=transform@original
    rect=(projected[0].min(),projected[1].min(),projected[0].max(),projected[1].max())
    assert map_box(rect,np.linalg.inv(transform),image.size)==(10,20,50,40)
    assert map_box(None,np.eye(3),image.size) is None


def test_failed_alternative_is_bounded_and_original_evidence_survives(tmp_path):
    image=tmp_path/'plate.png';Image.new('RGB',(200,80),'white').save(image)
    class Reader:
        engine='tesseract'
        def __init__(self): self.calls=0
        def recognize_variant(self,path,psm,timeout):
            self.calls+=1
            if self.calls>1: raise HTTPException(503,'private runtime detail')
            return [OCRLine(text='Model: AB-123',confidence=.96,box=(10,10,160,30))]
    reader=Reader();lines,reads,warnings=read_plate(reader,image,max_attempts=2)
    assert reader.calls==2 and len(reads)==2
    assert lines[0].text=='Model: AB-123' and reads[0].selected
    assert 'alternative_reading_failed' in warnings
    assert 'private runtime detail' not in str([r.model_dump() for r in reads])


def test_labelled_metrics_penalize_wrong_values_and_count_abstention():
    cases=[{'expected_fields':{'model':'AB-123'},'predicted_fields':[{'field':'model','value':'AB-125','status':'observed'}]},
           {'expected_fields':{'model':'AB-123'},'predicted_fields':[]},
           {'expected_fields':{'model':'AB-123'},'predicted_fields':[{'field':'model','value':'AB-123','status':'observed'}]}]
    metrics=field_metrics(cases)
    assert metrics['precision']==.5 and metrics['recall']==pytest.approx(1/3)
    assert metrics['coverage']==pytest.approx(2/3)
