#!/usr/bin/env python3
"""Offline QA for vertical UGC MP4. Uses only Python stdlib + local FFmpeg.

Signal detectors are *screening tools*, not automatic proof of good editing,
accurate lip sync, or rights clearance. Exit 2 on structural failures.
"""
from __future__ import annotations
import argparse, json, math, re, subprocess
from pathlib import Path


def command(args, timeout=120):
    p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
    if p.returncode:
        raise RuntimeError((p.stderr or p.stdout)[-1200:])
    return p.stdout,p.stderr


def detect(path, name, params, duration):
    # Low-resolution analysis avoids decoding an HD image for every detector.
    vf=f"fps=4,scale=270:-2,{name}={params}" if name!='silencedetect' else None
    cmd=['ffmpeg','-hide_banner','-nostdin','-i',str(path)]
    if vf: cmd+=['-vf',vf,'-an']
    else:cmd+=['-af',f'{name}={params}','-vn']
    cmd+=['-f','null','-']
    _,log=command(cmd,timeout=max(120,round(duration*5)))
    return log


def analyze(path:Path,*,full_decode=False):
    if not path.is_file():raise ValueError('MP4 introuvable')
    raw,_=command(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(path)])
    info=json.loads(raw);streams=info['streams'];vid=next((s for s in streams if s.get('codec_type')=='video'),None);aud=next((s for s in streams if s.get('codec_type')=='audio'),None)
    fatal=[];warnings=[]
    if not vid:fatal.append('Pas de vidéo')
    if not aud:fatal.append('Pas de piste audio')
    duration=float(info.get('format',{}).get('duration',0))
    if not 0<duration<=3600:fatal.append('Durée invalide')
    w=int(vid.get('width',0)) if vid else 0;h=int(vid.get('height',0)) if vid else 0
    if w*16!=h*9:fatal.append('Format non 9:16')
    if w<720 or h<1280:warnings.append('Résolution inférieure à 720×1280')
    if vid and vid.get('codec_name')!='h264':warnings.append('Codec vidéo autre que H.264')
    if aud and aud.get('codec_name')!='aac':warnings.append('Codec audio autre que AAC')
    fps=vid.get('avg_frame_rate','0/1') if vid else '0/1'
    if vid:
        try:
            a,b=map(float,fps.split('/'))
            if b==0 or not 23.9<=a/b<=60.1:warnings.append('Cadence hors de 24–60 FPS')
        except (ValueError,ZeroDivisionError):fatal.append('Cadence non lisible')
    detections={}
    if not fatal:
        for name,params,pattern in [
            ('blackdetect','d=0.55:pix_th=0.08:pic_th=0.96',r'black_start:([0-9.]+) black_end:([0-9.]+)'),
            ('freezedetect','n=-50dB:d=1.5',r'freeze_start: ([0-9.]+)'),
            ('silencedetect','noise=-45dB:d=1.2',r'silence_start: ([0-9.]+)')]:
            try:
                log=detect(path,name,params,duration)
                found=re.findall(pattern,log)
                detections[name]=found[:30]
                if found:warnings.append(f'{name}: {len(found)} passage(s) à examiner')
            except (RuntimeError,subprocess.TimeoutExpired) as e:
                warnings.append(f'{name}: analyse indisponible ({str(e)[:100]})')
        if full_decode:
            try:command(['ffmpeg','-v','error','-xerror','-i',str(path),'-f','null','-'],timeout=max(120,round(duration*6)))
            except (RuntimeError,subprocess.TimeoutExpired):fatal.append('Décodage intégral échoué')
    return {'path':str(path),'duration':duration,'resolution':[w,h],'fps':fps,'video_codec':vid.get('codec_name') if vid else None,'audio_codec':aud.get('codec_name') if aud else None,'structural_pass':not fatal,'fatal':fatal,'warnings':warnings,'signal_detections':detections,'full_decode':full_decode,'human_review_required':['intelligibilité de la voix','synchronisation labiale','précision du produit','droits et allégations','lisibilité des sous-titres']}


def main():
    p=argparse.ArgumentParser();p.add_argument('video');p.add_argument('--full-decode',action='store_true');p.add_argument('--output');args=p.parse_args()
    try:r=analyze(Path(args.video),full_decode=args.full_decode)
    except (ValueError,RuntimeError) as e:print(json.dumps({'error':str(e)},ensure_ascii=False));raise SystemExit(2)
    s=json.dumps(r,ensure_ascii=False,indent=2);print(s)
    if args.output:Path(args.output).write_text(s+'\n',encoding='utf-8')
    if not r['structural_pass']:raise SystemExit(2)
if __name__=='__main__':main()
