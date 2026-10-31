#!/usr/bin/env python3
"""UGC Zero Credit: production/QA locale, sans API, sans réseau, sans TTS imposé.

Python 3.10+, FFmpeg/FFprobe 6+; aucun package Python requis.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from quality_gate import analyze as qa_analyze
from audio_quality import analyze_audio as measure_audio
from sync_audit import audit_timeline
from face_quality import audit_talking_clips
from editorial_quality import analyze as editorial_analyze

ALLOWED_RIGHTS = {"owned", "licensed", "ai_generated"}
MAX_CLIPS = 24
MAX_OVERLAYS = 36
ALLOWED_MOTIONS = {"static", "push_in", "pull_out", "pan_left", "pan_right"}


def fail(message: str) -> None:
    raise ValueError(message)


def run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 900, capture=True):
    result = subprocess.run(cmd, cwd=cwd, text=True, capture_output=capture, timeout=timeout)
    if result.returncode:
        error = (result.stderr or result.stdout or "")[-6000:]
        raise RuntimeError(f"Commande échouée (code {result.returncode}): {' '.join(cmd[:9])}\n{error}")
    return result


def probe(p: Path) -> dict:
    return json.loads(run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)]).stdout)


def get_media_file(root: Path, name: str) -> Path:
    if not isinstance(name, str) or not name or "\x00" in name or "://" in name:
        fail("Les médias doivent être des chemins locaux (aucune URL ni API).")
    local = (root / name).resolve()
    if not local.is_relative_to(root.resolve()):
        fail(f"Chemin extérieur au projet refusé : {name}")
    if not local.is_file():
        fail(f"Média introuvable : {name}")
    return local


def number(item, name, minval=0, exclusive=False):
    v=item.get(name)
    if not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or (v <= minval if exclusive else v < minval):
        fail(f"Champ {name} invalide: {v!r}")
    return float(v)


def load_project(path: Path) -> tuple[dict, Path]:
    p=path.resolve()
    d=json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(d,dict): fail("Projet JSON invalide")
    return d, p.parent


def verify(config: dict, root: Path, *, inspect_media=True) -> dict:
    if config.get("version") != 1: fail("Version de configuration inconnue (attendu 1).")
    info=config.get("product", {})
    if not info.get("name") or not isinstance(info.get("name"),str): fail("Nom du produit obligatoire")
    if info.get("claims_verified") is not True: fail("Les allégations produit doivent être vérifiées et approuvées.")
    if info.get("disclosure") != "PUBLICITÉ · LIEN AFFILIÉ · INFLUENCEUSE IA":
        fail("La mention obligatoire de contenu publicitaire / IA manque.")
    if config.get("forbidden_paid_services",True) is not True:
        fail("Le mode zéro crédit doit rester verrouillé")
    if config.get("editorial_policy", "review") not in {"off", "review", "required"}:
        fail("editorial_policy: attendu off, review ou required")
    if config.get("face_policy", "review") not in {"off", "review", "required"}:
        fail("face_policy: attendu off, review ou required")
    clips=config.get("talking_clips")
    if not isinstance(clips,list) or not 1 <=len(clips)<=MAX_CLIPS:fail("1-24 clips parlés requis")
    overlay=config.get("overlays",[])
    if not isinstance(overlay,list) or len(overlay)>MAX_OVERLAYS: fail("Surcouches incorrectes")
    timeline=[]; total=0.; inventory=[]
    for i,clip in enumerate(clips):
        if clip.get("rights") not in ALLOWED_RIGHTS:fail(f"Clip {i}: droits non vérifiés; REFUS de montage")
        if clip.get("rights")=="licensed" and not clip.get("license_ref"): fail(f"Clip {i}: fournir license_ref pour un contenu tiers")
        if clip.get("sync")!="native":fail(f"Clip {i}: audio et lèvres doivent être natifs; aucun doublage non synchronisé")
        start=number(clip,"source_in"); duration=number(clip,"duration",.09,True)
        smart=clip.get("smart_crop","off")
        if smart not in {"off","face"}: fail(f"Clip {i}: smart_crop doit être off ou face")
        for axis in ("focus_x","focus_y"):
            coord=clip.get(axis,.5)
            if not isinstance(coord,(float,int)) or isinstance(coord,bool) or not math.isfinite(coord) or not 0<=coord<=1:
                fail(f"Clip {i}: {axis} doit être compris entre 0 et 1")
        file=get_media_file(root,clip.get("file"))
        if inspect_media:
            meta=probe(file);vs=[s for s in meta["streams"] if s.get("codec_type")=="video"]
            audio=[s for s in meta["streams"] if s.get("codec_type")=="audio"]
            if not vs or not audio:fail(f"Clip {i}: vidéo ET son obligatoires : {clip['file']}")
            length=float(meta.get("format",{}).get("duration",0))
            if start+duration>length+.05:fail(f"Clip {i}: source_in + duration dépassent la durée source {length:.2f}")
            inventory.append({"file":clip["file"],"sha256":sha256(file),"rights":clip["rights"],"type":"talking_native"})
            sw,sh=int(vs[0]["width"]),int(vs[0]["height"])
        else:sw,sh=0,0
        timeline.append({"file":str(file),"source_in":start,"duration":duration,"timeline_start":total,"index":i,
                         "smart_crop":smart,"focus_x":float(clip.get("focus_x",.5)),"focus_y":float(clip.get("focus_y",.5)),
                         "source_width":sw,"source_height":sh})
        total+=duration
    for i,layer in enumerate(overlay):
        if layer.get("rights") not in ALLOWED_RIGHTS:fail(f"Insert {i}: droits manquants")
        if layer.get("rights")=="licensed" and not layer.get("license_ref"):fail(f"Insert {i}: fournir license_ref pour un contenu tiers")
        t=number(layer,"start"); dur=number(layer,"duration",.05,True)
        if t+dur>total+.001:fail(f"Insert {i} hors de la vidéo : {t+dur:.2f}>{total:.2f}")
        file=get_media_file(root,layer.get("file"))
        if file.suffix.lower() not in (".jpg",".jpeg",".png",".webp",".mp4",".mov",".mkv",".webm"):
            fail(f"Insert {i}: format interdit")
        motion=layer.get("motion","push_in" if file.suffix.lower() in (".jpg",".jpeg",".png",".webp") else "static")
        if motion not in ALLOWED_MOTIONS:fail(f"Insert {i}: mouvement inconnu {motion}")
        crop_region=layer.get("subject_crop")
        if crop_region is not None:
            if file.suffix.lower() not in (".jpg",".jpeg",".png",".webp"):
                fail(f"Insert {i}: subject_crop réservé aux images")
            if (not isinstance(crop_region,list) or len(crop_region)!=4 or
                any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in crop_region)):
                fail(f"Insert {i}: subject_crop doit être [x,y,width,height]")
            x,y,cw,ch=crop_region
            if not (0<=x<1 and 0<=y<1 and 0.1<=cw<=1 and 0.1<=ch<=1 and x+cw<=1.00001 and y+ch<=1.00001):
                fail(f"Insert {i}: rectangle du sujet hors image")
        if file.suffix.lower() in (".mp4",".mov",".mkv",".webm") and motion!="static":
            fail(f"Insert {i}: animation photo seulement (vidéos déjà animées)")
        fade=layer.get("fade",.14)
        if not isinstance(fade,(int,float)) or isinstance(fade,bool) or not math.isfinite(fade) or fade<0 or fade>min(dur/2,.5):
            fail(f"Insert {i}: transition invalide (max 0.5 s et moitié de la durée)")
        fx=layer.get("focus_x",.5);fy=layer.get("focus_y",.5)
        if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) or not 0<=v<=1 for v in (fx,fy)):
            fail("Point de focalisation incorrect (0..1)")
        if inspect_media:
            meta=probe(file)
            if not any(s.get("codec_type")=="video" for s in meta["streams"]):fail("Insert sans piste vidéo")
            if file.suffix.lower() in (".mp4",".mov",".mkv",".webm"):
                start=number(layer,"source_in")
                length=float(meta.get("format",{}).get("duration",0))
                if start+dur>length+.05:fail(f"Insert {i} dépasse la source")
            inventory.append({"file":layer["file"],"sha256":sha256(file),"rights":layer["rights"],"type":"product_overlay"})
    music=config.get("music")
    if music:
        if music.get("rights") not in ALLOWED_RIGHTS:fail("Droits musique absents")
        if music.get("rights")=="licensed" and not music.get("license_ref"): fail("Musique tierce: license_ref obligatoire")
        file=get_media_file(root,music.get("file"))
        if inspect_media:
            meta=probe(file)
            if not any(s.get("codec_type")=="audio" for s in meta["streams"]):fail("Fichier musique sans audio")
            inventory.append({"file":music["file"],"sha256":sha256(file),"rights":music["rights"],"type":"music"})
    words=config.get("words",[])
    if not isinstance(words,list):fail("Les mots doivent être une liste")
    positioned=[]; perclip={i:[] for i in range(len(clips))}
    for w in words:
        i=w.get("clip");st=number(w,"start");en=number(w,"end")
        if not isinstance(i,int) or i not in perclip or en<=st:fail("Mot: clip/start/end incorrect")
        if not isinstance(w.get("text"),str) or not w["text"].strip(): fail("Mot sans texte")
        c=timeline[i]
        if st<c["source_in"]-.03 or en>c["source_in"]+c["duration"]+.03:
            fail(f"Mot {w['text']}: timing hors de la coupe vidéo {i}")
        positioned.append({"text":w["text"].strip(),"start":max(0.,c["timeline_start"]+st-c["source_in"]),"end":min(total,c["timeline_start"]+en-c["source_in"]),"clip":i})
        perclip[i].append(w)
    positioned.sort(key=lambda w:w["start"])
    for word in positioned:
        if len(word["text"]) > 38:fail("Mot de sous-titre trop long (plus de 38 caractères)")
        if word["end"] - word["start"] > 3.0:fail("Mot sous-titré pendant plus de 3 secondes: contrôler le minutage")
    for w0,w1 in zip(positioned,positioned[1:]):
        if w0["end"]>w1["start"]+.04:fail("Les sous-titres se chevauchent (horodatages invalides)")
    if config.get("caption_mode","words")=="words" and not positioned:
        fail("Sous-titres mot-à-mot demandés, mais aucun horodatage fourni : ne pas en inventer.")
    editorial=[]
    if not info.get("evidence_urls"):
        editorial.append("Revoir les preuves des allégations : aucun lien de référence dans product.evidence_urls")
    if not info.get("product_reference"):
        editorial.append("Vérifier visuellement le packaging exact du produit avec une photo source")
    for i,clip in enumerate(clips):
        dialogue=clip.get("spoken_script","")
        if dialogue and not isinstance(dialogue,str):fail("spoken_script doit être une chaîne")
        if isinstance(dialogue,str) and re.search(r"(?i)je l.ai testé|je l.ai reçu|j.ai essayé|j.ai reçu",dialogue):
            editorial.append(f"Clip {i}: témoignage personnel détecté ; interdire si influenceuse fictive")
    return {"total_duration":total,"talking":timeline,"words":positioned,"inventory":inventory,
            "warnings":([] if positioned else ["Pas de sous-titres : aucun horodatage fourni"]),
            "editorial_review":editorial}


def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1048576),b""):h.update(block)
    return h.hexdigest()


def fmt_time(t: float):
    h=int(t//3600);m=int(t//60)%60;s=t%60
    return f"{h}:{m:02d}:{s:05.2f}"


def ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{","\\{").replace("}","\\}").replace("\n"," ")


def ASS_color(hexcolor):
    hexcolor=hexcolor.lstrip("#")
    return f"&H00{hexcolor[4:6]}{hexcolor[2:4]}{hexcolor[:2]}"


def caption_groups(words:list[dict], *, limit=28, max_words=5, silence=.45) -> list[list[dict]]:
    """Group stable captions without bridging speaker/cut/silence boundaries.

    Every timestamp comes from source audio; no ASR times are interpolated.
    """
    groups=[];current=[]
    for word in words:
        if current and (word.get("clip") != current[-1].get("clip") or
            word["start"]-current[-1]["end"] > silence or len(current)>=max_words or
            sum(len(x["text"])+1 for x in current)+len(word["text"])>limit):
            groups.append(current);current=[]
        current.append(word)
    if current:groups.append(current)
    return groups


def write_captions(path:Path, words:list[dict],duration:float, width:int,height:int,disclosure:str):
    """Captions persist through short gaps: no blinking between adjacent words."""
    fs=round(width*.049); upper=int(height*.105)
    margin_v=int(height*.23)
    header=f"""[Script Info]
