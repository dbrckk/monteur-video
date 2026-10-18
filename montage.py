"""Multi-rush montage and user-selectable thematic FFmpeg finishing filters.

All footage is processed in upload order and normalized to one H.264/AAC
profile before stream-copy concatenation. Filters act on the completed master,
never destructively changing the original export.
"""
from __future__ import annotations

import math
import os
import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

from editor import THEMES, detect_scenes, edit_video, execute, probe_media, social_metadata
from visual_quality import analyze_visual
from soundtrack import select_music_profile
from color_grade import grade_plan

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


def automatic_duration(durations: Sequence[float], scene_counts: Sequence[int] | None = None,
                       activity_seconds: float | None = None) -> int:
    """Choose a short-form target without padding or inventing missing footage."""
    if not durations or any(not math.isfinite(d) or d < 1 for d in durations):
        raise ValueError("Sources vidéo invalides")
    available = sum(durations)
    if scene_counts is not None and (len(scene_counts) != len(durations) or
                                     any(n < 0 for n in scene_counts)):
        raise ValueError("Analyse des scènes incohérente")
    if activity_seconds is not None and (not math.isfinite(activity_seconds) or
                                         activity_seconds < 0):
        raise ValueError("Activité visuelle invalide")
    if available < 10:
        return 10  # Final export naturally stops at available source duration.
    if available < 20:
        return 10 if available < 13 else 15
    if available < 35:
        return 15
    if available < 70:
        baseline = 30
    elif available < 110:
        baseline = 45
    else:
        baseline = 60
    # Strong visual edit evidence supports a compact, high-energy reel.
    # Static gym footage can still contain useful action, so never shorten it
    # merely because the camera stays fixed.
    if scene_counts is not None and available >= 35:
        cuts_per_minute = sum(scene_counts) * 60 / available
        if cuts_per_minute >= 18:
            baseline = min(baseline, 15)
        elif cuts_per_minute >= 9:
            baseline = min(baseline, 30)
    # Even a stationary gym camera may capture a very short action burst.
    if activity_seconds is not None and available >= 35:
        if 6 <= activity_seconds < 10 and activity_seconds <= available * 0.2:
            baseline = min(baseline, 10)
        elif 10 <= activity_seconds <= 20 and activity_seconds <= available * 0.3:
            baseline = min(baseline, 15)
    return baseline


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


