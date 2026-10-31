#!/usr/bin/env python3
"""Tests intégrés V6 (100% CPU local, sans appels réseau ou générations payantes)."""
from __future__ import annotations
import copy
import json
import subprocess
import tempfile
from pathlib import Path

import numpy as np
import cv2
from ugc import load_project,verify,build,sha256,protect_output_path
from editorial_quality import analyze as editorial_analyze,_merge,_intersect
from auto_edit import propose,make_plan
from review_dashboard import build as dashboard_build
from visual_assets import analyse,hamming,inspect_assets
from release_gate import assess

BASE=Path(__file__).resolve().parent
project=BASE/'examples'/'synthetic_demo.json'
config,root=load_project(project)
original=verify(config,root)
checks=[]

def passed(message,cond):
    if not cond:raise AssertionError(message)
    checks.append(message)

def rejects(message,fn,exception=(ValueError,RuntimeError)):
    try:fn()
    except exception:checks.append('REJET: '+message)
    else:raise AssertionError('Aurait dû refuser: '+message)

old=editorial_analyze(original,config['overlays'])
proposed,auto=propose(config,original)
passed('Automonteur aboutit à un montage éditorial validé',auto['status']=='PASS')
passed('Automonteur réduit l’obstruction vocale',auto['proposed_audit']['speech_covered_ratio']<old['speech_covered_ratio'])
passed('Accroche visage préservée par le plan',auto['proposed_audit']['hook_unobscured'])
passed('Ne modifie jamais le projet source',len(config['overlays'])==2 and len(proposed['overlays'])==1)
passed('Suppression des plans superfétatoires documentée',len(auto['removed'])==1 and len(auto['changes'])==1)
passed('Garde éditoriale activée dans nouveau JSON',proposed['editorial_policy']=='required')
passed('Durée globale de la narration préservée',verify(proposed,root)['total_duration']==original['total_duration'])
passed('Régression révélée: partie parlée masquée >55%',old['speech_covered_ratio']>.55)
passed('Auditeur signale le montage trop chargé',old['status']=='WARN' and 'excessive_speech_occlusion' in old['flags'])
passed('Aucun contrôle ne prétend prouver le lip-sync',old['does_not_estimate_phoneme_lipsync'])
passed('Intervals chevauchants fusionnés',_merge([(1,2),(1.2,3),(3,4)])==[(1,4)])
passed('Intervalle d’intersection correct',_intersect([(0,1),(2,3)],[(.5,2.5)])==[(.5,1),(2,2.5)])
passed('Coûts et réseau nuls',old['cost_credits']==old['network_calls']==0)

minimal=editorial_analyze(original,[])
passed('Absence d’inserts = narration visible',minimal['status']=='PASS' and minimal['speech_covered_ratio']==0)
hook=editorial_analyze(original,[{'start':0,'duration':.9}])
passed('Masquage de l’accroche détecté','hook_obscured' in hook['flags'])
long=editorial_analyze({'total_duration':12,'words':[{'start':0,'end':10}]},[{'start':3,'duration':4.5}])
passed('Insert continu trop long détecté','long_continuous_broll' in long['flags'])
unknown=editorial_analyze({'total_duration':4,'words':[]},[])
passed('Sans vrai minutage vocal, résultat REVIEW et non PASS',unknown['status']=='REVIEW' and unknown['speech_covered_ratio'] is None)

bad=copy.deepcopy(config);bad['editorial_policy']='invalid'
rejects('Politique éditoriale inconnue',lambda:verify(bad,root))

