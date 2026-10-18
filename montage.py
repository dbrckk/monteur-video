"""Multi-rush montage and user-selectable thematic FFmpeg finishing filters.

All footage is processed in upload order and normalized to one H.264/AAC
profile before stream-copy concatenation. Filters act on the completed master,
never destructively changing the original export.
"""
from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Callable, Sequence

from editor import THEMES, edit_video, execute, probe_media, social_metadata

MAX_SOURCES = 10
FILTER_PRESETS = {
    "original": {
        "label": "Original", "description": "Rendu sans retouche.",
        "vf": None, "css": "none",
    },
    "impact": {
        "label": "Impact", "description": "Contraste et relief, idéal pour la musculation.",
        "vf": "eq=contrast=1.17:brightness=-0.012:saturation=1.17,unsharp=5:5:0.6:3:3:0",
        "css": "contrast(1.17) saturate(1.17) brightness(0.988)",
    },
    "acier": {
        "label": "Acier", "description": "Teinte froide et définition plus nette.",
        "vf": "eq=contrast=1.12:saturation=0.86:brightness=-0.006,colorbalance=bs=0.08:rs=-0.04",
        "css": "contrast(1.12) saturate(0.86) hue-rotate(8deg)",
    },
    "energie": {
        "label": "Énergie", "description": "Couleurs vibrantes pour l'effort et le sport.",
        "vf": "eq=contrast=1.09:saturation=1.29:brightness=0.015",
        "css": "contrast(1.09) saturate(1.29) brightness(1.015)",
    },
    "cinema": {
        "label": "Cinéma", "description": "Ambiance plus profonde et légèrement désaturée.",
        "vf": "eq=contrast=1.11:brightness=-0.02:saturation=0.86:gamma=0.97,vignette=PI/6",
        "css": "contrast(1.11) saturate(0.86) brightness(0.98)",
    },
    "soleil": {
        "label": "Soleil", "description": "Chaleur et lumière pour lifestyle et progression.",
        "vf": "eq=contrast=1.05:brightness=0.022:saturation=1.13,colorbalance=rs=0.06:bs=-0.06",
        "css": "sepia(0.15) contrast(1.05) saturate(1.13) brightness(1.02)",
    },
    "noir_blanc": {
        "label": "Noir & blanc", "description": "Esthétique minimaliste, contrastée et intense.",
        "vf": "hue=s=0,eq=contrast=1.22:brightness=-0.015",
        "css": "grayscale(1) contrast(1.22) brightness(0.985)",
    },
}
THEME_FILTERS = {
    "fitness": ["impact", "acier", "noir_blanc"],
    "motivation": ["cinema", "noir_blanc", "soleil"],
    "sport": ["energie", "impact", "acier"],
    "lifestyle": ["soleil", "cinema", "energie"],
    "auto": ["impact", "cinema", "soleil"],
}


def filter_catalog(theme: str) -> list[dict]:
    """Curated theme-first order, with complete explicit preset whitelist."""
    if theme not in THEMES:
        raise ValueError("Thème inconnu")
    suggested = THEME_FILTERS[theme]
    keys = ["original", *suggested,
            *(name for name in FILTER_PRESETS if name not in {"original", *suggested})]
    return [{"id": key, "label": FILTER_PRESETS[key]["label"],
             "description": FILTER_PRESETS[key]["description"],
             "css": FILTER_PRESETS[key]["css"],
             "recommended": key in suggested} for key in keys]


def automatic_duration(durations: Sequence[float]) -> int:
    """Choose a short-form target without padding or inventing missing footage."""
    if not durations or any(not math.isfinite(d) or d < 1 for d in durations):
        raise ValueError("Sources vidéo invalides")
    available = sum(durations)
    if available < 10:
        return 10  # Final export naturally stops at available source duration.
    if available < 20:
        return 10 if available < 13 else 15
    if available < 35:
        return 15
    if available < 70:
        return 30
    if available < 110:
        return 45
    return 60


def allocation(durations: Sequence[float], requested: int) -> list[float]:
    """Fair duration split: every supplied rush gets at least one second."""
    if not durations or len(durations) > MAX_SOURCES:
        raise ValueError("Nombre de vidéos invalide")
    if not 10 <= requested <= 180:
        raise ValueError("La durée cible doit être de 10 à 180 secondes")
    if any(not math.isfinite(d) or d < 1 for d in durations):
        raise ValueError("Chaque vidéo doit contenir au moins une seconde")
    total = min(float(requested), sum(durations))
    if total < len(durations):
        raise ValueError("Durée insuffisante pour représenter toutes les vidéos")
    budgets = [1.0 for _ in durations]
    remaining = total - len(budgets)
    for _ in range(len(durations) + 1):
        eligible = [i for i, d in enumerate(durations) if d - budgets[i] > 0.00001]
        if remaining < 0.00001 or not eligible:
            break
        weights = {i: math.sqrt(durations[i]) for i in eligible}
        weight_sum = sum(weights.values())
        granted = 0.0
        for i in eligible:
            amount = min(durations[i] - budgets[i], remaining * weights[i] / weight_sum)
            budgets[i] += amount
            granted += amount
        remaining -= granted
    return budgets