def _content_fingerprint(path: Path) -> str:
    """Stable source tie-breaker independent of Android upload order or filename."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        digest.update(stream.read(65536))
        length = stream.seek(0, 2)
        if length > 65536:
            stream.seek(max(0, length - 65536))
            digest.update(stream.read(65536))
    digest.update(str(length).encode("ascii"))
    return digest.hexdigest()


def narrative_order(sources: Sequence[Path], samples: Sequence[list]) -> list[int]:
    """Visual-energy arc: context -> effort builds -> peak -> calmer closing shot.

    These are measured shot properties, not a claim to understand exercise
    semantics. Content hashes make ties independent of upload order.
    """
    if len(sources) != len(samples):
        raise ValueError("Analyse des rushs incohérente")
    if len(sources) < 2:
        return list(range(len(sources)))

    def features(index: int) -> tuple[float, float, str]:
        usable = [x for x in samples[index] if 25 <= x.luminance <= 230
                  and x.detail >= 2]
        if usable:
            motion = sorted(min(24, max(0, x.motion)) for x in usable)
            activity = motion[int((len(motion) - 1) * 0.70)]
            clarity = sum(min(48, x.detail) for x in usable) / len(usable)
            # Visual energy is primary; clarity avoids a blurred establishing shot.
            return round(activity + 0.04 * clarity, 3), round(clarity, 3), _content_fingerprint(sources[index])
        return -1.0, -1.0, _content_fingerprint(sources[index])

    ranked = sorted(range(len(sources)), key=features)
    if len(ranked) <= 2:
        return ranked
    return [ranked[0], *ranked[2:], ranked[1]]


def _filename_capture_time(name: str) -> str | None:
    """Use only explicit camera timestamp filenames; never file upload/modification time.

    Camera formats such as VID_20260803_143012 and PXL_20260803_143012
    are local wall-clock time, so only used when every source has the same
    filename-derived convention. Do not mix these with UTC camera tags.
    """
    name = Path(name).name
    match = re.search(r"(?:^|[_-])(?:VID|PXL|IMG|MVIMG)[_-]?(20\\d{2})([01]\\d)([0-3]\\d)[_-]([0-2]\\d)([0-5]\\d)([0-5]\\d)(?:[_\\.-]|$)",
                      name, re.I)
    if not match:
        return None
    try:
        return datetime(*(int(x) for x in match.groups())).isoformat()
    except ValueError:
        return None


def chronological_order(sources: Sequence[Path], samples: Sequence[list],
                        info: Sequence[dict],
                        source_names: Sequence[str] | None = None) -> tuple[list[int], str]:
    """Keep trustworthy capture anchors; infer only the gaps between them.

    Filename capture dates are accepted only when ALL rushes use recognizable
    camera filename conventions and there are no timezone-aware tags, avoiding
    unsafe comparisons between local wall time and UTC. Unknown shots are
    inserted into the visual story but never reorder known chronological anchors.
    """
    if len(sources) != len(info) or len(sources) != len(samples):
        raise ValueError("Métadonnées chronologiques incohérentes")
    names = source_names or [Path(p).name for p in sources]
    if len(names) != len(sources):
        raise ValueError("Noms de sources chronologiques incohérents")
    timestamps = [item.get("captured_at") for item in info]
    if not any(timestamps):
        filename_times = [_filename_capture_time(name) for name in names]
        if all(filename_times) and len(set(filename_times)) > 1:
            return sorted(range(len(sources)), key=lambda i:
                          (filename_times[i], _content_fingerprint(sources[i]))), "camera_filename_time"
    hashes = [_content_fingerprint(source) for source in sources]
    known = [i for i, value in enumerate(timestamps) if isinstance(value, str) and value]
    if len(known) >= 2 and len({timestamps[i] for i in known}) > 1:
        anchors = sorted(known, key=lambda i: (timestamps[i], hashes[i]))
        if len(known) == len(sources):
            return anchors, "capture_time"
        # With partial capture dates, preserve all anchored order and place
        # unanchored shots in stable visual-energy positions. This is a story
        # approximation, explicitly distinguished from recovered chronology.
        visual = narrative_order(sources, samples)
        positions = {index: pos for pos, index in enumerate(visual)}
        remaining = [i for i in visual if i not in known]
        slots = [[] for _ in range(len(anchors) + 1)]
        for index in remaining:
            slot = sum(positions[anchor] < positions[index] for anchor in anchors)
            slots[slot].append(index)
        assembled = []
        for k, anchor in enumerate(anchors):
            assembled.extend(slots[k])
            assembled.append(anchor)
        assembled.extend(slots[-1])
        return assembled, "capture_anchors_visual_gaps"
    return narrative_order(sources, samples), "energy_arc_no_reliable_timestamps"

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
    # Publish real milestones during preparation: the previous 51% stage could
    # remain frozen for minutes while FFmpeg silently scanned whole recordings.
    info = []
    for i, source in enumerate(sources):
        if progress:
            progress(0.01 + i / len(sources) * 0.07, "probe")
        info.append(probe_media(Path(source)))
        if progress:
            progress(0.01 + (i + 1) / len(sources) * 0.07, "probe")
    auto_mode = target_seconds == 0
    scene_cache: list[list[float]] = []
    quality_cache: list[list] = []
    for i, (source, item) in enumerate(zip(sources, info)):
        base = 0.08 + i / len(sources) * 0.12
        scene_cache.append(detect_scenes(
            Path(source), item["duration"],
            progress=(lambda p, base=base: progress(
                base + p * 0.12 / len(sources), "scenes")) if progress else None))
    for i, (source, item) in enumerate(zip(sources, info)):
        base = 0.20 + i / len(sources) * 0.12
        quality_cache.append(analyze_visual(
            Path(source), duration=item["duration"],
            progress=(lambda p, base=base: progress(
                base + p * 0.12 / len(sources), "quality")) if progress else None))
    if auto_mode:
        analyzed = [sample for rush in quality_cache for sample in rush]
        activity_seconds = (sum(0.5 for x in analyzed if x.motion >= 3.5 and
                                25 <= x.luminance <= 230 and x.detail >= 4)
                            if analyzed else None)
        target_seconds = automatic_duration([item["duration"] for item in info],
                                            [len(s) for s in scene_cache],
                                            activity_seconds=activity_seconds)
    music_profile = select_music_profile(
        theme, [sample for rush in quality_cache for sample in rush],
        scene_count=sum(map(len, scene_cache)),
        source_seconds=sum(item["duration"] for item in info))
    grades = grade_plan(quality_cache, theme)
    budgets = allocation([item["duration"] for item in info], target_seconds)
    order, sequence_strategy = chronological_order(
        [Path(source) for source in sources], quality_cache, info, source_names)
    if progress:
        progress(0.32, "story")
    if len(sources) == 1:
        result = edit_video(Path(sources[0]), destination, theme=theme, aspect=aspect,
                            target_seconds=target_seconds, transcribe=transcribe,
                            size=size,
                            progress=(lambda p, stage: progress(0.32 + p * 0.62, stage))
                            if progress else None,
                            detected_scenes=scene_cache[0],
                            visual_samples=quality_cache[0],
                            music_profile=music_profile,
                            grade_filter=grades["source_grades"][0]["filter"],
                            color_reference=grades, source_index=0)
        result["target_duration_seconds"] = target_seconds
        result["duration_mode"] = "auto" if auto_mode else "manual"
        result["source_count"] = 1
        result["music_profile"] = music_profile
        result["color_grade"] = grades
        result["sequence_strategy"] = sequence_strategy
        result["sequence_order"] = [0]
        result["capture_timestamps"] = [info[0].get("captured_at")]
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
    for position, index in enumerate(order):
        source, duration, budget = sources[index], info[index], budgets[index]
        part = work / f"rush-{position:02}.mp4"
        if progress:
            progress(0.32 + position / len(sources) * 0.62, "highlights")
        child = edit_video(
            Path(source), part, theme=theme, aspect=aspect,
            target_seconds=budget, transcribe=transcribe, size=size,
            allow_short=True,
            detected_scenes=scene_cache[index],
            visual_samples=quality_cache[index],
            music_profile=music_profile,
            grade_filter=grades["source_grades"][index]["filter"],
            color_reference=grades, source_index=index,
            progress=(lambda p, stage, position=position: progress(
                min(0.94, 0.32 + (position + p) / len(sources) * 0.62), stage))
            if progress else None,
        )
        rendered.append(part)
        selected_speech.extend(child.get("selected_transcript", []))
        combined_clips.extend({"source_index": index, "sequence_position": position,
                               **clip} for clip in child["clips"])
        details.append({
            "index": index, "sequence_position": position,
            "name": source_names[index] if source_names else Path(source).name,
            "duration_seconds": round(duration["duration"], 2),
            "rendered_seconds": child["rendered_duration_seconds"],
            "speech_engine": child["speech_engine"],
            "visual_analysis": child.get("visual_analysis", "unavailable"),
            "captured_at": duration.get("captured_at"),
            "color_grade": grades["source_grades"][index]["correction"],
        })
    concat = work / "playlist.txt"
    concat.write_text("".join(f"file '{part.name}'\n" for part in rendered), encoding="utf-8")
    execute(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat),
             "-map", "0:v:0", "-map", "0:a:0",
             "-c", "copy", "-movflags", "+faststart", str(destination)], timeout=180)
    if progress:
        progress(0.98, "render")
    output = social_metadata(theme, selected_speech, sum(x["duration"] for x in info))
    output.update({
        "aspect": aspect,
        "target_duration_seconds": target_seconds,
        "duration_mode": "auto" if auto_mode else "manual",
        "resolution": "9:16" if aspect == "vertical" else "16:9",
        "source_count": len(sources),
        "music_profile": music_profile,
        "color_grade": grades,
        "sequence_strategy": sequence_strategy,
        "sequence_order": order,
        "capture_timestamps": [item.get("captured_at") for item in info],
        "visual_analysis": ("motion_luminance_detail" if any(
            x["visual_analysis"] != "unavailable" for x in details) else "unavailable"),
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
                 "-movflags", "+faststart", str(temporary)], timeout=1200)
        if progress:
            progress(0.95, "filter")
        probe_media(temporary)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)
    if progress:
        progress(1.0, "done")