with tempfile.TemporaryDirectory(prefix='ugc-v6-functional-') as folder:
    folder=Path(folder)
    # Ensure the sidecar thumbnail can never overwrite an image source.
    with tempfile.NamedTemporaryFile(dir=root, prefix='test_cover_collision_', suffix='.jpg') as testsrc:
        testconf=copy.deepcopy(config)
        testconf['overlays'][0]['file']=Path(testsrc.name).name
        rejects('Miniature générée ne doit pas écraser une image produit',
                lambda:protect_output_path(Path(testsrc.name).with_suffix('.mp4'),original,testconf,root))
    photo=folder/'clear.png';blur=folder/'blur.png';duplicate=folder/'copy.png'
    baseimg=np.zeros((256,256,3),dtype=np.uint8);baseimg[:]=(130,120,145)
    for k in range(15,240,18):cv2.line(baseimg,(k,10),(k,240),(235,238,246),2)
    cv2.putText(baseimg,'DEMO PRODUCT',(12,120),cv2.FONT_HERSHEY_SIMPLEX,.8,(30,20,45),2)
    cv2.imwrite(str(photo),baseimg)
    cv2.imwrite(str(blur),cv2.GaussianBlur(baseimg,(41,41),12))
    cv2.imwrite(str(duplicate),baseimg)
    sharp=analyse(photo);soft=analyse(blur);copyimg=analyse(duplicate)
    passed('Visuel net priorisé sur image floue',sharp['mean_visual_clarity_score']>soft['mean_visual_clarity_score'])
    passed('Images identiques détectables',hamming(sharp['samples'][0]['difference_hash'],copyimg['samples'][0]['difference_hash'])==0)
    passed('Score ne garantit ni identité produit ni droits',sharp['product_identity_verified'] is False and sharp['rights_verified_by_pixels'] is False)
    rejects('Extension non image/vidéo rejetée',lambda:analyse(folder/'project.json'),(ValueError,FileNotFoundError))
    with tempfile.NamedTemporaryFile(prefix='ugc_v6_test_',suffix='.json',dir=project.parent,delete=True) as generated:
        suggested=Path(generated.name)
    made=make_plan(project,suggested)
    passed('Copie JSON autonome générée sans toucher à la source',made['status']=='PASS' and suggested.exists())
    rejects('Refus d’écraser un projet généré',lambda:make_plan(project,suggested))
    rejects('Refus de créer un projet hors du dossier source',lambda:make_plan(project,folder/'separate.json'))
    suggested.unlink()
    targets=inspect_assets(project)
    passed('Analyse des médias existants OK',len(targets['assets'])==2 and targets['status']=='PASS')
    passed('Rapport de tri contient les indices',set(targets['ranking_indices'])=={0,1})
    output=folder/'demo_v6_preview.mp4'
    safe=copy.deepcopy(config);safe['editorial_policy']='required';safe['overlays']=[]
    build_report=build(safe,root,output,preview=True,full_decode=True,strict_sync=True,face_policy_override='off')
    passed('Rendu V6 strict admissible décodable',output.exists() and build_report['quality_gate']['full_decode'])
    passed('V6: audio source préservé dans rendu',build_report['sync_audio_gate']['native_audio_preserved'])
    passed('V6: publication reste manuelle',build_report['publication']['automatic_publish'] is False)
    passed('V6: rapport éditorial intégré au rendu',build_report['editorial_quality']['status']=='PASS')
    rejects('Configuration trop chargée refusée avant rendu',lambda:build({**config,'editorial_policy':'required'},root,folder/'bad.mp4',preview=True,face_policy_override='off'))
    passed('Rendu refusé ne laisse aucun MP4',not (folder/'bad.mp4').exists())
    release=assess(project,output,full_decode=False)
    passed('Publication refusée sans authentique influenceuse et droits',release['status']=='BLOCKED')
    passed('Audit éditorial visible avant publication',release['editorial_quality']['status']=='WARN')
    passed('Contrôle de sortie embarque les sources',len(build_report['inventory'])>=1)
    passed('Rapport et sous-titres présents',output.with_suffix('.report.json').is_file() and output.with_suffix('.srt').is_file())
    report_preview=folder/'preview_v6_report.json'
    report_preview.write_text(json.dumps(build_report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    page=folder/'review.html'
    page_info=dashboard_build(output,page)
    page_text=page.read_text(encoding='utf-8')
    passed('Revue mobile HTML générée',page.is_file() and '<video' in page_text)
    passed('La page n’injecte aucun service réseau',not any(x in page_text for x in ('https://','http://','<script','fonts.googleapis')))
    passed('Lecteur pointe vers le MP4 local',output.name in page_text)
    passed('Rapport mobile et vidéo cohérents',page_info['speech_covered_ratio']==0 and page_info['cost_credits']==0)
    forged_report=folder/'fake_report.json'
    injected=copy.deepcopy(build_report)
    injected['editorial_quality']['flags']=['<script>alert(1)</script>']
    forged_report.write_text(json.dumps(injected,ensure_ascii=False),encoding='utf-8')
    dashboard_build(output,folder/'safe_review.html',report=forged_report)
    passed('Texte d’alerte HTML échappé, pas de XSS',
           '&lt;script&gt;' in (folder/'safe_review.html').read_text(encoding='utf-8'))
    injected['output']='other_file.mp4'
    forged_report.write_text(json.dumps(injected,ensure_ascii=False),encoding='utf-8')
    rejects('Refus d’un rapport ne correspondant pas au MP4',
            lambda:dashboard_build(output,folder/'invalid_review.html',report=forged_report))

result={'version':'6.0','status':'PASS','checks_passed':len(checks),'checks':checks,
        'credit_cost':0,'external_api_calls':0,'model_downloads':0,'paid_generations':0,
        'limitations':['Pas d’évaluation phonème-lèvre','Ranking visuel ≠ conformité produit','Vrai modèle influenceuse non généré gratuitement'],
        'previous_demo_flags':old['flags']}
(BASE/'functional_results_v6.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(result,ensure_ascii=False,indent=2))
