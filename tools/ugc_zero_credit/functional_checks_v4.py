#!/usr/bin/env python3
"""Tests fonctionnels offline du moteur V4 (aucun appel à un service payant)."""
from __future__ import annotations
import argparse,copy,json,sys,subprocess
from pathlib import Path
from ugc import verify,load_project,face_aware_crop,build,sha256
from face_quality import _audit_single,audit_talking_clips
from environment_doctor import doctor

ROOT=Path(__file__).resolve().parent
SOURCE=ROOT/'examples/synthetic_demo.json'
BASE,folder=load_project(SOURCE)
CHECKS=[]

def accept(name,condition):
    assert condition,name
    CHECKS.append('PASS: '+name)

def reject(name,change):
    obj=copy.deepcopy(BASE);change(obj)
    try:verify(obj,folder)
    except ValueError:CHECKS.append('REJET: '+name)
    else:raise AssertionError(name+' aurait dû échouer')

valid=verify(BASE,folder)
accept('Configuration V3 acceptée en V4', bool(valid['talking']))
reject('Politique visage inconnue',lambda c:c.update(face_policy='inconnu'))
reject('Smart crop inconnu',lambda c:c['talking_clips'][0].update(smart_crop='neural_paid'))
reject('Focus x hors cadre',lambda c:c['talking_clips'][0].update(focus_x=2))
reject('Focus y NaN',lambda c:c['talking_clips'][0].update(focus_y=float('nan')))

synth=audit_talking_clips(valid['talking'],policy='review',samples_per_second=2)
accept('Graphiques sans influenceuse = refus visuel', synth['status']=='fail' and synth['clips'][0]['face_coverage']==0)
accept('L’absence de visage ne consomme pas de crédit',synth['network_calls']==0 and synth['cost_credits']==0)
accept('Politique off explicite = test non exécuté',audit_talking_clips(valid['talking'],policy='off')['status']=='skipped')

try:build(BASE,folder,ROOT/'forbidden_face_output.mp4',preview=True,face_policy_override='required')
except ValueError as e:accept('Export strict bloqué avant encodeur sans visage', 'Audit visage obligatoire' in str(e))
else:raise AssertionError('Blocage visage requis')

fake={'face_center_normalized':[.90,.39]}
fx,fy=face_aware_crop(fake,1280,720,360,640)
accept('Visage très à droite => recadrage vers bord droit',fx==1 and fy==.5)
fx2,fy2=face_aware_crop(fake,1080,1920,360,640)
accept('Format 9:16 déjà adapté => crop sans perturbation',(fx2,fy2)==(.5,.5))

probe=doctor(ROOT)
accept('Doctor: moteur FFmpeg et disque compatibles',probe['summary']['render_local_ready'])
accept('Doctor: n’invente pas une disponibilité lip-sync GPU',not probe['summary']['neural_lip_sync_ready'])
accept('Doctor: aucun jeton/API consommé',probe['credit_cost']==probe['network_calls']==0)

if len(sys.argv)>1:
    external=Path(sys.argv[1]);accept('Vidéo de test avec visage disponible', external.exists())
    face=_audit_single(external,0,3.8)
    accept('Visage parlant et bouche mobile détectés', face['status']=='pass' and face['mouth_active_fraction']>.2)
    frozen=Path(sys.argv[2]) if len(sys.argv)>2 else None
    if frozen:
        bad=_audit_single(frozen,0,3.8)
        accept('Vidéo figée avec voix correctement rejetée',bad['status']=='fail' and bad['mouth_motion_median']<1)

report={'version':'4.0','status':'PASS','checks':len(CHECKS),'results':CHECKS,
        'cost_credits':0,'api_calls':0,'model_downloads':0,
        'known_limitation':'Un mouvement de bouche ne prouve pas sa synchronisation phonétique avec la voix.'}
(ROOT/'functional_results_v4.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
