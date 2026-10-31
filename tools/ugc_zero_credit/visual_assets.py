#!/usr/bin/env python3
"""Analyse qualité des plans produit sans modèle ni crédit.

Scores de netteté/luminance/texture pour tri manuel uniquement : une image
très nette peut représenter le mauvais produit ou être non licenciée.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess

IMAGE_EXT={'.jpg','.jpeg','.png','.webp'}
VIDEO_EXT={'.mp4','.mov','.mkv','.webm'}


def _frame(path:Path,t:float,size=320):
    try:
        import cv2
    except ImportError as e:
        raise RuntimeError('OpenCV manquant: pas de téléchargement automatique, voir requirements_vision_optional.txt') from e
    if path.suffix.lower() in IMAGE_EXT:
        img=cv2.imread(str(path),cv2.IMREAD_COLOR)
    else:
        cap=cv2.VideoCapture(str(path))
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC,float(t)*1000)
            ok,img=cap.read()
            if not ok:img=None
        finally:cap.release()
    if img is None:raise ValueError(f'Image/vidéo illisible: {path}')
    h,w=img.shape[:2]; scale=min(1,size/max(h,w))
    if scale<1:img=cv2.resize(img,(round(w*scale),round(h*scale)),interpolation=cv2.INTER_AREA)
    return img


def _hash_image(img):
    import cv2
    small=cv2.resize(cv2.cvtColor(img,cv2.COLOR_BGR2GRAY),(9,8),interpolation=cv2.INTER_AREA)
    bits=(small[:,1:]>small[:,:-1]).ravel()
    return ''.join('1' if x else '0' for x in bits)


def hamming(a,b):return sum(c!=d for c,d in zip(a,b)) if len(a)==len(b) else 64


def analyse(path:Path,*,times=(0,.4,.8))->dict:
    import cv2
    if not path.is_file():raise FileNotFoundError(path)
    frames=[]
    if path.suffix.lower() in VIDEO_EXT:
        probe=subprocess.run(['ffprobe','-v','error','-show_entries','format=duration','-of','default=nw=1:nk=1',str(path)],capture_output=True,text=True,timeout=30)
        if probe.returncode:raise ValueError('Vidéo illisible par FFprobe')
        dur=float(probe.stdout.strip())
        times=[max(0,min(dur-.06,dur*t)) for t in times]
    elif path.suffix.lower() in IMAGE_EXT:times=[0]
    else:raise ValueError(f'Format média refusé: {path.suffix}')
    for t in times:
        im=_frame(path,t);gray=cv2.cvtColor(im,cv2.COLOR_BGR2GRAY)
        import numpy as np
        sharp=float(cv2.Laplacian(gray,cv2.CV_64F).var())
        bright=float(gray.mean());black=float((gray<22).mean());white=float((gray>242).mean())
        contrast=float(gray.std());hsh=_hash_image(im)
        # Image score for prioritising manual inspection, not a quality guarantee.
        sharp_score=max(0,min(1,(math.log1p(sharp)-2.6)/4.7))
        exposure_score=max(0,1-abs(bright-123)/120)
        contrast_score=max(0,min(1,contrast/58))
        penalty=0.25 if black>.75 or white>.75 else 0
        score=round(max(0,100*(.48*sharp_score+.31*exposure_score+.21*contrast_score-penalty)),1)
        frames.append({'time_seconds':round(float(t),3),'sharpness_variance':round(sharp,2),
                       'mean_brightness':round(bright,1),'contrast':round(contrast,1),
                       'black_fraction':round(black,3),'white_fraction':round(white,3),
                       'visual_clarity_score':score,'difference_hash':hsh})
    return {'path':str(path),'samples':frames,
            'mean_visual_clarity_score':round(sum(x['visual_clarity_score'] for x in frames)/len(frames),1),
            'possible_static_or_duplicate':len(frames)>1 and all(hamming(frames[0]['difference_hash'],r['difference_hash'])<=2 for r in frames[1:]),
            'product_identity_verified':False,'rights_verified_by_pixels':False,
            'reason':'Score de tri seulement; produit exact, autorisations, texte et claims doivent être contrôlés manuellement.',
            'cost_credits':0,'network_calls':0}


def inspect_assets(project:Path)->dict:
    from ugc import load_project,verify,get_media_file
    config,root=load_project(project)
    verify(config,root)
    entries=[]
    for i,overlay in enumerate(config.get('overlays',[])):
        result=analyse(get_media_file(root,overlay['file']))
        result['index']=i;result['rights_declared']=overlay['rights']
        entries.append(result)
    near=[]
    for i,a in enumerate(entries):
        for b in entries[i+1:]:
            if hamming(a['samples'][0]['difference_hash'],b['samples'][0]['difference_hash'])<=5:
                near.append([a['index'],b['index']])
    return {'status':'PASS' if entries else 'NO_ASSETS', 'assets':entries,'near_duplicate_candidates':near,
            'ranking_indices': [e['index'] for e in sorted(entries,key=lambda x:x['mean_visual_clarity_score'],reverse=True)],
            'visual_ranking_not_a_brand_or_license_check':True,'cost_credits':0,'network_calls':0}


def main():
    p=argparse.ArgumentParser(description='Tri visuel gratuit des assets de produit')
    p.add_argument('project');p.add_argument('--output');a=p.parse_args()
    r=inspect_assets(Path(a.project))
    if a.output:Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
