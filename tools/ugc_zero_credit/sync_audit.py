#!/usr/bin/env python3
"""Vérification audio gratuite source→export (ne mesure PAS la synchronisation labiale du modèle)."""
import argparse
import array
import json
from pathlib import Path
import subprocess
import sys


def samples(path, start, duration, rate=2000):
    cmd=["ffmpeg","-v","error","-nostdin","-ss",f"{start:.6f}","-i",str(path),"-t",f"{duration:.6f}","-vn","-ac","1","-ar",str(rate),"-f","s16le","-"]
    x=subprocess.run(cmd,capture_output=True,timeout=120)
    if x.returncode:raise RuntimeError(x.stderr.decode(errors='replace')[-1200:])
    vals=array.array("h"); vals.frombytes(x.stdout)
    if sys.byteorder!="little":vals.byteswap()
    return [v/32768.0 for v in vals]


def correlate(a,b,rate=2000,maximum_ms=120):
    # Estime un lag constant; ignore les attaques/rampes du début et les bords.
    size=min(len(a),len(b));pad=int(.25*rate)
    n=min(int(3.6*rate),size-pad-int(maximum_ms/1000*rate)-100)
    if n<rate//2:return {"status":"indeterminate","reason":"signal trop court"}
    hop=3;la=a[pad:pad+n:hop]
    mean=sum(la)/len(la);la=[v-mean for v in la];power=sum(v*v for v in la)
    if power<.000001:return {"status":"indeterminate","reason":"audio trop silencieux"}
    max_lag=int(maximum_ms/1000*rate)
    best=(-1e30,0)
    for lag in range(-max_lag,max_lag+1,2):
        rb=b[pad+lag:pad+lag+n:hop]
        if len(rb)!=len(la):continue
        avg=sum(rb)/len(rb)
        s=sum(x*(y-avg) for x,y in zip(la,rb))
        den=(power*sum((y-avg)*(y-avg) for y in rb))**.5
        c=s/den if den>1e-10 else -1.
        if c>best[0]:best=(c,lag)
    corr,lag=best
    return {"status":"matched" if corr>=.25 else "indeterminate","estimated_audio_shift_ms":round(lag/rate*1000,1),"correlation":round(corr,4),"note":"lag de l'audio mixé relatif au signal natif; ne teste pas la synchronisation visuelle des lèvres"}


def distributed_windows(clip_duration:float, window=1.6) -> list[tuple[float,float]]:
    """Three voice samples across each native speaking clip, not only its opening."""
    if clip_duration<=0.55:return [(0,max(.4,clip_duration))]
    span=min(window,max(.6,clip_duration-.2))
    last=max(.0,clip_duration-span)
    offsets=[min(.12,last),last/2,last]
    clean=[]
    for x in offsets:
        if all(abs(x-y[0])>.18 for y in clean):clean.append((x,span))
    return clean


def audit_timeline(talking:list[dict], render:Path, *, threshold_ms=50, max_drift_ms=40) -> dict:
    """Correlate each native voice source with its final timing (no visual lip claim)."""
    comparisons=[]
    for clip in talking:
        comparisons_clip=[]
        for off,d in distributed_windows(clip['duration']):
            src=samples(clip['file'],clip['source_in']+off,d)
            final=samples(render,clip['timeline_start']+off,d)
            match=correlate(src,final,maximum_ms=120)
            match.update(source_offset_seconds=round(off,3),window_seconds=round(d,3))
            comparisons_clip.append(match)
        valid=[m for m in comparisons_clip if m['status']=='matched']
        shifts=[m['estimated_audio_shift_ms'] for m in valid]
        drift=round(max(shifts)-min(shifts),2) if len(shifts)>1 else None
        stable=len(valid)==len(comparisons_clip) and all(abs(x)<=threshold_ms for x in shifts) and (drift is None or drift<=max_drift_ms)
        comparisons.append({'clip_index':clip['index'],'windows':comparisons_clip,
                            'drift_range_ms':drift,'audio_timing_pass':stable})
    return {'render':str(render),'threshold_shift_ms':threshold_ms,'threshold_drift_ms':max_drift_ms,
            'clips':comparisons,'native_audio_preserved':all(x['audio_timing_pass'] for x in comparisons),
            'caveat':'Audio source→export only. Does not measure generated mouth/lip alignment.'}


def audit(project:Path, render:Path, *, threshold_ms=50, max_drift_ms=40) -> dict:
    from ugc import load_project, verify
    conf,root=load_project(project);info=verify(conf,root)
    return audit_timeline(info['talking'],render,threshold_ms=threshold_ms,max_drift_ms=max_drift_ms)


def main():
    p=argparse.ArgumentParser(description='Audit audio local à plusieurs fenêtres, sans API')
    p.add_argument('project');p.add_argument('render');p.add_argument('--threshold-ms',type=float,default=50)
    p.add_argument('--max-drift-ms',type=float,default=40)
    p.add_argument('--strict',action='store_true')
    p.add_argument('--report')
    a=p.parse_args()
    report=audit(Path(a.project),Path(a.render),threshold_ms=a.threshold_ms,max_drift_ms=a.max_drift_ms)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if a.report:Path(a.report).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if a.strict and not report['native_audio_preserved']:sys.exit(3)


if __name__=='__main__':main()