Title: UGC Zero Credit V3 — sous-titres à groupes persistants
ScriptType: v4.00+
PlayResX: {width}
PlayResY: {height}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,DejaVu Sans,{fs},&H00FFFFFF,&H00FFFFFF,&H00220D1C,&H68000000,-1,0,0,0,100,100,0,0,1,5,1,2,{int(width*.09)},{int(width*.16)},{margin_v},1
Style: Label,DejaVu Sans,{int(fs*.49)},&H00FFFFFF,&H00FFFFFF,&H00220D1C,&H68000000,-1,0,0,0,100,100,0,0,1,3,1,8,35,35,{upper},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines=[header]
    lines.append(f"Dialogue: 1,{fmt_time(0)},{fmt_time(duration)},Label,,0,0,0,,{ass_escape(disclosure)}\n")
    groups=caption_groups(words)
    # One full caption is displayed throughout its acoustic group, including
    # natural gaps. Highlight state changes at the next real word onset.
    for gi,group in enumerate(groups):
        for i,w in enumerate(group):
            left=" ".join(ass_escape(z["text"]) for z in group[:i]);active=ass_escape(w["text"])
            right=" ".join(ass_escape(z["text"]) for z in group[i+1:])
            if left:left+=" "
            if right:right=" "+right
            content=left+"{\\c&H00D5AEFF&}"+active+"{\\c&H00FFFFFF&}"+right
            start=w['start']
            if i+1<len(group): end=group[i+1]['start']
            else:
                next_start=groups[gi+1][0]['start'] if gi+1<len(groups) else duration
                end=min(w['end']+.11,next_start-.015,duration)
            if end-start <.01:end=start+.015
            lines.append(f"Dialogue: 0,{fmt_time(start)},{fmt_time(end)},Caption,,0,0,0,,{content}\n")
    path.write_text("".join(lines),encoding="utf-8")


