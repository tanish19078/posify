"""Bounded alternative OCR views with inverse mapping to the uploaded image.

Geometry is an optional, reviewable proposal. Original readings remain available.
The quality heuristic chooses a reading layout; it is not an accuracy metric.
"""
import importlib.util
import hashlib
import math
import re
import tempfile
import time
from pathlib import Path

import numpy as np
from fastapi import HTTPException
from PIL import Image, ImageFilter, ImageOps

from posify.ocr import OCRLine
from posify.recognition import ReadingAttempt


def map_box(box, inverse, size):
    if box is None:
        return None
    x1,y1,x2,y2 = box
    points = np.array([[x1,y1,1],[x2,y1,1],[x2,y2,1],[x1,y2,1]], dtype=float).T
    mapped = inverse @ points
    if not np.isfinite(mapped).all() or np.any(np.abs(mapped[2]) < 1e-9):
        return None
    mapped = mapped[:2] / mapped[2]
    return (max(0, min(size[0], math.floor(mapped[0].min()))),
            max(0, min(size[1], math.floor(mapped[1].min()))),
            max(0, min(size[0], math.ceil(mapped[0].max()))),
            max(0, min(size[1], math.ceil(mapped[1].max()))))


def mapped_line(line, inverse, size):
    return line.model_copy(update={'box':map_box(line.box,inverse,size),
        'words':[word.model_copy(update={'box':map_box(word.box,inverse,size)}) for word in line.words[:100]]})


def quality(lines):
    words = [(word.text,word.confidence) for line in lines for word in line.words]
    if not words: words = [(line.text,line.confidence) for line in lines]
    useful = [(text,conf) for text,conf in words if sum(c.isalnum() for c in text)>=2]
    if not useful: return 0.
    weight = sum(min(len(text),24) for text,_ in useful)
    mean = sum(min(len(text),24)*conf for text,conf in useful) / weight
    density = min(1., sum(sum(c.isalnum() for c in text) for text,_ in useful)/80)
    return round(mean * (.35+.65*density), 6)


