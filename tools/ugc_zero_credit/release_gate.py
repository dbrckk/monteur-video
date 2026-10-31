#!/usr/bin/env python3
"""Fail-closed publication readiness check for an existing UGC export.

No automated visual detector can establish truthful product claims, genuine
lip-to-phoneme synchronization, rights, or approval from the actual influencer.
Those decisions require explicitly documented human review.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from ugc import load_project,verify,sha256
from quality_gate import analyze as analyze_video
from sync_audit import audit_timeline
from audio_quality import analyze_audio
from editorial_quality import analyze as analyze_edit

REQUIRED_REVIEWS={
    'product_packaging':'Produit visible et packaging conformes aux références',
    'spoken_french':'Parole intelligible, prononciation des marques correctement écoutée',
    'lip_sync_human':'Lèvres vérifiées visuellement, pas seulement audio synchronisé',
    'caption_accuracy':'Sous-titres comparés au son réel et aux noms du produit',
    'claims_evidence':'Chaque allégation vérifiée à partir de sources conservées',
    'commercial_rights':'Tous les médias, voix et personnages autorisés commercialement',
    'disclosure_platform':'Mentions publicité/IA et étiquettes plateforme prévues',
    'smartphone_review':'Lisibilité, cadrage et CTA vérifiés sur écran mobile'
}


def read_json(path):
    if not Path(path).is_file():return None
    return json.loads(Path(path).read_text(encoding='utf-8'))


def assess(project:Path,video:Path,*,approvals:Path|None=None,full_decode=False):
    config,root=load_project(project)
    checked=verify(config,root)
    video=video.resolve()
    if not video.is_file():raise ValueError('Vidéo finale inexistante')
    failures=[];reviews=[];warnings=[]
    editorial=analyze_edit(checked,config.get('overlays',[]))
    if config.get('editorial_policy','review')=='required' and editorial['status']!='PASS':
        failures.append('Montage éditorial non conforme (inserts pendant la parole)')
    elif editorial['status']=='WARN':
        warnings.append('Montage à revoir : '+', '.join(editorial['flags']))
    qa=analyze_video(video,full_decode=full_decode)
    if not qa['structural_pass']:failures+=qa['fatal']
    if qa['resolution'] != [1080,1920]:failures.append('Publication Full HD 1080×1920 requise')
    if full_decode and qa.get('full_decode') is not True:failures.append('Décodage complet requis')
    sync=audit_timeline(checked['talking'],video)
    if not sync['native_audio_preserved']:failures.append('Synchronisation audio native source→sortie non validée')
    measured=analyze_audio(video)
    if not measured['measurement_available']:failures.append('Mesure intégrée LUFS/true peak indisponible')
    elif measured['true_peak_dbtp'] > -1.0:failures.append('True peak trop élevé (> −1 dBTP)')
    if qa.get('warnings'):warnings.extend(qa['warnings'])
    if measured.get('warnings'):warnings.extend(measured['warnings'])
    report_file=video.with_suffix('.report.json')
    report=read_json(report_file)
    if not report:
        failures.append('Rapport d’export natif manquant: '+str(report_file.name))
    else:
        if report.get('sha256')!=sha256(video):failures.append('Empreinte SHA-256 de la vidéo différente du rapport')
        if config.get('editorial_policy','review')=='required' and                 report.get('editorial_quality',{}).get('status')!='PASS':
            failures.append('Rapport d’audit éditorial strict absent ou non validé')
        claimed=report.get('inventory',[])
        actual={ (x['file'],x['type']):x['sha256'] for x in checked['inventory'] }
        if not claimed:failures.append('Inventaire des médias source manquant')
        for x in claimed:
            if actual.get((x.get('file'),x.get('type'))) != x.get('sha256'):
                failures.append('Un média d’origine a changé après export: '+str(x.get('file')))
        gate=report.get('face_visual_gate',{})
        if gate.get('status')!='pass':failures.append('Présentatrice non validée par le contrôle visuel local')
        if report.get('quality_gate',{}).get('full_decode') is not True:
            failures.append('Le rapport d’export ne confirme pas le décodage intégral')
        if report.get('zero_credit') is not True or report.get('no_network') is not True:
            failures.append('Le rapport ne garantit pas le mode sans crédits/réseau')
    product=config['product']
    if not product.get('product_reference'):
        failures.append('Référence/visuel produit non documenté (product.product_reference)')
    if not product.get('evidence_urls'):
        failures.append('Sources des allégations non documentées (product.evidence_urls)')
    if not checked['words']:
        failures.append('Aucun sous-titre acoustiquement horodaté')
    a=read_json(approvals) if approvals else None
    if not a:failures.append('Fiche d’approbation humaine absente (voir approvals.template.json)')
    else:
        if not a.get('reviewer') or len(str(a['reviewer']).strip())<3:
            failures.append('Identifiant du relecteur obligatoire')
        if a.get('video_sha256')!=sha256(video):
            failures.append('Approbations non liées à l’empreinte SHA-256 du MP4 courant')
        for key,what in REQUIRED_REVIEWS.items():
            if a.get('reviews',{}).get(key) is not True:reviews.append(what)
    if reviews:failures.append('Relectures manuelles non validées ('+str(len(reviews))+')')
    return {'version':'6.0','video':str(video),'sha256':sha256(video),
            'status':'READY_FOR_MANUAL_POSTING' if not failures else 'BLOCKED',
            'automatically_posted':False,'failures':failures,'manual_reviews_outstanding':reviews,
            'warnings':warnings,'video_qa':{'resolution':qa['resolution'],'fps':qa['fps'],
                                           'duration':qa['duration'],'full_decode':qa['full_decode']},
            'audio_measure':measured,'audio_sync_pass':sync['native_audio_preserved'],'editorial_quality':editorial,
            'human_lip_sync_proven_by_software':False,'cost_credits':0,'network_requests':0,
            'notice':'Le contrôle humain reste obligatoire. Aucun upload/publication automatique.'}


def main():
    p=argparse.ArgumentParser(description='Prépublication TikTok/Shorts : contrôles locaux et approbation humaine')
    p.add_argument('project');p.add_argument('video');p.add_argument('--approvals')
    p.add_argument('--report');p.add_argument('--full-decode',action='store_true')
    a=p.parse_args()
    try:r=assess(Path(a.project),Path(a.video),approvals=Path(a.approvals) if a.approvals else None,full_decode=a.full_decode)
    except (RuntimeError,ValueError,FileNotFoundError) as e:
        print(json.dumps({'status':'BLOCKED','error':str(e)},ensure_ascii=False));raise SystemExit(2)
    if a.report:Path(a.report).write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(r,ensure_ascii=False,indent=2))
    if r['status']=='BLOCKED':raise SystemExit(3)

if __name__=='__main__':main()
