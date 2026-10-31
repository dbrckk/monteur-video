#!/usr/bin/env python3
"""Planification locale conservatrice des inserts UGC, zero API.

Crée une COPIE de JSON éditable. N'altère pas le projet source et n'exporte rien.
Les temps de la parole proviennent des mots acoustiques fournis par l'utilisateur,
les recommandations ne remplacent pas la vérification des références au produit.
"""
from __future__ import annotations
import argparse
import copy
import json
import math
from pathlib import Path
from editorial_quality import analyze,_merge,_intersect,_duration


def propose(config:dict,checked:dict,*,max_cuts_per_minute=42,min_gap=.35,
            max_covered_speech=.50,hook=.80)->tuple[dict,dict]:
    total=float(checked['total_duration'])
    old=copy.deepcopy(config.get('overlays',[]))
    ranked=sorted(enumerate(old),key=lambda x:(float(x[1]['start']),x[0]))
    max_count=max(0,math.floor(max_cuts_per_minute*total/(60*2)))
    words=_merge([(float(w['start']),float(w['end'])) for w in checked.get('words',[])])
    spoken=_duration(words)
    new=[];removed=[];changes=[]
    if not words:
        report={'status':'REVIEW','message':'Impossible de proposer des coupes sûres sans horodatages des mots.',
                'kept':0,'removed':[],'changes':[],'original_audit':analyze(checked,old),
                'proposed_audit':None,'cost_credits':0,'network_calls':0}
        return copy.deepcopy(config),report
    cta_reserved=min(1.0,max(.35,total*.10))
    for i,layer in ranked:
        if len(new)>=max_count:
            removed.append({'index':i,'file':layer['file'],'reason':'Rythme de coupe maximal atteint'});continue
        # Keep useful b-roll, but don't let one product shot monopolise the scene.
        original=float(layer['duration'])
        duration=round(min(original,max(.65,min(1.35,total*.30))),3)
        if duration<.35:
            removed.append({'index':i,'file':layer['file'],'reason':'Insert trop court'});continue
        earliest=hook;latest=total-cta_reserved-duration
        if latest<=earliest:
            removed.append({'index':i,'file':layer['file'],'reason':'Aucune plage après le hook et avant le CTA'});continue
        # Prefer gaps between measured words and remain near the original cue.
        candidates={round(earliest+j*.1,3) for j in range(math.floor((latest-earliest)/.1)+1)}
        candidates.add(round(max(earliest,min(latest,float(layer['start']))),3))
        for a,b in zip(words,words[1:]):
            if b[0]>a[1]:
                mid=(a[1]+b[0])/2
                candidates.add(round(max(earliest,min(latest,mid-duration/2)),3))
        variants=[]
        for start in sorted(candidates):
            end=start+duration
            if any((start < t['start']+t['duration']+min_gap and end > t['start']-min_gap) for t in new):continue
            partial=_merge([(t['start'],t['start']+t['duration']) for t in new]+[(start,end)])
            hidden=_duration(_intersect(words,partial))
            if hidden/max(spoken,.001)>max_covered_speech:continue
            local=_duration(_intersect(words,[(start,end)]))
            # Prefer a cleaner speech gap, then editor's original position.
            score=local/max(duration,.001)*5+abs(start-float(layer['start']))/max(total,1)*.9
            variants.append((score,abs(start-float(layer['start'])),start))
        if not variants:
            removed.append({'index':i,'file':layer['file'],'reason':'Aucune coupe ne respecte visibilité voix/visage'});continue
        _,_,start=min(variants)
        revised=copy.deepcopy(layer);revised['start']=start;revised['duration']=duration
        revised['fade']=min(float(layer.get('fade',.14)),round(duration/2,3),.25)
        new.append(revised)
        changes.append({'index':i,'file':layer['file'],'original_start':layer['start'],
                        'new_start':start,'original_duration':layer['duration'],'new_duration':duration})
    new.sort(key=lambda z:z['start'])
    result=copy.deepcopy(config)
    result['overlays']=new
    result['editorial_policy']='required'
    audit=analyze(checked,new)
    status='PASS' if audit['status']=='PASS' else 'REVIEW'
    report={'status':status,'original_audit':analyze(checked,old),'proposed_audit':audit,
            'kept':len(new),'removed':removed,'changes':changes,
            'original_project_unchanged':True,'human_review_required':True,
            'warning':'Le placement automatique peut ne pas coïncider avec le sujet de la phrase; revoir le storyboard avant rendu.',
            'cost_credits':0,'network_calls':0}
    return result,report


def make_plan(project:Path,output:Path,report_path:Path|None=None)->dict:
    from ugc import load_project,verify
    c,folder=load_project(project)
    checked=verify(c,folder)
    if output.parent.resolve()!=project.resolve().parent:
        raise ValueError('Le projet proposé doit rester dans le même dossier pour conserver des références média sûres.')
    if output.resolve()==project.resolve() or output.exists():
        raise ValueError('Fichier de sortie existant/refus de remplacer le projet source')
    new,report=propose(c,checked)
    if report['status']!='PASS':
        return report
    # Rewrite only after final validation, reject any newly invalid source/overlay.
    verify(new,folder)
    output.write_text(json.dumps(new,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    report['output_project']=str(output)
    if report_path:
        report_path.parent.mkdir(parents=True,exist_ok=True)
        report_path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return report


def main():
    p=argparse.ArgumentParser(description='Plan éditorial sans IA payante, copie non destructive du JSON')
    p.add_argument('project');p.add_argument('--output',required=True);p.add_argument('--report')
    a=p.parse_args();r=make_plan(Path(a.project),Path(a.output),Path(a.report) if a.report else None)
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if r['status']!='PASS':raise SystemExit(3)
if __name__=='__main__':main()