def write_srt(path: Path, words: list[dict]):
    """Editable SRT from the same source-measured stable caption groups."""
    chunks=caption_groups(words)
    def stamp(t):
        n=round(t*1000);h=n//3600000;m=n//60000%60;sc=n//1000%60;ms=n%1000
        return f"{h:02}:{m:02}:{sc:02},{ms:03}"
    lines=[]
    for i,chunk in enumerate(chunks,1):
        lines.extend([str(i),stamp(chunk[0]["start"])+" --> "+stamp(chunk[-1]["end"])," ".join(z["text"] for z in chunk),""])
    path.write_text("\n".join(lines)+"\n",encoding="utf-8")


def image_motion(width:int,height:int,fps:int,duration:float,focus_x:float,focus_y:float,motion:str) -> str:
    """Actual zoom/pan (not slides), deterministic at output-frame rate."""
    n=max(2,math.ceil(duration*fps));progress=f"min(on/{n-1},1)"
    if motion=="static":z="1";x=f"(iw-iw/zoom)*{focus_x:.4f}";y=f"(ih-ih/zoom)*{focus_y:.4f}"
    elif motion=="push_in":z=f"1+0.08*{progress}";x=f"(iw-iw/zoom)*{focus_x:.4f}";y=f"(ih-ih/zoom)*{focus_y:.4f}"
    elif motion=="pull_out":z=f"1.09-0.09*{progress}";x=f"(iw-iw/zoom)*{focus_x:.4f}";y=f"(ih-ih/zoom)*{focus_y:.4f}"
    elif motion=="pan_left":z="1.09";x=f"(iw-iw/zoom)*(0.85-0.70*{progress})";y=f"(ih-ih/zoom)*{focus_y:.4f}"
    else:z="1.09";x=f"(iw-iw/zoom)*(0.15+0.70*{progress})";y=f"(ih-ih/zoom)*{focus_y:.4f}"
    return f"zoompan=z='{z}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"


