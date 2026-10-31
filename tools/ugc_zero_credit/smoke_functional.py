#!/usr/bin/env python3
"""Tests fonctionnels sans framework, sans appels réseau et sans API payante."""
import copy,json,subprocess,sys,tempfile
from pathlib import Path
from ugc import load_project,verify
from quality_gate import analyze
root=Path(__file__).resolve().parent
base,assets=load_project(root/'examples/synthetic_demo.json')
passed=[]
verify(base,assets);passed.append('projet valide accepté')
for label,mutator in [
 ('droits absents',lambda p:p['talking_clips'][0].update(rights='unknown')),
 ('doublage non synchronisé',lambda p:p['talking_clips'][0].update(sync='dubbed')),
 ('crédits payants',lambda p:p.update(forbidden_paid_services=False)),
 ('mots sans horodatage',lambda p:p.update(words=[])),
 ('média externe',lambda p:p['talking_clips'][0].update(file='https://example.com/video.mp4')),
 ('fichier hors dossier',lambda p:p['talking_clips'][0].update(file='../../../../etc/passwd')),
 ('insert hors timeline',lambda p:p['overlays'][0].update(start=9)),
 ('mots trop longs',lambda p:p['words'][0].update(text='A'*45)),
]:
    test=copy.deepcopy(base);mutator(test)
    try:verify(test,assets)
    except (ValueError,RuntimeError):passed.append(label+' rejeté')
    else:raise AssertionError(label+' non rejeté')
vid=root/'demo_1080x1920.mp4'
assert vid.exists()
qa=analyze(vid,full_decode=True)
assert qa['structural_pass'],qa
passed.append('MP4 1080x1920 + audio + décodage vérifiés')
print(json.dumps({'functional_checks':len(passed),'results':passed,'status':'PASS'},indent=2,ensure_ascii=False))
