#!/usr/bin/env python3
"""Page de relecture hors ligne de l'export, pensée pour Android.

Aucun JavaScript réseau, aucun CDN, aucune télémétrie, aucun token.
L'utilisateur conserve la responsabilité de visionner la vidéo et vérifier
l'exactitude du produit, les droits, la parole et le synchronisme phonétique.
"""
from __future__ import annotations
import argparse
import html
import json
import os
from pathlib import Path
from urllib.parse import quote


def _str(x):return html.escape(str(x),quote=True)


def build(video:Path,output:Path,*,report:Path|None=None)->dict:
    video=video.resolve()
    if not video.is_file() or video.suffix.lower()!='.mp4':raise ValueError('MP4 introuvable')
    report=report or video.with_suffix('.report.json')
    if not report.is_file():raise ValueError('Rapport de rendu introuvable; produire le MP4 avec ugc.py render')
    data=json.loads(report.read_text(encoding='utf-8'))
    ed=data.get('editorial_quality')
    if not ed:raise ValueError('Rapport V6 requis (manque editorial_quality)')
    if Path(data.get('output','')).name!=video.name:
        raise ValueError('Rapport et nom du MP4 ne correspondent pas')
    seconds=float(ed['total_seconds'])
    if not 0<seconds<3600:raise ValueError('Durée rapport invalide')
    spans=ed.get('broll_intervals',[])
    bars=[]
    for s,e in spans:
        left=max(0,min(100,s/seconds*100));width=max(0,min(100-left,(e-s)/seconds*100))
        bars.append(f'<div class="cut" style="left:{left:.3f}%;width:{width:.3f}%" title="Insert produit : {s:.1f}–{e:.1f} s"></div>')
    flags=ed.get('flags',[])
    flag_text=''.join('<li>'+_str(x)+'</li>' for x in flags) or '<li>Aucune anomalie de durée ou de couverture détectée</li>'
    audio=data.get('audio_measure',{})
    audio_desc= (f"{audio.get('integrated_lufs')} LUFS · {audio.get('true_peak_dbtp')} dBTP" if audio.get('measurement_available') else 'Mesure indisponible')
    media_path=quote(os.path.relpath(video,output.parent.resolve()).replace(os.sep,'/'),safe='./_-')
    subtitles=video.with_suffix('.srt')
    subtitle_link=(' · <a href="'+_str(quote(os.path.relpath(subtitles,output.parent.resolve()).replace(os.sep,'/'),safe='./_-'))+'">Sous-titres SRT</a>' if subtitles.is_file() else '')
    sync=data.get('sync_audio_gate',{}).get('native_audio_preserved')
    checks=[
        'Ai-je regardé le MP4 intégralement sur un téléphone ?',
        'La voix française est-elle intelligible et correctement prononcée ?',
        'La bouche correspond-elle à chaque phrase (relecture humaine) ?',
        'Le produit, son logo et sa couleur sont-ils exacts ?',
        'Les allégations et les droits des visuels sont-ils documentés ?',
        'Les mentions publicité / IA / affiliation sont-elles présentes ?',
        'Les sous-titres restent-ils lisibles sous les boutons TikTok ?'
    ]
    tasks=''.join('<label class="task"><input type="checkbox"> '+_str(t)+'</label>' for t in checks)
    page=f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>UGC V6 — Contrôle mobile</title><style>
:root{{font-family:system-ui,-apple-system,sans-serif;color-scheme:dark;background:#100f16;color:#f7f4f9}}
*{{box-sizing:border-box}}body{{margin:0 auto;max-width:1080px;padding:16px}}header{{padding:10px 0 18px}}
h1{{font-size:clamp(22px,5vw,36px);margin:0 0 8px}}p{{line-height:1.5;color:#c8bfcd}}
.layout{{display:grid;grid-template-columns:minmax(200px,390px) 1fr;gap:20px}}@media(max-width:720px){{.layout{{grid-template-columns:1fr}}}}
video{{display:block;width:100%;max-height:76vh;border-radius:18px;background:#000;aspect-ratio:9/16;object-fit:contain}}
.card{{background:#201c28;border:1px solid #393244;padding:18px;border-radius:18px;margin-bottom:15px}}
h2{{font-size:18px;margin:0 0 10px}}.metrics{{display:grid;grid-template-columns:1fr 1fr;gap:10px}}
.metric{{background:#302735;border-radius:12px;padding:10px}}.metric b{{font-size:24px;display:block}}.metric span{{font-size:12px;color:#cbc2d1}}
.track{{position:relative;height:32px;border:1px solid #6b536d;border-radius:9px;background:#4c3a53;overflow:hidden;margin:12px 0}}
.cut{{position:absolute;top:0;bottom:0;background:#ffa4ba}}.legend{{font-size:13px}}.legend strong{{color:#ffa4ba}}
.task{{display:block;padding:10px 0;border-bottom:1px solid #3d3543;font-size:15px}}input{{width:19px;height:19px;vertical-align:middle;margin-right:8px;accent-color:#e68aaf}}
ul{{padding-left:20px}}li{{margin:8px 0}}a{{color:#ffa4c0}}.ok{{color:#8bf0b9}}.warn{{color:#ffc09a}}
</style></head><body><header><h1>UGC Zero Credit V6</h1><p>Relecture mobile — aucune API, aucune analyse en ligne. Le contenu ci-dessous est une aide, pas une approbation automatique.</p></header>
<div class="layout"><section><video src="{_str(media_path)}" controls playsinline preload="metadata"></video><p><a href="{_str(media_path)}" download>Télécharger le MP4</a>{subtitle_link}</p></section>
<section><div class="card"><h2>Qualité vérifiée</h2><div class="metrics">
<div class="metric"><b>{_str(data.get('width'))} × {_str(data.get('height'))}</b><span>pixels</span></div>
<div class="metric"><b>{_str(data.get('fps'))}</b><span>images par seconde</span></div>
<div class="metric"><b>{_str('OK' if sync else 'À contrôler')}</b><span>timing audio source → export</span></div>
<div class="metric"><b>{_str(ed.get('speech_covered_ratio'))}</b><span>proportion de parole masquée</span></div></div>
<p>Mixage : {_str(audio_desc)}. Synchronisme phonème/lèvres : non prouvé.</p></div>
<div class="card"><h2>Chronologie des inserts produit</h2><div class="track">{''.join(bars)}</div>
<p class="legend"><strong>Rose</strong> : visage potentiellement masqué par un plan produit. Durée totale : {_str(seconds)} s.</p>
<p>Audit éditorial : <b class="{'ok' if ed['status']=='PASS' else 'warn'}">{_str(ed['status'])}</b></p><ul>{flag_text}</ul></div>
<div class="card"><h2>Validation humaine indispensable</h2>{tasks}<p>Aucune case n'est sauvegardée ou assimilée à une autorisation de publication.</p></div>
</section></div></body></html>'''
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(page,encoding='utf-8')
    return {'html':str(output),'video':str(video),'speech_covered_ratio':ed['speech_covered_ratio'],
            'clips_covered':len(spans),'cost_credits':0,'network_requests':0}


def main():
    p=argparse.ArgumentParser(description='Rapport HTML de relecture TikTok utilisable hors ligne')
    p.add_argument('video');p.add_argument('--output',required=True);p.add_argument('--report')
    args=p.parse_args()
    print(json.dumps(build(Path(args.video),Path(args.output),report=Path(args.report) if args.report else None),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