def rectify(image):
    """Propose one large convex plate boundary; never remove the original view."""
    if min(image.size)<32 or not importlib.util.find_spec('cv2'):
        return None
    import cv2
    cv2.setNumThreads(1)
    original = np.asarray(image.convert('RGB'))
    scale = min(1.,1000/max(image.size))
    small = cv2.resize(original,None,fx=scale,fy=scale)
    gray = cv2.cvtColor(small,cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(cv2.GaussianBlur(gray,(5,5),0),40,140)
    contours,_ = cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    for contour in sorted(contours,key=cv2.contourArea,reverse=True)[:24]:
        points=cv2.approxPolyDP(contour,.025*cv2.arcLength(contour,True),True)
        if len(points)!=4 or not cv2.isContourConvex(points): continue
        if cv2.contourArea(points) < .40*small.shape[0]*small.shape[1]: continue
        points=points[:,0,:].astype(np.float32)/scale
        center=points.mean(axis=0)
        points=points[np.argsort(np.arctan2(points[:,1]-center[1],points[:,0]-center[0]))]
        points=np.roll(points,-np.argmin(points.sum(axis=1)),axis=0)
        a,b,c,d=points
        width=max(np.linalg.norm(b-a),np.linalg.norm(c-d))
        height=max(np.linalg.norm(d-a),np.linalg.norm(c-b))
        if min(width,height)<32 or not .15<width/height<9: continue
        factor=min(1.,1800/max(width,height))
        w,h=max(32,round(width*factor)),max(32,round(height*factor))
        target=np.array([[0,0],[w-1,0],[w-1,h-1],[0,h-1]],np.float32)
        matrix=cv2.getPerspectiveTransform(points,target)
        if not np.isfinite(matrix).all() or abs(np.linalg.det(matrix))<1e-9: continue
        result=cv2.warpPerspective(original,matrix,(w,h),borderValue=(255,255,255))
        return Image.fromarray(result),matrix,[tuple(map(float,p)) for p in points]
    return None


def prepare(image, matrix, angle=0, contrast=False):
    image=image.convert('L')
    if contrast:
        image=ImageOps.autocontrast(image,cutoff=1).filter(ImageFilter.UnsharpMask(radius=1,percent=120,threshold=3))
    scale=min(3., max(1.,1800/max(image.size)))
    scale=min(scale,math.sqrt(3_000_000/(image.width*image.height)))
    new=(max(1,round(image.width*scale)),max(1,round(image.height*scale)))
    transform=np.diag([new[0]/image.width,new[1]/image.height,1.]) @ matrix
    image=image.resize(new,Image.Resampling.LANCZOS)
    border=12
    image=ImageOps.expand(image,border=border,fill='white')
    transform=np.array([[1,0,border],[0,1,border],[0,0,1]]) @ transform
    w,h=image.size
    if angle==90:
        image=image.transpose(Image.Transpose.ROTATE_90)
        transform=np.array([[0,1,0],[-1,0,w],[0,0,1]]) @ transform
    elif angle==180:
        image=image.transpose(Image.Transpose.ROTATE_180)
        transform=np.array([[-1,0,w],[0,-1,h],[0,0,1]]) @ transform
    elif angle==270:
        image=image.transpose(Image.Transpose.ROTATE_270)
        transform=np.array([[0,-1,h],[1,0,0],[0,0,1]]) @ transform
    return image,transform


def read_plate(ocr, image_path, region_index=0, max_attempts=8, seconds=18):
    """Read a crop without selecting a pass using catalogue/ground-truth values."""
    if not hasattr(ocr,'recognize_variant'):
        lines=ocr.recognize(image_path)
        return lines, [ReadingAttempt(id=f'region-{region_index}-baseline',region_index=region_index,
            method='baseline',rotation=0,psm=None,selected=True,quality_score=quality(lines),lines=lines)], []
    with Image.open(image_path) as original:
        source=original.convert('RGB')
    size=source.size
    quad=[(0.,0.),(float(size[0]),0.),(float(size[0]),float(size[1])),(0.,float(size[1]))]
    attempts=[];warnings=[];seen=set();deadline=time.monotonic()+seconds
    with tempfile.TemporaryDirectory(prefix='posify-plate-') as folder:
        def attempt(image,matrix,method,angle,psm,source_quad,code_mode=False):
            if len(attempts)>=max_attempts or time.monotonic()>=deadline:
                if 'reading_budget_exhausted' not in warnings: warnings.append('reading_budget_exhausted')
                return
            fingerprint=(image.size,psm,hashlib.sha256(image.tobytes()).digest())
            if fingerprint in seen: return
            seen.add(fingerprint)
            path=Path(folder)/f'{len(attempts)}.png';image.save(path)
            try:
                options={'code_mode':True} if code_mode else {}
                lines=ocr.recognize_variant(path,psm=psm,timeout=min(8.,max(.1,deadline-time.monotonic())),**options)
            except HTTPException:
                if not attempts: raise
                warnings.append('alternative_reading_failed')
                attempts.append(ReadingAttempt(id=f'region-{region_index}-pass-{len(attempts)}',region_index=region_index,
                    method=method,rotation=angle,psm=psm,source_quad=source_quad,warnings=['component_unavailable']))
                return
            lines=[mapped_line(line,np.linalg.inv(matrix),size) for line in lines[:80]]
            attempts.append(ReadingAttempt(id=f'region-{region_index}-pass-{len(attempts)}',region_index=region_index,
                method=method,rotation=angle,psm=psm,source_quad=source_quad,quality_score=quality(lines),lines=lines))
        identity=np.eye(3)
        attempt(source,identity,'original',0,6,quad)
        rotations=[0,90,180,270] if ocr.engine=='tesseract' else [0]
        for angle in rotations:
            image,matrix=prepare(source,identity,angle,contrast=True)
            attempt(image,matrix,'contrast_upscale_border',angle,6,quad)
        best_angle=max(attempts,key=lambda a:a.quality_score).rotation if attempts else 0
        try:
            rectified=rectify(source)
        except Exception:
            rectified=None;warnings.append('rectification_unavailable_original_preserved')
        base,matrix,source_quad=rectified if rectified else (source,identity,quad)
        if rectified is None:
            warnings.append('no_reliable_plate_boundary')
        for psm in ([6,11] if ocr.engine=='tesseract' else [6]):
            image,transform=prepare(base,matrix,best_angle,contrast=True)
            attempt(image,transform,'perspective_contrast' if rectified else 'contrast_upscale_border',best_angle,psm,source_quad)
        if ocr.engine=='tesseract' and attempts:
            chosen=max(attempts,key=lambda a:a.quality_score)
            code_words=[word for line in chosen.lines[:4] for word in line.words if word.box
                and sum(c.isdigit() for c in word.text)>=3 and sum(c.isalpha() for c in word.text)>=2
                and '-' in word.text and word.confidence<.75]
            for word in code_words[:1]:
                x1,y1,x2,y2=word.box;height=max(1,y2-y1)
                bounds=(max(0,int(x1-height*1.6)),max(0,int(y1-height*.12)),min(size[0],int(x2+height*.3)),min(size[1],int(y2+height*.12)))
                local=source.crop(bounds)
                shift=np.array([[1,0,-bounds[0]],[0,1,-bounds[1]],[0,0,1.]])
                code_quad=[(bounds[0],bounds[1]),(bounds[2],bounds[1]),(bounds[2],bounds[3]),(bounds[0],bounds[3])]
                for psm in [7,13]:
                    prepared,transform=prepare(local,shift,chosen.rotation,contrast=True)
                    attempt(prepared,transform,'code_line_refinement',chosen.rotation,psm,code_quad,code_mode=True)
    if not attempts: return [],[],warnings+['no_reading_completed']
    best=max(attempts,key=lambda a:a.quality_score);best.selected=True
    if best.quality_score<.50: warnings.append('poor_plate_readability')
    return best.lines,attempts,warnings
