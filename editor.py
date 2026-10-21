"""Local-first, reproducible fitness/social-video editing engine (FFmpeg + optional Whisper)."""
from __future__ import annotations

import json
import math
import os
import re
import subprocess
from functools import lru_cache
from datetime import datetime, timezone
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
    preserves_action: bool = False

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
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"{command[0]} : analyse interrompue après {timeout} s") from exc
    return result.stderr + "\n" + result.stdout


def probe_media(source: Path) -> dict:
    raw = execute(["ffprobe", "-v", "error", "-show_format", "-show_streams",
                   "-of", "json", str(source)], timeout=120)
    info = json.loads(raw)
    video = next((s for s in info.get("streams", []) if s["codec_type"] == "video"), None)
    if video is None:
        raise ValueError("Le fichier ne contient aucune piste vidéo.")
    # Container length can follow a microphone track that outlives the video.
    # Always plan cuts against the actual picture timeline when it is known.
    duration = 0.0
    for candidate in (video.get("duration"), info.get("format", {}).get("duration")):
        try:
            seconds = float(candidate)
        except (ValueError, TypeError):
            continue
        if math.isfinite(seconds) and seconds > 0:
            duration = seconds
            break
    if not math.isfinite(duration) or duration < 0.5:
        raise ValueError("Durée vidéo invalide ou insuffisante.")
    # Prefer camera capture metadata over upload time or Android filesystem times.
    # Reject dates lacking a timezone: comparing local and UTC timestamps is unsafe.
    tags = [video.get("tags") or {}, info.get("format", {}).get("tags") or {}]
    captured = None
    for collection in tags:
        for key, value in collection.items():
            if key.lower() not in {"creation_time", "com.apple.quicktime.creationdate",
                                   "date", "com.android.capture.fps.creation_time"}:
                continue
            try:
                raw_date = str(value).strip().replace("Z", "+00:00")
                parsed = datetime.fromisoformat(raw_date)
                if parsed.tzinfo is not None and 2000 <= parsed.year <= 2100:
                    captured = parsed.astimezone(timezone.utc).isoformat()
                    break
            except (ValueError, TypeError, OverflowError):
                continue
        if captured:
            break
    return {"duration": duration,
            "width": int(video["width"]), "height": int(video["height"]),
            "captured_at": captured,
            "has_audio": any(s["codec_type"] == "audio" for s in info["streams"])}


def analysis_windows(duration: float) -> list[tuple[float, float]]:
    """Sample long videos via seeks instead of decoding their entire timeline."""
    if not math.isfinite(duration) or duration <= 0:
        return []
    budget = max(8.0, min(60.0, float(os.getenv("MONTEUR_ANALYSIS_SECONDS", "24"))))
    if duration <= budget:
        return [(0.0, duration)]
    count = min(4, max(2, math.ceil(budget / 6.0)))
    width = budget / count
    return [(round((duration - width) * i / (count - 1), 3), round(width, 3))
            for i in range(count)]


def detect_scenes(source: Path, duration: float,
                  progress: Callable[[float], None] | None = None) -> list[float]:
    """Bound CPU consumption; scene scanning failure must not block an edit."""
    windows = analysis_windows(duration)
    events: set[float] = set()
    for i, (start, length) in enumerate(windows):
        try:
            output = execute(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "info",
                              "-ss", str(start), "-i", str(source), "-t", str(length),
                              "-an", "-vf", "fps=2,scale=320:-2,select='gt(scene,0.27)',showinfo",
                              "-f", "null", "-"], timeout=90)
            events.update(round(start + float(m), 2) for m in
                          re.findall(r"pts_time:([0-9]+(?:\.[0-9]+)?)", output)
                          if 0.5 < float(m) < length - 0.5)
        except (RuntimeError, OSError):
            pass
        if progress:
            progress((i + 1) / len(windows))
    return sorted(t for t in events if 0.5 < t < duration - 0.5)

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


