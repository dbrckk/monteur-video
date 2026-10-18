"""Local-first, reproducible fitness/social-video editing engine (FFmpeg + optional Whisper)."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

THEMES = {
    "fitness": ("fitness", "entrainement", "musculation", "progression", "fitnessmotivation"),
    "motivation": ("motivation", "discipline", "mentalite", "objectif", "progression"),
    "lifestyle": ("lifestyle", "quotidien", "progression", "inspiration"),
    "sport": ("sport", "training", "performance", "determination"),
    "auto": ("progression", "inspiration"),
}
EVIDENCE = {
    "squat": ("squat", "squats"),
    "developpecouche": ("developpe couche", "bench press", "benchpress"),
    "souleveterre": ("souleve de terre", "deadlift"),
    "tractions": ("traction", "pull up", "pull-up"),
    "courseapied": ("course a pied", "running", "jogging", "courir"),
    "cardio": ("cardio", "endurance"),
    "nutrition": ("nutrition", "alimentation", "proteine", "protein"),
    "calisthenics": ("calisthenics", "calisthenie", "street workout"),
    "discipline": ("discipline", "consistance", "consistency"),
    "confianceensoi": ("confiance en soi", "self confidence"),
    "transformation": ("transformation", "avant apres", "before after"),
    "abdos": ("abdos", "abdominals", "abs workout"),
}
MOTIVATORS = ("discipline", "jamais", "effort", "objectif", "reuss", "progres",
              "strength", "consistency", "work hard", "keep going", "push", "focus",
              "motivation", "mentality", "mindset", "repetition")


@dataclass(frozen=True)
class Clip:
    start: float
    end: float
    score: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def execute(command: list[str], timeout: int | None = None) -> str:
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True,
                                timeout=timeout)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Executable manquant : {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"{command[0]} : {(exc.stderr or '')[-1300:]}") from exc
    return result.stderr + "\n" + result.stdout


def probe_media(source: Path) -> dict:
    raw = execute(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                   "-of", "json", str(source)], timeout=120)
    info = json.loads(raw)
    video = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("Le fichier ne contient aucune piste vidéo.")
    duration = float(info.get("format", {}).get("duration") or video.get("duration") or 0)
    if not math.isfinite(duration) or duration < 0.5:
        raise ValueError("Durée vidéo invalide ou insuffisante.")
    return {"duration": duration,
            "width": int(video["width"]), "height": int(video["height"]),
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def detect_scenes(source: Path, duration: float) -> list[float]:
    # Detection happens on a downscaled 2 FPS stream, keeping very long sources feasible.
    output = execute(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
                      "-i", str(source), "-an", "-vf",
                      "fps=2,scale=320:-2,select='gt(scene,0.27)',showinfo",
                      "-f", "null", "-"])
    return sorted({round(float(m), 2) for m in
                   re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", output)
                   if 0.5 < float(m) < duration - 0.5})


def detect_silences(source: Path, duration: float, has_audio: bool) -> list[tuple[float, float]]:
    if not has_audio:
        return []
    output = execute(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(source),
                      "-vn", "-af", "silencedetect=noise=-35dB:d=0.65",
                      "-f", "null", "-"])
    events = re.findall(r"silence_(start|end):\s*([0-9.]+)", output)
    silence = []
    start = None
    for kind, val in events:
        t = min(duration, float(val))
        if kind == "start":
            start = t
        elif start is not None:
            silence.append((start, max(start, t)))
            start = None
    if start is not None:
        silence.append((start, duration))
    return silence


def speech_to_text(source: Path, enabled: bool = True) -> tuple[list[dict], str]:
    if not enabled:
        return [], "disabled"
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return [], "unavailable: install requirements-ai.txt"
    model_name = os.environ.get("WHISPER_MODEL", "base")
    device = os.environ.get("WHISPER_DEVICE", "cpu")
    compute_type = "float16" if device == "cuda" else "int8"
    try:
        model = WhisperModel(model_name, device=device, compute_type=compute_type)
        segments, _ = model.transcribe(str(source), beam_size=3, vad_filter=True,
                                       word_timestamps=True)
        transcript = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                transcript.append({"start": float(segment.start),
                                   "end": float(segment.end), "text": text})
        return transcript, "whisper"
    except Exception as exc:
        # Rendering remains possible without ASR; do not present invented captions.
        return [], f"unavailable: {type(exc).__name__}"


def active_ranges(duration: float, silences: list[tuple[float, float]]) -> list[tuple[float, float]]:
    ranges = []
    cursor = 0.0
    for a, b in sorted(silences):
        a, b = max(0.0, a), min(duration, b)
        if a > cursor + 1.0:
            ranges.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < duration - 1.0:
        ranges.append((cursor, duration))
    return ranges


def plan_clips(duration: float, scenes: list[float], silences: list[tuple[float, float]],
               transcript: list[dict], target_seconds: int = 45) -> list[Clip]:
    if not 10 <= target_seconds <= 180:
        raise ValueError("La durée cible doit être comprise entre 10 et 180 secondes.")
    ranges = active_ranges(duration, silences) or [(0.0, duration)]
    candidates = []
    for start, end in ranges:
        cursor = start
        while cursor < end - 1.0:
            natural_cuts = [s for s in scenes if cursor + 3.0 <= s <= min(end, cursor + 7.0)]
            stop = min(end, natural_cuts[0] if natural_cuts else cursor + 5.5)
            if stop - cursor < 1.0:
                break
            spoken = " ".join(x["text"].lower() for x in transcript
                              if x["start"] < stop and x["end"] > cursor)
            bonus = min(5, sum(1 for token in MOTIVATORS if token in spoken))
            scene_bonus = 0.4 if any(abs(s - cursor) < 0.8 for s in scenes) else 0
            score = 1.0 + bonus + scene_bonus + min(2.0, len(spoken) / 120)
            candidates.append(Clip(round(cursor, 3), round(stop, 3), score))
            cursor = stop
    if not candidates:
        return [Clip(0.0, duration, 1.0)]
    # Add mild temporal diversity so a two-hour input does not yield one contiguous passage.
    ranked = sorted(candidates, key=lambda c: (-c.score, c.start))
    chosen: list[Clip] = []
    remaining = min(float(target_seconds), duration)
    for candidate in ranked:
        if remaining < 1.1:
            break
        if any(abs(candidate.start - c.start) < min(12.0, duration / 8)
               for c in chosen) and len(candidates) > 4:
            continue
        size = min(candidate.duration, remaining)
        if size < 1.0:
            continue
        chosen.append(Clip(candidate.start, candidate.start + size, candidate.score))
        remaining -= size
    if remaining >= 1.1:
        for candidate in ranked:
            if any(candidate.start < c.end and candidate.end > c.start for c in chosen):
                continue
            size = min(candidate.duration, remaining)
            if size >= 1:
                chosen.append(Clip(candidate.start, candidate.start + size, candidate.score))
                remaining -= size
            if remaining < 1.1:
                break
    return sorted(chosen, key=lambda x: x.start)


def social_metadata(theme: str, transcript: list[dict], duration: float) -> dict:
    theme = theme.lower() if theme.lower() in THEMES else "auto"
    combined = " ".join(x["text"].lower() for x in transcript)
    # Tags tied to actual speech are added only when supported by the transcript.
    evidenced = [tag for tag, words in EVIDENCE.items() if any(word in combined for word in words)]
    hashtags = list(dict.fromkeys([*THEMES[theme], *evidenced]))[:12]
    line = next((re.sub(r"\s+", " ", x["text"]).strip(" .") for x in transcript
                 if 20 <= len(x["text"]) <= 135), "")
    opener = f"« {line} »\n\n" if line else ""
    descriptions = {
        "fitness": "La progression se construit séance après séance.",
        "motivation": "La discipline transforme les intentions en actions.",
        "sport": "L'effort d'aujourd'hui prépare les résultats de demain.",
        "lifestyle": "Construire de meilleures habitudes, un jour à la fois.",
        "auto": "Un extrait à partager, un moment à retenir.",
    }
    description = (opener + descriptions[theme] +
                   "\nEt toi, quel est ton prochain objectif ?\n\n" +
                   " ".join("#" + x for x in hashtags))
    return {"description": description, "hashtags": hashtags,
            "speech_based_tags": evidenced, "transcript_used": bool(transcript),
            "source_duration_seconds": round(duration, 2)}


def ass_timestamp(seconds: float) -> str:
    cs = max(0, round(seconds * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02}:{s:02}.{cs:02}"


def create_captions(path: Path, clip: Clip, transcript: list[dict], vertical: bool) -> bool:
    events = []
    for phrase in transcript:
        start = max(clip.start, phrase["start"])
        stop = min(clip.end, phrase["end"])
        if stop - start < 0.15:
            continue
        words = phrase["text"].strip().split()
        if not words:
            continue
        chunks = [words[i:i + 5] for i in range(0, len(words), 5)]
        span = (stop - start) / len(chunks)
        for i, chunk in enumerate(chunks):
            sanitized = re.sub(r"[{}\r\n\\]", "", " ".join(chunk))
            if not sanitized:
                continue
            a = ass_timestamp(start - clip.start + i * span)
            b = ass_timestamp(start - clip.start + (i + 1) * span)
            events.append(f"Dialogue: 0,{a},{b},Default,,0,0,0,,{sanitized.upper()}")
    if not events:
        return False
    y = 1920 if vertical else 1080
    margin = 325 if vertical else 165
    size = 66 if vertical else 49
    path.write_text(
        "[Script Info]\nScriptType: v4.00+\nWrapStyle: 2\n"
        f"PlayResX: {1080 if vertical else 1920}\nPlayResY: {y}\n"
        "[V4+ Styles]\n"
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,"
        "BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,"
        "BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding\n"
        f"Style: Default,DejaVu Sans,{size},&H0000FFFF,&H0000FFFF,&H00000000,"
        f"&H99000000,-1,0,0,0,100,100,0,0,1,3,1,2,65,65,{margin},1\n"
        "[Events]\nFormat: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text\n"
        + "\n".join(events) + "\n", encoding="utf-8")
    return True


def render(source: Path, destination: Path, clips: list[Clip], metadata: dict,
           transcript: list[dict], vertical: bool, has_audio: bool,
           size: int = 1080, progress: Callable[[float, str], None] | None = None) -> None:
    if not clips:
        raise ValueError("Aucun passage utilisable.")
    work = destination.parent / "segments"
    work.mkdir(parents=True, exist_ok=True)
    w, h = (size, size * 16 // 9) if vertical else (size * 16 // 9, size)
    if w % 2 or h % 2:
        raise ValueError("Dimensions de sortie non paires.")
    files = []
    for i, clip in enumerate(clips):
        part = work / f"{i:04}.mp4"
        scaling = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h},setsar=1")
        ass = work / f"{i:04}.ass"
        if create_captions(ass, clip, transcript, vertical):
            # Segments are named with UUID parent / numeric basename: safe for FFmpeg quoting.
            scaling += f",subtitles={ass.as_posix()}"
        command = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                   "-ss", str(clip.start), "-i", str(source)]
        if not has_audio:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        command += ["-t", str(clip.duration), "-map", "0:v:0",
                    "-map", "0:a:0" if has_audio else "1:a:0",
                    "-vf", scaling, "-r", "30", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-ac", "2",
                    "-map_metadata", "-1", "-shortest", str(part)]
        execute(command)
        files.append(part)
        if progress:
            progress(0.40 + (i + 1) / len(clips) * 0.52, "render")
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in files), encoding="utf-8")
    execute(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat),
             "-c", "copy", "-movflags", "+faststart", str(destination)])
    metadata["rendered_duration_seconds"] = round(sum(c.duration for c in clips), 2)


def edit_video(source: Path, destination: Path, *, theme: str = "fitness",
               aspect: str = "vertical", target_seconds: int = 45,
               transcribe: bool = True, size: int = 1080,
               progress: Callable[[float, str], None] | None = None) -> dict:
    if aspect not in {"vertical", "youtube"}:
        raise ValueError("Format inconnu.")
    if theme not in THEMES:
        raise ValueError("Thème inconnu.")
    if progress:
        progress(0.05, "probe")
    info = probe_media(source)
    if progress:
        progress(0.12, "speech")
    transcript, asr_mode = speech_to_text(source, enabled=transcribe and info["has_audio"])
    if progress:
        progress(0.25, "scenes")
    scenes = detect_scenes(source, info["duration"])
    if progress:
        progress(0.32, "silence")
    silences = detect_silences(source, info["duration"], info["has_audio"])
    clips = plan_clips(info["duration"], scenes, silences, transcript, target_seconds)
    metadata = social_metadata(theme, transcript, info["duration"])
    metadata.update({"aspect": aspect, "resolution": ("9:16" if aspect == "vertical" else "16:9"),
                     "speech_engine": asr_mode, "captions_generated": bool(transcript),
                     "scene_count": len(scenes),
                     "clips": [{"start": c.start, "end": c.end, "score": round(c.score, 2)}
                               for c in clips]})
    if progress:
        progress(0.40, "render")
    render(source, destination, clips, metadata, transcript,
           aspect == "vertical", info["has_audio"], size, progress)
    if progress:
        progress(1.0, "done")
    return metadata
