"""Evidence-based sports action phases from video motion + actual speech.

No pose estimation and no fabricated exercise labels. Detect preparation,
sustained action and recovery from temporal changes in optical proxy motion.
Classify exercise names ONLY from an explicit source transcript.
"""
from __future__ import annotations
import math
import re
import unicodedata
from statistics import median

SPORT_WORDS = {
    "squat": ("squat", "squats"),
    "developpe_couche": ("developpe couche", "bench press", "benchpress"),
    "souleve_de_terre": ("souleve de terre", "deadlift"),
    "traction": ("traction", "tractions", "pullup", "pull up"),
    "course": ("course a pied", "running", "jogging"),
    "pompes": ("pompes", "push ups", "pushups"),
    "fentes": ("fentes", "lunges"),
    "burpees": ("burpees", "burpee"),
}
MIN_ACTION_SAMPLES = 3


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", "".join(
        ch for ch in text if not unicodedata.combining(ch))).split())


def speech_exercise(transcript: list[dict]) -> dict:
    speech = " ".join(_normalize(str(item.get("text", ""))) for item in transcript)
    detected = []
    for name, phrases in SPORT_WORDS.items():
        if any(re.search(r"(?<!\w)" + re.escape(_normalize(phrase)) + r"(?!\w)", speech)
               for phrase in phrases):
            detected.append(name)
    return {"exercise": detected[0] if len(detected) == 1 else None,
            "candidates": detected, "source": "transcript_explicit" if detected else "unknown",
            "confidence": 0.9 if len(detected) == 1 else 0.0}


