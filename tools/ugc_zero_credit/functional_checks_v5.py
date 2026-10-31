#!/usr/bin/env python3
"""Integration acceptance run V5. Requires included synthetic media, no network/paid API."""
from __future__ import annotations
import copy
import json
import tempfile
from pathlib import Path
from ugc import load_project,verify,protect_output_path,sha256
from review_sheet import make_contact_sheet
from release_gate import assess,REQUIRED_REVIEWS

ROOT=Path(__file__).resolve().parent
project=ROOT/'examples'/'synthetic_demo.json'
config,base=load_project(project)
checked=verify(config,base)
results=[]
def ok(name,condition):
    if not condition:raise AssertionError(name)
    results.append('PASS: '+name)
def denied(name,fn):
    try:fn()
    except ValueError:results.append('REJET: '+name)
    else:raise AssertionError('Aurait dû être rejeté: '+name)

source=(base/config['talking_clips'][0]['file']).resolve()
h=sha256(source)
denied('Refus d’écraser directement la vidéo source',lambda:protect_output_path(source,checked,config,base))
ok('Source inchangée après refus de sortie',sha256(source)==h)
denied('Refus d’une sortie sans extension MP4',lambda:protect_output_path(ROOT/'film.mkv',checked,config,base))
with tempfile.TemporaryDirectory(prefix='ugc-v5-qa-') as tmp:
    tmp=Path(tmp)
    alias=tmp/'lien.mp4';alias.symlink_to(source)
    denied('Refus de lien symbolique alias vers une source',lambda:protect_output_path(alias,checked,config,base))
    protect_output_path(tmp/'nouvelle_video.mp4',checked,config,base)
    ok('Nouvelle destination autorisée',True)
    sheet=tmp/'contact.jpg'
    r=make_contact_sheet(ROOT/'demo_1080x1920.mp4',sheet,count=9)
    ok('Planche de contact extraite du véritable MP4',sheet.is_file() and len(r['timestamps'])==9)
    ok('Planche de contact associée à l’empreinte source',r['source_sha256']==sha256(ROOT/'demo_1080x1920.mp4'))
    denied('Refus de 0 images',lambda:make_contact_sheet(ROOT/'demo_1080x1920.mp4',sheet,count=0))
    denied('Refus de largeur d’image invalide',lambda:make_contact_sheet(ROOT/'demo_1080x1920.mp4',sheet,tile_width=2000))
    release=assess(project,ROOT/'demo_1080x1920.mp4')
    ok('Démonstration synthétique NON publiable par défaut',release['status']=='BLOCKED')
    ok('Approbation humaine absente bloquante',any('approbation' in s for s in release['failures']))
    ok('Références d’allégations absentes bloquantes',any('allégations' in s for s in release['failures']))
    ok('Test libre de crédits et réseaux',release['cost_credits']==0 and release['network_requests']==0)
    approvals=tmp/'approvals.json'
    approvals.write_text(json.dumps({'reviewer':'contrôle démo','video_sha256':sha256(ROOT/'demo_1080x1920.mp4'),
         'reviews':{k:True for k in REQUIRED_REVIEWS}}),encoding='utf-8')
    forged=assess(project,ROOT/'demo_1080x1920.mp4',approvals=approvals)
    ok('Même avec cases approuvées: pas de publication sans contrôle source',forged['status']=='BLOCKED')
    approvals.write_text(json.dumps({'reviewer':'contrôle démo','video_sha256':'0'*64,
         'reviews':{k:True for k in REQUIRED_REVIEWS}}),encoding='utf-8')
    mismatch=assess(project,ROOT/'demo_1080x1920.mp4',approvals=approvals)
    ok('Fausse empreinte de validation rejetée',any('SHA-256' in s for s in mismatch['failures']))
    ok('Liste de vérifications humaines complète',len(REQUIRED_REVIEWS)==8)

report={'release':'5.0','status':'PASS','functional_integration_checks':len(results),'checks':results,
        'credits_consumed':0,'api_calls':0,'external_model_downloads':0,
        'demo_publication_status':'BLOCKED: no real influencer or approvals'}
(ROOT/'functional_results_v5.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