def edit_many(sources: Sequence[Path], destination: Path, *, theme: str = "fitness",
              aspect: str = "vertical", target_seconds: int = 45,
              source_names: Sequence[str] | None = None,
              transcribe: bool = True, size: int = 1080,
              progress: Callable[[float, str], None] | None = None) -> dict:
    """Select independently from every rush, then merge one final social video."""
    if theme not in THEMES or aspect not in {"vertical", "youtube"}:
        raise ValueError("Paramètres de montage invalides")
    if not sources or len(sources) > MAX_SOURCES:
        raise ValueError(f"Sélectionner entre 1 et {MAX_SOURCES} vidéos")
    if source_names is not None and len(source_names) != len(sources):
        raise ValueError("Nombre de noms incohérent")
    # Inspect each file before any expensive rendering.
    info = [probe_media(Path(source)) for source in sources]
    if target_seconds == 0:
        target_seconds = automatic_duration([item["duration"] for item in info])
    budgets = allocation([item["duration"] for item in info], target_seconds)
    if len(sources) == 1:
        result = edit_video(Path(sources[0]), destination, theme=theme, aspect=aspect,
                            target_seconds=target_seconds, transcribe=transcribe,
                            size=size, progress=progress)
        result["target_duration_seconds"] = target_seconds
        result["source_count"] = 1
        result["sources"] = [{
            "index": 0, "name": source_names[0] if source_names else Path(sources[0]).name,
            "duration_seconds": round(info[0]["duration"], 2),
            "rendered_seconds": result["rendered_duration_seconds"],
        }]
        return result

    destination.parent.mkdir(parents=True, exist_ok=True)
    work = destination.parent / "rushes"
    work.mkdir(parents=True, exist_ok=True)
    rendered = []
    details = []
    selected_speech = []
    combined_clips = []
    for i, (source, duration, budget) in enumerate(zip(sources, info, budgets)):
        part = work / f"rush-{i:02}.mp4"
        if progress:
            progress(0.02 + i / len(sources) * 0.88, "scenes")
        child = edit_video(
            Path(source), part, theme=theme, aspect=aspect,
            target_seconds=budget, transcribe=transcribe, size=size,
            allow_short=True,
            progress=(lambda p, stage, i=i: progress(
                min(0.91, 0.02 + (i + p) / len(sources) * 0.88), stage))
            if progress else None,
        )
        rendered.append(part)
        selected_speech.extend(child.get("selected_transcript", []))
        combined_clips.extend({"source_index": i, **clip} for clip in child["clips"])
        details.append({
            "index": i,
            "name": source_names[i] if source_names else Path(source).name,
            "duration_seconds": round(duration["duration"], 2),
            "rendered_seconds": child["rendered_duration_seconds"],
            "speech_engine": child["speech_engine"],
        })
    concat = work / "playlist.txt"
    concat.write_text("".join(f"file '{part.name}'\n" for part in rendered), encoding="utf-8")
    execute(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat),
             "-map", "0:v:0", "-map", "0:a:0",
             "-c", "copy", "-movflags", "+faststart", str(destination)])
    if progress:
        progress(0.98, "render")
    output = social_metadata(theme, selected_speech, sum(x["duration"] for x in info))
    output.update({
        "aspect": aspect,
        "target_duration_seconds": target_seconds,
        "resolution": "9:16" if aspect == "vertical" else "16:9",
        "source_count": len(sources),
        "sources": details,
        "clips": combined_clips,
        "captions_generated": bool(selected_speech),
        "speech_engine": "whisper" if any(x["speech_engine"] == "whisper" for x in details)
                         else "unavailable_or_disabled",
        "rendered_duration_seconds": round(sum(d["rendered_seconds"] for d in details), 2),
        "selected_transcript": selected_speech,
    })
    if progress:
        progress(1.0, "done")
    return output


def apply_filter(source: Path, destination: Path, preset: str,
                 progress: Callable[[float, str], None] | None = None) -> None:
    """Non-destructively export a color-grade from an already rendered master."""
    if preset not in FILTER_PRESETS or preset == "original":
        raise ValueError("Filtre de rendu inconnu")
    if not source.is_file() or source.stat().st_size == 0:
        raise ValueError("Montage original introuvable")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.stem + ".partial.mp4")
    temporary.unlink(missing_ok=True)
    if progress:
        progress(0.05, "filter")
    try:
        execute(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                 "-i", str(source), "-map", "0:v:0", "-map", "0:a:0?",
                 "-vf", FILTER_PRESETS[preset]["vf"],
                 "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
                 "-pix_fmt", "yuv420p", "-c:a", "copy",
                 "-movflags", "+faststart", str(temporary)])
        if progress:
            progress(0.95, "filter")
        probe_media(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    if progress:
        progress(1.0, "done")
