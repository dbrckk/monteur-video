#!/usr/bin/env python3
"""Audit éditorial de vidéos UGC hors ligne.

Contrôle la proportion de parole masquée par des inserts plein écran et le
rythme des plans. Ne remplace ni la validation des droits ni une écoute humaine.
Aucun appel réseau, aucun modèle génératif ni score prétendu de lip-sync.
"""
from __future__ import annotations
import argparse
import json
import math
from pathlib import Path


def _merge(spans: list[tuple[float,float]]) -> list[tuple[float,float]]:
    merged=[]
    for left,right in sorted(spans):
        if right<=left:continue
        if merged and left<=merged[-1][1]+1e-8:
            merged[-1]=(merged[-1][0],max(merged[-1][1],right))
        else:merged.append((left,right))
    return merged


def _duration(intervals):
    return sum(end-start for start,end in intervals)


def _intersect(a:list[tuple[float,float]],b:list[tuple[float,float]])->list[tuple[float,float]]:
    i=j=0;out=[]
    while i<len(a) and j<len(b):
        x=max(a[i][0],b[j][0]);y=min(a[i][1],b[j][1]);
        if x<y:out.append((x,y))
        if a[i][1]<b[j][1]:i+=1
        else:j+=1
    return _merge(out)


def analyze(checked:dict,overlays:list[dict],*,max_speech_covered=.55,max_continuous_broll=3.5,
            hook_seconds=.8,max_cuts_per_minute=42)->dict:
    """Based on manually supplied *acoustic word times*, never guessed timestamps.

    Note: an overlay is assumed full screen, as the current FFmpeg compositor
    fills the frame; even a fade still counts as potentially hiding the face.
    """
    total=float(checked['total_duration'])
    words=_merge([(float(w['start']),float(w['end'])) for w in checked.get('words',[])])
    spans=_merge([(float(x['start']),float(x['start'])+float(x['duration'])) for x in overlays])
    spoken=_duration(words)
    hidden=_intersect(words,spans)
    cover=_duration(hidden)
    ratio=cover/spoken if spoken>0 else None
    visible=sum(1 for s,e in spans if e>0 and s<hook_seconds)
    continuous=max((e-s for s,e in spans),default=0)
    cut_events=sorted({round(t,3) for span in spans for t in span if .001<t<total-.001})
    cuts_per_minute=len(cut_events)*60/total if total else float('inf')
    flags=[];advice=[]
    if not words:
        flags.append('unknown_speech_timing')
        advice.append('Fournir les vrais horodatages des mots avant de juger la visibilité pendant la voix.')
    if spans and spans[0][0] < hook_seconds and visible:
        flags.append('hook_obscured')
        advice.append(f'Conserver au moins {hook_seconds:.1f} s de présentatrice visible à l’ouverture.')
    if ratio is not None and ratio>max_speech_covered:
        flags.append('excessive_speech_occlusion')
        advice.append('Réduire ou déplacer les inserts : une trop grande partie de la parole masque le visage.')
    if continuous>max_continuous_broll:
        flags.append('long_continuous_broll')
        advice.append('Couper les séquences produit trop longues par un retour face caméra.')
    if cuts_per_minute>max_cuts_per_minute:
        flags.append('excessive_cut_pace')
        advice.append('Ralentir la fréquence des coupes pour améliorer la lisibilité et la confiance.')
    # Missing observed speech is explicitly unproven, not PASS.
    status='REVIEW' if not words else ('WARN' if flags else 'PASS')
    return {'status':status,'total_seconds':round(total,3), 'speech_seconds_observed':round(spoken,3),
            'speech_covered_seconds':round(cover,3),
            'speech_covered_ratio':round(ratio,3) if ratio is not None else None,
            'max_broll_seconds':round(continuous,3),'cuts_per_minute':round(cuts_per_minute,2),
            'hook_unobscured':visible==0,'broll_intervals':[[round(s,3),round(e,3)] for s,e in spans],
            'speech_covered_intervals':[[round(s,3),round(e,3)] for s,e in hidden],
            'flags':flags,'recommendations':advice,'score': None if ratio is None else round(100*(1-min(1,ratio)),1),
            'limits':{'max_speech_covered':max_speech_covered,'max_continuous_broll':max_continuous_broll,
                      'hook_seconds':hook_seconds,'max_cuts_per_minute':max_cuts_per_minute},
            'requires_human_review':True,'does_not_estimate_phoneme_lipsync':True,
            'cost_credits':0,'network_calls':0}


def for_project(project:Path,*,inspect_media=True):
    from ugc import load_project,verify
    config,root=load_project(project)
    return analyze(verify(config,root,inspect_media=inspect_media),config.get('overlays',[]))


def main():
    p=argparse.ArgumentParser(description='Audit montage gratuit : visage visible pendant la parole')
    p.add_argument('project');p.add_argument('--output');p.add_argument('--strict',action='store_true')
    args=p.parse_args()
    report=for_project(Path(args.project))
    if args.output:Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if args.strict and report['status']!='PASS':raise SystemExit(3)
if __name__=='__main__':main()