def action_phases(samples: list, duration: float) -> list[dict]:
    """Segment contiguous measured action bouts without bridging unsampled gaps."""
    usable = [s for s in sorted(samples, key=lambda x: x.time)
              if math.isfinite(s.time) and math.isfinite(s.motion)
              and 22 <= s.luminance <= 231 and s.detail >= 2]
    if len(usable) < 6:
        return []
    motions = sorted(max(0, s.motion) for s in usable)
    baseline = median(motions[:max(3, len(motions) // 2)])
    threshold = max(1.9, min(14.0, baseline * 1.75))
    active = [s.motion >= threshold for s in usable]
    # Fill one-sample dips only when temporal samples are contiguous.
    for i in range(1, len(active) - 1):
        if (not active[i] and active[i-1] and active[i+1]
                and usable[i+1].time - usable[i-1].time <= 1.2):
            active[i] = True
    bouts = []
    start = None
    for i in range(len(usable) + 1):
        gap = i == len(usable) or (
            i > 0 and usable[i].time - usable[i-1].time > 1.05)
        is_active = i < len(usable) and active[i]
        if start is not None and (gap or not is_active):
            end_index = i - 1
            count = end_index - start + 1
            if count >= MIN_ACTION_SAMPLES:
                first = usable[start].time
                last = usable[end_index].time
                interval = min(duration, last + 0.5)
                peak = max(usable[k].motion for k in range(start, end_index+1))
                bouts.append({"start": round(first, 2), "end": round(interval, 2),
                              "peak_motion": round(peak, 2),
                              "confidence": round(min(0.85, .45 + .07 * count), 2),
                              "kind": "observed_motion_bout"})
            start = None
        if is_active and start is None:
            start = i
    return bouts


def motion_cadence(samples: list, bouts: list[dict]) -> list[dict]:
    """Detect a repeat-like visual cadence, not completed exercise repetitions.

    Motion is camera-sensitive and low-rate (2 FPS). A peak may reflect
    camera shake, transitions or equipment movement. Reject sparse gaps and
    too-short or irregular sequences; never report a repetition count.
    """
    results = []
    ordered = sorted(samples, key=lambda x: x.time)
    for bout in bouts:
        frames = [x for x in ordered
                  if bout["start"] <= x.time < bout["end"]
                  and math.isfinite(x.time) and math.isfinite(x.motion)
                  and 22 <= x.luminance <= 231 and x.detail >= 2]
        if len(frames) < 10 or any(
                not 0.3 <= b.time - a.time <= 0.7
                for a, b in zip(frames, frames[1:])):
            continue
        values = [max(0.0, x.motion) for x in frames]
        floor = median(values)
        amplitude = max(values) - min(values)
        if amplitude < max(2.0, floor * 0.30):
            continue
        threshold = floor + 0.18 * amplitude
        peaks = []
        for i in range(1, len(frames) - 1):
            if (values[i] > threshold and values[i] > values[i-1]
                    and values[i] >= values[i+1]
                    and (not peaks or frames[i].time - peaks[-1] >= 0.8)):
                peaks.append(frames[i].time)
        if len(peaks) < 3:
            continue
        intervals = [b - a for a, b in zip(peaks, peaks[1:])]
        spacing = median(intervals)
        if not 0.8 <= spacing <= 8.0:
            continue
        regularity = median(abs(x - spacing) for x in intervals) / spacing
        if regularity > 0.25:
            continue
        results.append({
            "start": bout["start"], "end": bout["end"],
            "visual_cycle_seconds": round(spacing, 2),
            "regularity": round(max(0.0, 1.0 - regularity), 2),
            "confidence": round(min(0.65, 0.30 + 0.05 * len(intervals)), 2),
            "kind": "possible_periodic_visual_motion",
            "not_exercise_rep_count": True,
        })
    return results


def candidate_cadence_score(start: float, end: float,
                            cadence: list[dict]) -> float:
    """Small bounded highlight bonus for repeated *visual* movement.

    Do not overrule image quality, visual continuity, or chronology. A cycle
    score is only awarded when at least 60% of the clip overlaps a verified
    periodic visual segment; it is never an exercise repetition estimate.
    """
    if not math.isfinite(start) or not math.isfinite(end) or end <= start:
        return 0.0
    best = 0.0
    for item in cadence:
        if item.get("kind") != "possible_periodic_visual_motion":
            continue
        confidence = item.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)) or not math.isfinite(confidence):
            continue
        if confidence < 0.3:
            continue
        overlap = max(0.0, min(end, item["end"]) - max(start, item["start"]))
        fraction = overlap / (end - start)
        if fraction >= 0.6:
            best = max(best, fraction * min(0.65, confidence) * 1.25)
    return round(min(0.8, best), 3)


def candidate_action_score(start: float, end: float, bouts: list[dict]) -> float:
    if end <= start:
        return 0.0
    overlap = max((max(0.0, min(end, b["end"]) - max(start, b["start"]))
                   for b in bouts), default=0.0)
    return round(2.2 * min(1.0, overlap / max(1.0, end-start)), 3)


def timeline_phases(samples: list, duration: float,
                    bouts: list[dict] | None = None) -> list[dict]:
    """Evidence-grounded preparation / effort / recovery intervals.

    Labels refer to relative observed motion, NOT human intent or pose.
    Do not bridge long sampling gaps or label unsampled regions.
    """
    if not math.isfinite(duration) or duration <= 0:
        return []
    bouts = action_phases(samples, duration) if bouts is None else bouts
    if not bouts:
        return []
    ordered = sorted(bouts, key=lambda b: b["start"])
    result = []
    first = ordered[0]["start"]
    if first >= 1:
        result.append({"start": 0.0, "end": round(first, 2),
                       "phase": "before_observed_effort",
                       "confidence": 0.35, "evidence": "relative_timing_only"})
    for i, bout in enumerate(ordered):
        result.append({"start": bout["start"], "end": bout["end"],
                       "phase": "observed_effort",
                       "confidence": bout["confidence"],
                       "evidence": "sustained_visual_motion"})
        if i + 1 < len(ordered):
            next_start = ordered[i + 1]["start"]
            if next_start - bout["end"] >= 1:
                result.append({"start": bout["end"], "end": next_start,
                               "phase": "between_efforts",
                               "confidence": 0.35,
                               "evidence": "relative_timing_only"})
    last = ordered[-1]["end"]
    if duration - last >= 1:
        result.append({"start": last, "end": round(duration, 2),
                       "phase": "after_observed_effort",
                       "confidence": 0.35, "evidence": "relative_timing_only"})
    return result


def narrative_coverage(clips: list, phases: list[dict]) -> dict:
    """Audit how much selected footage overlaps measured effort intervals."""
    total = sum(max(0, clip.end - clip.start) for clip in clips)
    observed = [p for p in phases if p["phase"] == "observed_effort"]
    overlap = sum(max(0.0, min(clip.end, p["end"]) -
                      max(clip.start, p["start"]))
                  for clip in clips for p in observed)
    return {"selected_seconds": round(total, 2),
            "observed_effort_seconds": round(overlap, 2),
            "observed_effort_ratio": round(min(1, overlap / total), 3) if total else 0.0,
            "phase_detection": "motion_proxy_not_pose_recognition"}


def narrative_signals(samples: list, transcript: list[dict], duration: float) -> dict:
    phases = action_phases(samples, duration)
    explicit = speech_exercise(transcript)
    timeline = timeline_phases(samples, duration, phases)
    cadence = motion_cadence(samples, phases)
    return {
        "method": "motion_bouts_and_explicit_speech",
        "action_bouts": phases,
        "timeline_phases": timeline,
        "possible_motion_cadence": cadence,
        "exercise": explicit["exercise"],
        "exercise_evidence": explicit["source"],
        "exercise_confidence": explicit["confidence"],
        "speech_candidates": explicit["candidates"],
        "actual_pose_or_repetition_recognition": False,
    }
