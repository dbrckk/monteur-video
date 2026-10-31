#!/usr/bin/env python3
"""End-to-end functional checks for V3; no unit-test framework, no network/APIs.

Does not re-encode a new video; expects the provided verified demo MP4.
"""
from __future__ import annotations
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from audio_quality import analyze_audio
from quality_gate import analyze as quality_analyze
from sync_audit import audit as sync_audit
from ugc import caption_groups, load_project, sha256, verify, platform_guide

ROOT=Path(__file__).resolve().parent
SRC=ROOT/'examples/synthetic_demo.json'
RESULTS=[]


def assert_rejected(label, mutator):
    p=copy.deepcopy(BASE)
    mutator(p)
    try:verify(p,ROOT/'examples')
    except (ValueError,RuntimeError):RESULTS.append('REJET: '+label)
    else:raise AssertionError('REJET MANQUANT: '+label)


BASE,folder=load_project(SRC)
valid=verify(BASE,folder)
RESULTS.append('Configuration V3 valide acceptée')

for title,edit in [
 ('droits non déclarés',lambda p:p['talking_clips'][0].update(rights='unknown')),
 ('doublage tardif non synchronisé',lambda p:p['talking_clips'][0].update(sync='dubbed')),
 ('génération payante activée',lambda p:p.update(forbidden_paid_services=False)),
 ('service HTTP externe',lambda p:p['talking_clips'][0].update(file='https://example.com/secret.mp4')),
 ('sortie du dossier par traversal',lambda p:p['talking_clips'][0].update(file='../../../etc/passwd')),
 ('clip avec timing trop long',lambda p:p['talking_clips'][0].update(duration=999)),
 ('insert hors vidéo',lambda p:p['overlays'][0].update(start=9)),
 ('animation non déclarée',lambda p:p['overlays'][0].update(motion='neural_avatar')),
 ('animation photo sur vidéo',lambda p:p['overlays'][0].update(file='demo_media/presentation_demo.mp4',motion='push_in')),
 ('fondu supérieur à demi-durée',lambda p:p['overlays'][0].update(fade=1.9)),
 ('crop hors cadre',lambda p:p['overlays'][0].update(subject_crop=[.7,.5,.7,.9])),
 ('crop négatif',lambda p:p['overlays'][0].update(subject_crop=[-.2,0,.4,.5])),
 ('horodatages sous-titres chevauchants',lambda p:p['words'][1].update(start=.55,end=1.7)),
 ('texte sous-titre trop long',lambda p:p['words'][1].update(text='J'*45)),
 ('mot sans temps mesuré',lambda p:p.update(words=[])),
 ('label publicitaire absent',lambda p:p['product'].update(disclosure='')),
]: assert_rejected(title,edit)

# Segmentation must not group adjacent cuts into one caption.
ww=[{'text':'mot','start':0,'end':.2,'clip':0},{'text':'suivant','start':.21,'end':.4,'clip':1}]
assert len(caption_groups(ww))==2
RESULTS.append('Les groupes sous-titres respectent les coupes de scènes')

safe=platform_guide()
assert 'viewBox="0 0 1080 1920"' in safe and 'BOUTONS PLATEFORME' in safe
RESULTS.append('Guide zone sûre 9:16 généré sans média externe')

video=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'demo_1080x1920.mp4'
assert video.is_file(),f'Vidéo de démonstration absente: {video}'
qa=quality_analyze(video,full_decode=True)
assert qa['structural_pass'] and qa['resolution']==[1080,1920],qa
RESULTS.append('Vidéo 1080x1920 + audio + décodage complet validés')

m=analyze_audio(video)
assert m['measurement_available'] and -19<m['integrated_lufs']<-12 and m['true_peak_dbtp']<=-1,m
RESULTS.append('Mixage mesuré LUFS et true peak dans les marges')

sync=sync_audit(SRC,video)
assert sync['native_audio_preserved'],sync
assert all(len(c['windows'])>=2 for c in sync['clips']),sync
RESULTS.append('Synchronisation source→sortie validée à plusieurs positions')

with tempfile.TemporaryDirectory() as d:
    altered=Path(d)/'altered.mp4'
    # Purely local corruption: shift narration by 95ms; ensures our gate detects it.
    cmd=['ffmpeg','-hide_banner','-nostdin','-loglevel','error','-y','-i',str(video),
        '-map','0:v','-map','0:a','-c:v','copy','-af','adelay=95:all=1','-c:a','aac','-t', '4','-threads','2',str(altered)]
    subprocess.run(cmd,check=True,timeout=80)
    late=sync_audit(SRC,altered)
    assert not late['native_audio_preserved'],late
    shifts=[w.get('estimated_audio_shift_ms') for c in late['clips'] for w in c['windows'] if w['status']=='matched']
    assert shifts and all(70<=v<=120 for v in shifts),late
    RESULTS.append('Une désynchronisation créée de 95 ms est correctement rejetée')

report={'version':'3.0','status':'PASS','functional_checks':len(RESULTS),'results':RESULTS,
        'output_sha256':sha256(video),'lufs':m['integrated_lufs'],'true_peak_dbtp':m['true_peak_dbtp'],
        'sync_audio_shift_ms':[w['estimated_audio_shift_ms'] for c in sync['clips'] for w in c['windows']],
        'external_credit_cost':0,
        'limitation':'Ce test ne valide pas le lip-sync visuel: contrôle humain nécessaire.'}
(ROOT/'functional_results_v3.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(report,ensure_ascii=False,indent=2))
