#!/usr/bin/env python3
"""Audit visuel de plans parlés 100 % local (OpenCV Haar + FFmpeg).

Ne mesure PAS la synchronisation phonétique lèvres/voix. Détecte seulement
l'absence de visage, l'immobilité manifeste du bas du visage et les cadrages
à examiner. Aucune API ni poids téléchargé; cv2.data contient la cascade Haar.
"""
from __future__ import annotations
import argparse
import array
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys


def _audio_level_per_time(path: Path, times: list[float], origin: float, duration: float, rate: int = 8000):
    """RMS du signal natif, mesuré localement par fenêtre centrée autour de t.

    Il s'agit de l'activité sonore, PAS de reconnaissance vocale.
    """
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-ss", f"{origin:.4f}",
               "-i", str(path), "-t", f"{duration:.4f}", "-vn", "-ac", "1", "-ar", str(rate),
               "-f", "s16le", "-"]
    result = subprocess.run(command, capture_output=True, timeout=max(45, int(duration * 4)))
    if result.returncode:
        return [None] * len(times)
    pcm = array.array('h')
    pcm.frombytes(result.stdout[:len(result.stdout)//2*2])
    if sys.byteorder != 'little':pcm.byteswap()
    power = []
    window = max(int(rate*.10), 1)
    for absolute in times:
        center = int((absolute-origin)*rate)
        s = max(0, center-window)
        e = min(len(pcm), center+window)
        if e-s < rate*.05:
            power.append(None)
        else:
            rms=math.sqrt(sum((v/32768)**2 for v in pcm[s:e])/(e-s))
            power.append(round(20*math.log10(max(rms,1e-9)), 2))
    return power


def _safe_stat(values, method='median'):
    if not values:return None
    if method == 'median':return round(float(statistics.median(values)),3)
    return round(float(sum(values)/len(values)), 3)


def _audit_single(path: Path, start: float, duration: float, *, samples_per_second=3.5, max_samples=95) -> dict:
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {'status':'unavailable', 'reason':'OpenCV + NumPy non installés; aucune requête externe',
                'human_review_required':True}
    if duration < .6:
        return {'status':'review','reason':'Plan trop court pour mesurer le mouvement', 'human_review_required':True}
    classifier = cv2.CascadeClassifier(str(Path(cv2.data.haarcascades)/'haarcascade_frontalface_default.xml'))
    if classifier.empty():
        return {'status':'unavailable','reason':'Cascade Haar locale indisponible','human_review_required':True}
    cap=cv2.VideoCapture(str(path))
    if not cap.isOpened():
        return {'status':'unavailable','reason':'Impossible d’ouvrir la vidéo en local','human_review_required':True}
    try:
        n=min(max_samples, max(7, math.ceil(duration*samples_per_second)))
        # Évite les premières/dernières images de coupe et représente la séquence entière.
        absolute_times=[start + min(duration-.055, max(.06,(i+.45)*duration/n)) for i in range(n)]
        levels=_audio_level_per_time(path,absolute_times,start,duration)
        found=0;boxes=[];mouth_moves=[];forehead_moves=[];audible_pair=[];frames_ok=0
        prev=None;prev_time=None
        for t,db in zip(absolute_times,levels):
            cap.set(cv2.CAP_PROP_POS_MSEC, t*1000)
            ok,image=cap.read()
            if not ok:continue
            frames_ok+=1
            height,width=image.shape[:2]
            scale=min(1,480/max(width,1))
            sw=max(1,round(width*scale));sh=max(1,round(height*scale))
            resized=cv2.resize(image,(sw,sh),interpolation=cv2.INTER_AREA)
            gray=cv2.cvtColor(resized,cv2.COLOR_BGR2GRAY)
            faces=classifier.detectMultiScale(gray,scaleFactor=1.10,minNeighbors=4,minSize=(max(28,sw//12),max(28,sw//12)))
            if len(faces)==0:
                prev=None;prev_time=None
                continue
            x,y,w,h=max(faces,key=lambda v:v[2]*v[3]);x=int(x);y=int(y);w=int(w);h=int(h)
            found+=1
            boxes.append(( (x+w/2)/sw,(y+h/2)/sh,w/sw,h/sh ))
            def patch(x0,y0,x1,y1,ow,oh):
                xa=max(0,int(x+w*x0));xb=min(sw,int(x+w*x1))
                ya=max(0,int(y+h*y0));yb=min(sh,int(y+h*y1))
                if xb<=xa or yb<=ya:return None
                return cv2.resize(gray[ya:yb,xa:xb],(ow,oh)).astype(np.float32)
            mouth=patch(.22,.60,.78,.90,88,48)
            forehead=patch(.24,.18,.76,.43,88,48)
            if mouth is not None and forehead is not None and prev is not None and prev_time is not None and t-prev_time<.8:
                mouth_delta=float(np.mean(np.abs(mouth-prev[0])))
                forehead_delta=float(np.mean(np.abs(forehead-prev[1])))
                # Camera/head motion changes forehead as well: subtract part of it.
                relative=max(0.,mouth_delta-.45*forehead_delta)
                mouth_moves.append(relative)
                forehead_moves.append(forehead_delta)
                audible_pair.append(db is not None and db > -41)
            if mouth is not None and forehead is not None:
                prev=(mouth,forehead);prev_time=t
        if not frames_ok:
            return {'status':'unavailable','reason':'Pas de frames décodables','human_review_required':True}
        coverage=found/frames_ok
        audible=sum(x is not None and x>-41 for x in levels)/max(1,len(levels))
        active=[x for x,a in zip(mouth_moves,audible_pair) if a]
        activity_fraction=sum(x>=2.0 for x in active)/len(active) if active else 0.
        motion_p90=float(np.percentile(active,90)) if active else 0.
        centers=[(b[0],b[1]) for b in boxes]
        outside=sum(not(.09<=x<=.87 and .12<=y<=.85) for x,y in centers)/len(centers) if centers else None
        reasons=[]
        if coverage<.20:
            status='fail';reasons.append('Aucun visage frontal fiable pendant la majeure partie du plan parlé')
        elif coverage<.53:
            status='review';reasons.append('Visage absent ou non frontal sur une grande partie du plan')
        elif audible>=.35 and len(active)>=5 and activity_fraction<.10 and motion_p90<1.5:
            status='fail';reasons.append('Zone bouche quasi immobile malgré une activité audio importante')
        elif len(active)<4 or audible<.15:
            status='review';reasons.append('Signal vocal insuffisant pour conclure sur le mouvement')
        else:
            status='pass'
        if outside is not None and outside>.30:
            # This may be repaired by the optional face-aware crop.
            # It must still appear in the report, even if motion is sound.
            reasons.append('Cadrage à corriger: visage souvent dans la zone des boutons')
        stats={
            'status':status,
            'reason':'; '.join(reasons) or 'Visage détecté et zone de la bouche en mouvement',
            'source':str(path), 'source_in':round(start,3),'duration':round(duration,3),
            'sampled_frames':frames_ok,'detected_faces':found,'face_coverage':round(coverage,3),
            'face_center_normalized':[_safe_stat([z[0] for z in boxes]),_safe_stat([z[1] for z in boxes])] if boxes else None,
            'face_width_fraction':_safe_stat([z[2] for z in boxes]),
            'face_unsafe_fraction':round(outside,3) if outside is not None else None,
            'audio_activity_fraction':round(audible,3),
            'mouth_motion_pairs':len(mouth_moves),'active_pairs':len(active),
            'mouth_motion_median':_safe_stat(active),
            'mouth_motion_p90':round(motion_p90,3),
            'mouth_active_fraction':round(activity_fraction,3),
            'human_review_required':True,
            'method':'OpenCV Haar local + différences de texture bouche/front + FFmpeg RMS local',
            'limitation':'Détecte une bouche figée ou visage absent, PAS le synchronisme phonème/lèvre. Faux positifs et négatifs possibles.'
        }
        return stats
    finally:
        cap.release()


def audit_talking_clips(talking:list[dict], *, policy='review',samples_per_second=3.5) -> dict:
    if policy not in {'off','review','required'}:raise ValueError('face_policy: attendu off/review/required')
    if policy=='off':return {'status':'skipped','policy':policy,'cost_credits':0,'clips':[]}
    clips=[]
    for i,cl in enumerate(talking):
        data=_audit_single(Path(cl['file']),float(cl['source_in']),float(cl['duration']),samples_per_second=samples_per_second)
        data['clip_index']=int(cl.get('index',i))
        clips.append(data)
    statuses=[x['status'] for x in clips]
    status='pass' if all(x=='pass' for x in statuses) else ('fail' if 'fail' in statuses else 'review')
    return {'status':status,'policy':policy,'clips':clips,'passes_required_gate':all(x=='pass' for x in statuses),
            'human_review_required':True,'cost_credits':0,'network_calls':0,
            'caveat':'Aucune validation phonétique/labiale précise sans modèle spécialisé + revue humaine.'}


def main():
    p=argparse.ArgumentParser(description='Analyse visuelle locale visage/bouche - zéro API')
    p.add_argument('project', help='JSON de montage UGC')
    p.add_argument('--strict',action='store_true',help='Code 3 si un clip n’est pas clairement validé')
    p.add_argument('--output',help='JSON de rapport')
    p.add_argument('--sample-fps',type=float,default=3.5)
    a=p.parse_args()
    from ugc import load_project,verify
    conf,folder=load_project(Path(a.project));checked=verify(conf,folder)
    r=audit_talking_clips(checked['talking'],policy='required' if a.strict else 'review',samples_per_second=a.sample_fps)
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if a.output:Path(a.output).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.strict and not r['passes_required_gate']:raise SystemExit(3)


if __name__=='__main__':main()