@lru_cache(maxsize=2)
def load_whisper_model(model_name: str, device: str, compute_type: str):
    """Reuse the heavy model across every rush in a montage (one render worker)."""
    from faster_whisper import WhisperModel
    return WhisperModel(model_name, device=device, compute_type=compute_type)


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
        model = load_whisper_model(model_name, device, compute_type)
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
               transcript: list[dict], target_seconds: float = 45,
               allow_short: bool = False,
               visual_samples: list | None = None,
               beat_seconds: float | None = None,
               action_bouts: list[dict] | None = None,
               motion_cadence: list[dict] | None = None) -> list[Clip]:
    """Select highlights across the entire recording, respecting pauses and visual cuts.

    Stratified buckets prevent a long, low-dialogue video from collapsing into its
    first minute. Within each bucket, speech relevance and scene cuts take priority.
    """
    from bisect import bisect_left

    minimum = 1 if allow_short else 10
    if not minimum <= target_seconds <= 180:
        raise ValueError(f"La durée cible doit être comprise entre {minimum} et 180 secondes.")
    # For gym footage, silence can contain the most valuable repetitions.
    # Prefer visible ranges, even with no soundtrack or spoken narration.
    if visual_samples:
        from visual_quality import usable_ranges
        ranges = usable_ranges(visual_samples, duration) or [(0.0, duration)]
    else:
        # A silent workout may contain the best repetitions. Without visual
        # evidence, audio silence is not grounds to discard the footage.
        ranges = [(0.0, duration)]
    boundaries = sorted(scenes)
    # Hard, rhythmic cuts suit strength training and sport better than
    # long uninterrupted shots. Slower themes receive longer phrases.
    clip_span = max(2.0, min(6.0, 8 * beat_seconds)) if beat_seconds else 5.5
    candidates: list[Clip] = []
    for start, end in ranges:
        cursor = start
        while cursor < end - 1.0:
            index = bisect_left(boundaries, cursor + 1.3)
            next_scene = (boundaries[index]
                          if index < len(boundaries) and boundaries[index] <= min(end, cursor + clip_span)
                          else None)
            stop = min(end, next_scene if next_scene is not None else cursor + clip_span)
            if stop - cursor < 1.0:
                break
            spoken = " ".join(x["text"].lower() for x in transcript
                              if x["start"] < stop and x["end"] > cursor)
            bonus = min(5, sum(1 for token in MOTIVATORS if token in spoken))
            near = bisect_left(boundaries, cursor - 0.8)
            scene_bonus = (0.4 if near < len(boundaries)
                           and abs(boundaries[near] - cursor) < 0.8 else 0.0)
            score = 1.0 + bonus + scene_bonus + min(2.0, len(spoken) / 120)
            if visual_samples:
                from visual_quality import clip_quality
                quality_bonus, unusable = clip_quality(visual_samples, cursor, stop)
                if unusable:
                    cursor = stop
                    continue
                score += quality_bonus
            if action_bouts:
                from action_story import candidate_action_score
                score += candidate_action_score(cursor, stop, action_bouts)
            if motion_cadence:
                from action_story import candidate_cadence_score
                score += candidate_cadence_score(cursor, stop, motion_cadence)
            candidates.append(Clip(round(cursor, 3), round(stop, 3), score))
            cursor = stop
    if action_bouts:
        from action_story import (short_complete_action_intervals,
                                  candidate_action_score, candidate_cadence_score)
        protected = short_complete_action_intervals(action_bouts, ranges, boundaries, clip_span)
        for clip_start, clip_end in protected:
            quality_bonus = 0.0
            if visual_samples:
                from visual_quality import clip_quality
                quality_bonus, unusable = clip_quality(visual_samples, clip_start, clip_end)
                if unusable:
                    continue
            # Select full short movements, not attractive but incomplete snippets.
            score = (3.0 + quality_bonus
                     + candidate_action_score(clip_start, clip_end, action_bouts)
                     + candidate_cadence_score(clip_start, clip_end, motion_cadence or []))
            candidates.append(Clip(clip_start, clip_end, round(score, 3), True))
    if not candidates:
        # Never export the entire rush when the requested highlight is short.
        return [Clip(0.0, min(duration, float(target_seconds)), 1.0)]

    bucket_count = min(len(candidates), max(1, math.ceil(target_seconds / 5.5)))
    buckets: list[list[Clip]] = [[] for _ in range(bucket_count)]
    for clip in candidates:
        group = min(bucket_count - 1, int(clip.start / duration * bucket_count))
        buckets[group].append(clip)

    # For equal scores, prefer the center of each time bucket, not always the earliest.
    representatives = []
    for i, bucket in enumerate(buckets):
        if bucket:
            center = duration * (i + 0.5) / bucket_count
            representatives.append(max(bucket, key=lambda c: (c.score, -abs(c.start - center))))

    selected: list[Clip] = []
    remaining = min(float(target_seconds), duration)

    def include(candidate: Clip) -> None:
        nonlocal remaining
        if remaining < 1.0 or any(candidate.start < c.end and candidate.end > c.start
                                  for c in selected):
            return
        # A protected observed movement may only be included in full.
        if candidate.preserves_action and candidate.duration > remaining + 0.0001:
            return
        length = min(candidate.duration, remaining)
        if not candidate.preserves_action and beat_seconds and length >= 4 * beat_seconds:
            # Prefer four-beat measures, or two beats for shorter actions.
            quantized = math.floor((length + 0.02) / (4 * beat_seconds)) * 4 * beat_seconds
            if quantized < 1.0:
                quantized = math.floor((length + 0.02) / (2 * beat_seconds)) * 2 * beat_seconds
            if quantized >= 1.0:
                length = min(length, quantized)
        if length >= 1.0:
            selected.append(Clip(candidate.start, round(candidate.start + length, 3),
                                 candidate.score, candidate.preserves_action))
            remaining -= length

    for representative in sorted(representatives, key=lambda c: (-c.score, c.start)):
        include(representative)
    for candidate in sorted(candidates, key=lambda c: (-c.score, c.start)):
        include(candidate)
        if remaining < 1.0:
            break
    return sorted(selected, key=lambda c: c.start)


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
           size: int = 1080, progress: Callable[[float, str], None] | None = None,
           grade_filter: str | None = None,
           shot_filters: list[str | None] | None = None,
           source_dimensions: tuple[int, int] | None = None) -> None:
    if not clips:
        raise ValueError("Aucun passage utilisable.")
    work = destination.parent / "segments"
    work.mkdir(parents=True, exist_ok=True)
    w, h = (size, size * 16 // 9) if vertical else (size * 16 // 9, size)
    if w % 2 or h % 2:
        raise ValueError("Dimensions de sortie non paires.")
    from smart_reframe import ffmpeg_crop_x, plan_vertical_reframe
    if vertical and source_dimensions is None:
        media = probe_media(source)
        source_dimensions = (media["width"], media["height"])
    reframes = []
    files = []
    for i, clip in enumerate(clips):
        part = work / f"{i:04}.mp4"
        if vertical and os.getenv("MONTEUR_SMART_REFRAME", "1") != "0":
            plan = plan_vertical_reframe(source, clip.start, clip.duration,
                                         *source_dimensions)
            crop_x = ffmpeg_crop_x(plan)
            reframes.append(plan)
        else:
            crop_x = "(iw-ow)/2"
        scaling = (f"scale={w}:{h}:force_original_aspect_ratio=increase,"
                   f"crop={w}:{h}:{crop_x}:(ih-oh)/2,setsar=1")
        clip_filter = shot_filters[i] if shot_filters is not None else grade_filter
        if clip_filter:
            scaling += "," + clip_filter
        ass = work / f"{i:04}.ass"
        if create_captions(ass, clip, transcript, vertical):
            # Segments are named with UUID parent / numeric basename: safe for FFmpeg quoting.
            scaling += f",subtitles={ass.as_posix()}"
        command = ["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
                   "-ss", str(clip.start), "-i", str(source)]
        if not has_audio:
            command += ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
        # Phone microphones sometimes stop before the video track. Without
        # padding, -shortest silently truncates the picture at the audio EOF.
        # Preserve the requested clip length and fill only missing audio with silence.
        audio_fade = (f"apad=whole_dur={clip.duration:.3f},"
                      f"atrim=duration={clip.duration:.3f},"
                      f"afade=t=in:st=0:d=0.06,"
                      f"afade=t=out:st={max(0.06, clip.duration - 0.08):.3f}:d=0.08")
        command += ["-t", str(clip.duration), "-map", "0:v:0",
                    "-map", "0:a:0" if has_audio else "1:a:0",
                    "-vf", scaling, "-af", audio_fade, "-r", "30", "-c:v", "libx264",
                    "-threads", "2", "-preset", "veryfast", "-crf", "20",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
                    "-ar", "48000", "-ac", "2",
                    "-map_metadata", "-1", "-shortest", str(part)]
        execute(command, timeout=600)
        files.append(part)
        if progress:
            progress(0.40 + (i + 1) / len(clips) * 0.52, "render")
    concat = work / "concat.txt"
    concat.write_text("".join(f"file '{p.name}'\n" for p in files), encoding="utf-8")
    execute(["ffmpeg", "-hide_banner", "-nostdin", "-y", "-loglevel", "error",
             "-f", "concat", "-safe", "0", "-i", str(concat),
             "-c", "copy", "-movflags", "+faststart", str(destination)], timeout=180)
    metadata["rendered_duration_seconds"] = round(sum(c.duration for c in clips), 2)
    metadata["auto_reframe"] = {
        "enabled": vertical and os.getenv("MONTEUR_SMART_REFRAME", "1") != "0",
        "motion_guided_clips": sum(p.mode == "motion_guided" for p in reframes),
        "center_fallback_clips": sum(p.mode != "motion_guided" for p in reframes),
        "strategy": "motion_saliency_not_person_recognition",
        "smooth_interpolation": True,
    }


def edit_video(source: Path, destination: Path, *, theme: str = "fitness",
               aspect: str = "vertical", target_seconds: int = 45,
               transcribe: bool = True, size: int = 1080,
               allow_short: bool = False,
               detected_scenes: list[float] | None = None,
               visual_samples: list | None = None,
               music_profile: dict | None = None,
               grade_filter: str | None = None,
               color_reference: dict | None = None,
               source_index: int = 0,
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
    scenes = detected_scenes if detected_scenes is not None else detect_scenes(source, info["duration"])
    # Gym repetitions are meaningful even with no soundtrack; clip selection
    # no longer consults audio silence ranges, so skip the expensive full decode.
    if progress:
        progress(0.32, "highlights")
    if visual_samples is None:
        from visual_quality import analyze_visual
        visual_samples = analyze_visual(source, duration=info["duration"])
    if grade_filter is None:
        from color_grade import grade_plan
        grade_filter = grade_plan([visual_samples or []], theme)["source_grades"][0]["filter"]
    from soundtrack import beat_duration
    beat_grid = (60.0 / music_profile["bpm"] if music_profile else beat_duration(theme)) if theme in {"fitness", "sport"} else None
    from action_story import narrative_signals
    action_story = narrative_signals(visual_samples or [], transcript, info["duration"])
    from pose_evidence import analyze_pose
    action_story["pose_evidence"] = analyze_pose(source, info["duration"])
    clips = plan_clips(info["duration"], scenes, [], transcript, target_seconds,
                       allow_short=allow_short, visual_samples=visual_samples,
                       beat_seconds=beat_grid,
                       action_bouts=action_story["action_bouts"],
                       motion_cadence=action_story["possible_motion_cadence"])
    from action_story import narrative_coverage, completed_action_coverage
    action_story["selected_coverage"] = narrative_coverage(clips, action_story["timeline_phases"])
    action_story["whole_action_coverage"] = completed_action_coverage(clips, action_story["action_bouts"])
    from color_grade import adaptive_shot_filters
    shot_filters = adaptive_shot_filters(visual_samples or [], clips, theme,
                                        shared_grade=color_reference,
                                        source_index=source_index)
    # Publication text must describe what survived editing, not unseen source footage.
    selected_speech = [phrase for phrase in transcript
                       if any(phrase["start"] < clip.end and phrase["end"] > clip.start
                              for clip in clips)]
    metadata = social_metadata(theme, selected_speech, info["duration"])
    metadata.update({"aspect": aspect, "resolution": ("9:16" if aspect == "vertical" else "16:9"),
                     "speech_engine": asr_mode, "captions_generated": bool(selected_speech),
                     "selected_transcript": selected_speech,
                     "scene_count": len(scenes),
                     "action_story": action_story,
                     "action_quality": action_story["whole_action_coverage"],
                     "visual_analysis": "motion_luminance_detail" if visual_samples else "unavailable",
                     "cut_style": "beat_synced" if beat_grid else "editorial",
                     "auto_color_grading": any(bool(v) for v in shot_filters),
                     "per_shot_color_matching": True,
                     "clips": [{"start": c.start, "end": c.end, "score": round(c.score, 2)}
                               for c in clips]})
    if progress:
        progress(0.40, "render")
    render(source, destination, clips, metadata, selected_speech,
           aspect == "vertical", info["has_audio"], size, progress,
           grade_filter=grade_filter, shot_filters=shot_filters,
           source_dimensions=(info["width"], info["height"]))
    if progress:
        progress(1.0, "done")
    return metadata