def scale_cover(idx, width:int, height:int, focus_x:float=.5, focus_y:float=.5, *, factor=1.0) -> str:
    # Le recadrage se fait en pixels, le focus évite de couper le visage/produit.
    w=round(width*factor); h=round(height*factor)
    return (f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
            f"crop={width}:{height}:x='(in_w-out_w)*{focus_x:.4f}':y='(in_h-out_h)*{focus_y:.4f}',"
            f"setsar=1")


def face_aware_crop(detection:dict, source_width:int,source_height:int,
                    output_width:int,output_height:int, *, desired_x=.48, desired_y=.40) -> tuple[float,float]:
    """Center subject in safe zone after cover scaling, not merely take source x%.

    Returns the crop offset fraction used by FFmpeg scale_cover. Safe when the
    source already is 9:16, and avoids pushing a face into right-side buttons.
    """
    center=detection.get("face_center_normalized")
    if not center or not source_width or not source_height:return .5,.5
    scale=max(output_width/source_width,output_height/source_height)
    sw=source_width*scale;sh=source_height*scale
    dx=sw-output_width;dy=sh-output_height
    x=(center[0]*sw-desired_x*output_width)/dx if dx>1 else .5
    y=(center[1]*sh-desired_y*output_height)/dy if dy>1 else .5
    return round(max(0,min(1,x)),4),round(max(0,min(1,y)),4)


