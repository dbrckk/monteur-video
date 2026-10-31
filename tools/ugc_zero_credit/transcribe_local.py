#!/usr/bin/env python3
"""Horodatages mot-à-mot avec modèle Whisper déjà INSTALLÉ localement.

Ne télécharge PAS de modèle, ne consulte PAS d'API.
Requiert faster-whisper et un répertoire CTranslate2 déjà présent.
"""
import argparse
import json
from pathlib import Path
import sys


def main():
    p=argparse.ArgumentParser(description="Alignement local hors-ligne (modèle déjà sur disque)")
    p.add_argument("project");p.add_argument("--model-dir",required=True);p.add_argument("--clip",type=int,required=True);p.add_argument("--language",default="fr");p.add_argument("--output",required=True)
    a=p.parse_args()
    model=Path(a.model_dir).resolve()
    if not model.is_dir() or not (model/"model.bin").exists():
        sys.exit("ÉCHEC: modèle CTranslate2 local introuvable. Aucun téléchargement automatique autorisé.")
    try:from faster_whisper import WhisperModel
    except ImportError:sys.exit("Installe faster-whisper localement ou transfère des horodatages existants. Aucun téléchargement auto.")
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    from ugc import load_project,verify
    conf,root=load_project(Path(a.project));info=verify({**conf,"caption_mode":"none","words":[]},root)
    c=info["talking"][a.clip]
    m=WhisperModel(str(model),device="cpu",compute_type="int8",local_files_only=True)
    # Ne transcrit que le fichier local ; retourne timestamps originaux dans la source.
    segments,_=m.transcribe(str(c["file"]),language=a.language,word_timestamps=True,vad_filter=False)
    words=[]
    for seg in segments:
        for w in (seg.words or []):
            if c["source_in"] <= w.start and w.end <= c["source_in"]+c["duration"]:
                words.append({"clip":a.clip,"start":round(w.start,3),"end":round(w.end,3),"text":w.word.strip()})
    Path(a.output).write_text(json.dumps({"words":words,"manual_review_required":True},ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"{len(words)} mots horodatés. CORRIGER noms de marque et prononciation avant intégration.")

if __name__=="__main__":main()