def protect_output_path(output: Path, checked: dict, config: dict, root: Path) -> None:
    """Refuse any export that could overwrite footage, images or music.

    Resolve links before comparing: alias paths must not bypass protection.
    """
    if output.suffix.lower() != ".mp4":
        fail("Le nom d'export doit finir par .mp4")
    protected = {Path(x["file"]).resolve() for x in checked["talking"]}
    protected.update(get_media_file(root, x["file"]).resolve() for x in config.get("overlays", []))
    if config.get("music"):
        protected.add(get_media_file(root, config["music"]["file"]).resolve())
    out = output.resolve()
    sidecars = [out, out.with_suffix(".ass"), out.with_suffix(".srt"), out.with_suffix(".qa.json"), out.with_suffix(".report.json"), out.with_suffix(".jpg")]
    if any(p in protected for p in sidecars):
        fail("Export refusé : le MP4 ou un fichier de rapport écraserait un média source")
    if out.is_dir():
        fail("Chemin d'export incorrect : dossier")


def build(config:dict,root:Path, output:Path, *,preview=False, full_decode=True, strict_sync=True,
          face_policy_override=None) -> dict:
    checked=verify(config,root)
    protect_output_path(output, checked, config, root)
    face_policy=face_policy_override or config.get("face_policy", "review")
    if face_policy not in {"off","review","required"}:fail("face_policy invalide")
    editorial_policy=config.get("editorial_policy", "review")
    if editorial_policy not in {"off", "review", "required"}:
        fail("editorial_policy doit être off, review ou required")
    editorial_report=editorial_analyze(checked,config.get("overlays",[]))
    if editorial_policy=="required" and editorial_report["status"]!="PASS":
        fail("Audit éditorial strict échoué: " + ", ".join(editorial_report["flags"]))
    face_report=audit_talking_clips(checked["talking"],policy=face_policy)
    if face_policy=="required" and not face_report["passes_required_gate"]:
        fail("Audit visage obligatoire échoué: " + "; ".join(
            f"clip {z['clip_index']} : {z.get('reason','')}" for z in face_report['clips'] if z['status']!='pass'))
    face_by_index={z["clip_index"]:z for z in face_report["clips"]}
    w=360 if preview else 1080;h=w*16//9;fps=15 if preview else 30
    total=checked["total_duration"]
    output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".ugc-zero-credit-", dir=output.parent) as tmp:
        tmpdir=Path(tmp)
        ass=tmpdir/"captions.ass"
        write_captions(ass,checked["words"],total,w,h,config["product"]["disclosure"])
        command=["ffmpeg","-hide_banner","-nostdin","-y","-loglevel","error"]
        for clip in checked["talking"]:command.extend(["-i",clip["file"]])
        overlay=config.get("overlays",[]);root2=root.resolve()
        for lay in overlay:
            p=get_media_file(root2,lay["file"])
            if p.suffix.lower() in (".png",".jpg",".jpeg",".webp"):
                command.extend(["-loop","1","-framerate",str(fps),"-t",str(lay["duration"]),"-i",str(p)])
            else:command.extend(["-i",str(p)])
        music_idx=None
        if config.get("music"):
            music_idx=len(checked["talking"])+len(overlay)
            command.extend(["-stream_loop","-1","-i",str(get_media_file(root2,config["music"]["file"]))])
        chain=[]
        for i,clip in enumerate(checked["talking"]):
            t=clip["source_in"];d=clip["duration"]
            fx,fy=clip["focus_x"],clip["focus_y"]
            detection=face_by_index.get(i,{})
            if clip["smart_crop"]=="face" and detection.get("face_center_normalized"):
                fx,fy=face_aware_crop(detection,clip["source_width"],clip["source_height"],w,h)
                detection["auto_crop_focus"]=[fx,fy]
            chain.append(f"[{i}:v]trim=start={t:.6f}:duration={d:.6f},setpts=PTS-STARTPTS,{scale_cover(i,w,h,fx,fy)},fps={fps},format=yuv420p[v{i}]")
            chain.append(f"[{i}:a]atrim=start={t:.6f}:duration={d:.6f},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,apad,atrim=duration={d:.6f}[a{i}]")
        inputs="".join(f"[v{i}][a{i}]" for i in range(len(checked["talking"])))
        chain.append(f"{inputs}concat=n={len(checked['talking'])}:v=1:a=1[mainv][maina]")
        current="mainv"
        for j,layer in enumerate(overlay):
            idx=len(checked["talking"])+j
            start=float(layer["start"]);d=float(layer["duration"])
            fx=float(layer.get("focus_x",.5));fy=float(layer.get("focus_y",.5))
            src=get_media_file(root2,layer["file"])
            # Les frames B-roll ne transmettent JAMAIS de son: l'influenceuse continue de parler.
            if src.suffix.lower() in (".jpg",".jpeg",".png",".webp"):
                # Photo: vraie animation Ken Burns calculée sur les images source.
                # Aucun modèle génératif, aucune API, aucune image synthétique ajoutée.
                motion=layer.get("motion","push_in")
                scale=scale_cover(idx,w,h,fx,fy)
                crop_region=layer.get("subject_crop")
                crop_filter=""
                if crop_region is not None:
                    cx,cy,cw,ch=crop_region
                    crop_filter=f"crop=iw*{cw:.5f}:ih*{ch:.5f}:iw*{cx:.5f}:ih*{cy:.5f},"
                source=f"[{idx}:v]trim=duration={d:.6f},setpts=PTS-STARTPTS,{crop_filter}{scale},fps={fps},"
                source+=image_motion(w,h,fps,d,fx,fy,motion)+f",trim=duration={d:.6f},setpts=PTS-STARTPTS"
            else:
                src_in=number(layer,"source_in")
                source=f"[{idx}:v]trim=start={src_in:.6f}:duration={d:.6f},setpts=PTS-STARTPTS,{scale_cover(idx,w,h,fx,fy)},fps={fps}"
            fade=float(layer.get("fade",.14))
            if fade>0:
                source+=f",format=yuva420p,fade=t=in:st=0:d={fade:.5f}:alpha=1,fade=t=out:st={max(0,d-fade):.5f}:d={fade:.5f}:alpha=1"
            else:source+=",format=yuva420p"
            chain.append(source+f",setpts=PTS+{start:.6f}/TB[ov{j}]")
            to=f"vid{j}"
            chain.append(f"[{current}][ov{j}]overlay=x=0:y=0:enable='between(t,{start:.6f},{start+d-.0001:.6f})':eof_action=pass:repeatlast=0:shortest=0[{to}]")
            current=to
        chain.append(f"[{current}]ass=filename=captions.ass,format=yuv420p[video]")
        if music_idx is not None:
            vol=float(config["music"].get("volume",.14))
            if not 0<=vol<=.3:fail("Musique trop forte; volume limité à 0..0.30")
            chain.append(f"[maina]asplit=2[voice][side]")
            chain.append(f"[{music_idx}:a]atrim=duration={total:.6f},asetpts=PTS-STARTPTS,aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo,volume={vol:.3f}[bg]")
            chain.append("[bg][side]sidechaincompress=threshold=0.02:ratio=8:attack=15:release=300[ducked]")
            chain.append("[voice][ducked]amix=inputs=2:duration=first:normalize=0:dropout_transition=0[rawa]")
        else:chain.append("[maina]anull[rawa]")
        chain.append(f"[rawa]atrim=duration={total:.6f},loudnorm=I=-16:TP=-1.5:LRA=11,aresample=48000[audio]")
        output_tmp=tmpdir/"render.mp4"
        command.extend(["-filter_complex",";".join(chain),"-map","[video]","-map","[audio]","-c:v","libx264","-preset",("ultrafast" if preview else "veryfast"),"-crf",("25" if preview else "20"),"-pix_fmt","yuv420p","-r",str(fps),"-c:a","aac","-b:a","160k","-ar","48000","-movflags","+faststart","-t",f"{total:.3f}","-threads","2",str(output_tmp)])
        run(command,cwd=tmpdir,timeout=1800)
        media=probe(output_tmp)
        vs=[z for z in media["streams"] if z.get("codec_type")=="video"]
        au=[z for z in media["streams"] if z.get("codec_type")=="audio"]
        if not vs or not au:fail("Sortie incomplète : vidéo ou son absent")
        if int(vs[0]["width"])!=w or int(vs[0]["height"])!=h:fail("Format vidéo incorrect")
        if abs(float(media["format"]["duration"])-total)>.25:fail("Durée MP4 incorrecte")
        if full_decode:
            run(["ffmpeg","-v","error","-xerror","-i",str(output_tmp),"-f","null","-"],timeout=900)
        # QA AVANT publication : une sortie antérieure valide n'est jamais
        # écrasée par un encodage décodable mais structurellement défectueux.
        qa=qa_analyze(output_tmp,full_decode=False)
        # The full decode above has already run; do not claim it was skipped.
        qa["full_decode_verified_by_exporter"]=bool(full_decode)
        if not qa["structural_pass"]:fail("Contrôle qualité structurel échoué : "+", ".join(qa["fatal"]))
        audio_measure=measure_audio(output_tmp)
        if not audio_measure["measurement_available"]:
            qa["warnings"].append("Mesure LUFS/true peak indisponible : contrôle manuel audio nécessaire")
        else:
            qa["warnings"].extend(audio_measure["warnings"])
        # Native audio timing is checked at multiple positions BEFORE publication.
        sync_report=audit_timeline(checked["talking"],output_tmp)
        if strict_sync and not sync_report["native_audio_preserved"]:
            fail("Décalage sonore source→export détecté ; publication bloquée")
        # Source-safe atomic replace on THE SAME filesystem, after mandatory QA gates.
        os.replace(output_tmp,output)
        (output.with_suffix(".ass")).write_text(ass.read_text(encoding="utf-8"),encoding="utf-8")
        write_srt(output.with_suffix(".srt"),checked["words"])
    qa["path"]=str(output)
    output.with_suffix(".qa.json").write_text(json.dumps(qa,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    report={"output":str(output),"duration":total,"width":w,"height":h,"fps":fps,"audio":"native preserved; sidechain background music optional","subtitle_words":len(checked["words"]),"caption_groups":len(caption_groups(checked["words"])),"editorial_review":checked["editorial_review"],"zero_credit":True,"no_network":True,"sha256":sha256(output),"inventory":checked["inventory"],"audio_measure":audio_measure,"sync_audio_gate":sync_report,"face_visual_gate":face_report,"editorial_quality":editorial_report,"publication":{"automatic_publish":False,"human_review_required":True,"structurally_valid":True,"ready_for_manual_review":True,"visual_speaker_gate_status":face_report["status"]},"quality_gate":{"ffprobe":True,"full_decode":full_decode,"atomic_publish":True,"signals":qa["signal_detections"],"warnings":qa["warnings"]},"human_review_required":["alignement lèvres / phonèmes: non mesuré par le pipeline (audit visuel = détection de bouche figée uniquement)", "emballage produit et publicités exactes", "droits des médias et voix", "intelligibilité du français"]}
    output.with_suffix(".report.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    # Miniature 9:16 : extraction d’une vraie frame du rendu final (sans génération payante).
    cover_at=min(1.2,total*.35)
    run(["ffmpeg","-hide_banner","-loglevel","error","-nostdin","-y","-ss",f"{cover_at:.3f}","-i",str(output),"-frames:v","1", "-q:v","3",str(output.with_suffix(".jpg"))],timeout=60)
    return report


def inspect(path:Path,full_decode=False) ->dict:
    meta=probe(path);vs=[s for s in meta["streams"] if s.get("codec_type")=="video"];aud=[s for s in meta["streams"] if s.get("codec_type")=="audio"]
    if not vs or not aud:fail("Il manque une piste audio ou vidéo")
    v=vs[0];info={"file":str(path),"width":v["width"],"height":v["height"],"rate":v["avg_frame_rate"],"seconds":float(meta["format"]["duration"]),"video_codec":v.get("codec_name"),"audio_codec":aud[0].get("codec_name"),"sha256":sha256(path)}
    if int(v["width"])*16 != int(v["height"])*9: info["warning"]="Ce MP4 n'est pas 9:16"
    if full_decode:run(["ffmpeg","-v","error","-xerror","-i",str(path),"-f","null","-"]);info["full_decode"]="passed"
    return info


def platform_guide() -> str:
    """SVG preview, platform controls are approximate; TikTok UI can vary."""
    return """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1080 1920">
<rect width="1080" height="1920" fill="#291827"/>
<rect x="0" y="0" width="1080" height="320" fill="#E55E7E" fill-opacity=".35"/>
<rect x="875" y="300" width="205" height="1380" fill="#E55E7E" fill-opacity=".35"/>
<rect x="0" y="1550" width="1080" height="370" fill="#E55E7E" fill-opacity=".35"/>
<rect x="110" y="330" width="745" height="1190" rx="28" fill="#7EE0AC" fill-opacity=".15" stroke="#7EE0AC" stroke-width="6"/>
<g fill="white" font-family="DejaVu Sans, sans-serif" font-weight="bold" text-anchor="middle">
<text x="540" y="205" font-size="45">ZONE HAUTE : CONTRÔLES VARIABLES</text>
<text x="965" y="970" font-size="32" transform="rotate(-90 965 970)">BOUTONS PLATEFORME</text>
<text x="540" y="1795" font-size="42">LÉGENDE / CTA / NAVIGATION</text>
<text x="480" y="820" font-size="54">ZONE VISUELLE SÛRE</text>
<text x="480" y="895" font-size="35">Lèvres, produit, démonstration</text>
<text x="480" y="1425" font-size="33">Sous-titres : vérifier sur téléphone</text>
</g></svg>"""


def main():
    p=argparse.ArgumentParser(description="UGC Zéro Crédit · FFmpeg local · jamais d'API générative")
    s=p.add_subparsers(dest="cmd",required=True)
    a=s.add_parser("check");a.add_argument("project");a.add_argument("--strict-editorial",action="store_true")
    a=s.add_parser("render");a.add_argument("project");a.add_argument("--output",required=True);a.add_argument("--preview",action="store_true");a.add_argument("--skip-full-decode",action="store_true");a.add_argument("--skip-sync-gate",action="store_true");a.add_argument("--require-speaking-face",action="store_true")
    a=s.add_parser("audit");a.add_argument("video");a.add_argument("--full-decode",action="store_true")
    a=s.add_parser("qa");a.add_argument("video");a.add_argument("--full-decode",action="store_true")
    a=s.add_parser("plan");a.add_argument("project")
    a=s.add_parser("guide");a.add_argument("--output",default="safe_zones_9x16.svg")
    a=s.add_parser("audio-qa");a.add_argument("video")
    a=s.add_parser("face-qa");a.add_argument("project");a.add_argument("--strict",action="store_true")
    a=s.add_parser("doctor");a.add_argument("--path",default=".")
    a=s.add_parser("editorial");a.add_argument("project");a.add_argument("--strict",action="store_true");a.add_argument("--output")
    a=s.add_parser("assets");a.add_argument("project");a.add_argument("--output")
    a=s.add_parser("autoplan");a.add_argument("project");a.add_argument("--output",required=True);a.add_argument("--report")
    a=s.add_parser("review");a.add_argument("video");a.add_argument("--output",required=True)
    args=p.parse_args()
    try:
        if args.cmd=="guide":
            target=Path(args.output)
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text(platform_guide(),encoding="utf-8")
            res={"guide":str(target),"dimensions":[1080,1920],"cost_credits":0}
        elif args.cmd=="audio-qa":res=measure_audio(Path(args.video))
        elif args.cmd=="doctor":
            from environment_doctor import doctor
            res=doctor(Path(args.path))
        elif args.cmd=="audit":res=inspect(Path(args.video),args.full_decode)
        elif args.cmd=="editorial":
            from editorial_quality import for_project
            res=for_project(Path(args.project))
            if args.output:Path(args.output).write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
            if args.strict and res["status"]!="PASS":
                print(json.dumps(res,ensure_ascii=False,indent=2));sys.exit(3)
        elif args.cmd=="review":
            from review_dashboard import build as make_dashboard
            res=make_dashboard(Path(args.video),Path(args.output))
        elif args.cmd=="autoplan":
            from auto_edit import make_plan
            res=make_plan(Path(args.project),Path(args.output),Path(args.report) if args.report else None)
            if res["status"]!="PASS":
                print(json.dumps(res,ensure_ascii=False,indent=2));sys.exit(3)
        elif args.cmd=="assets":
            from visual_assets import inspect_assets
            res=inspect_assets(Path(args.project))
            if args.output:Path(args.output).write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        elif args.cmd=="qa":res=qa_analyze(Path(args.video),full_decode=args.full_decode)
        else:
            c,root=load_project(Path(args.project))
            if args.cmd=="face-qa":
                res=audit_talking_clips(verify(c,root)["talking"],policy="required" if args.strict else "review")
                if args.strict and not res["passes_required_gate"]:
                    print(json.dumps(res,ensure_ascii=False,indent=2));sys.exit(3)
            elif args.cmd=="check":
                res=verify(c,root)
                if args.strict_editorial and res["editorial_review"]:
                    fail("Points éditoriaux non résolus : "+"; ".join(res["editorial_review"]))
            elif args.cmd=="plan":
                v=verify(c,root)
                res={"product":c["product"]["name"],"total_duration":v["total_duration"],"talking_timeline":v["talking"],"overlays":[{"file":x["file"],"start":x["start"],"end":round(x["start"]+x["duration"],3)} for x in c.get("overlays",[])],"caption_words":len(v["words"]),"caption_groups":len(caption_groups(v["words"])),"editorial_review":v["editorial_review"],"editorial_quality":editorial_analyze(v,c.get("overlays",[])),"paid_services":0}
            else:res=build(c,root,Path(args.output).resolve(),preview=args.preview,full_decode=not args.skip_full_decode,strict_sync=not args.skip_sync_gate,face_policy_override="required" if args.require_speaking_face else None)
        print(json.dumps(res,ensure_ascii=False,indent=2))
    except (ValueError,RuntimeError,FileNotFoundError,subprocess.TimeoutExpired) as e:
        print("ÉCHEC :",e,file=sys.stderr);sys.exit(2)

if __name__=="__main__":main()
