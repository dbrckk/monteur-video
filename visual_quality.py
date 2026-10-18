"""Low-memory FFmpeg visual signals for editing, not person/action recognition.

At 2 FPS and 192 pixels wide, measure frame-to-frame change, luminance,
and edge detail in one decode. Helps avoid black/frozen/out-of-focus sections.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from editor import execute


@dataclass(frozen=True)
class VisualSample:
    time: float
    luminance: float
    motion: float
    detail: float


def _read_metrics(path: Path) -> dict[float, float]:
    values: dict[float, float] = {}
    timestamp = None
    for line in path.read_text(encoding="utf-8").splitlines():
        found_time = re.search(r"pts_time:([0-9]+(?:\.[0-9]+)?)", line)
        if found_time:
            timestamp = round(float(found_time.group(1)), 2)
        found_value = re.search(r"lavfi\.signalstats\.YAVG=([0-9]+(?:\.[0-9]+)?)", line)
        if found_value and timestamp is not None:
            values[timestamp] = float(found_value.group(1))
    return values


def analyze_visual(source: Path) -> list[VisualSample]:
    """Return sampled visual indicators; safely degrade if analysis fails.

    Scores are not biometric, object-detection, or action-classification signals.
    No frame images or source footage are retained by this analyzer.
    """
    try:
        with tempfile.TemporaryDirectory(prefix="monteur-visual-") as temporary:
            folder = Path(temporary)
            paths = {key: folder / (key + ".txt")
                     for key in ("light", "motion", "detail")}
            graph = (
                "[0:v]fps=2,scale=192:-2,format=yuv420p,split=3[l][m][e];"
                f"[l]signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={paths['light']}[lo];"
                f"[m]tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={paths['motion']}[mo];"
                f"[e]sobel,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={paths['detail']}[eo]"
            )
            execute(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                     "-filter_complex_threads", "1", "-i", str(source),
                     "-filter_complex", graph, "-map", "[lo]", "-map", "[mo]",
                     "-map", "[eo]", "-an", "-f", "null", "-"])
            light = _read_metrics(paths["light"])
            motion = _read_metrics(paths["motion"])
            detail = _read_metrics(paths["detail"])
            return [VisualSample(t, light[t], motion.get(t, 0.0), detail.get(t, 0.0))
                    for t in sorted(light)]
    except (OSError, RuntimeError, ValueError):
        # A quality heuristic must never prevent an otherwise valid video render.
        return []


def clip_quality(samples: list[VisualSample], start: float, end: float) -> tuple[float, bool]:
    """(score adjustment, unusable) for a candidate; reject predominantly blank footage."""
    window = [x for x in samples if start <= x.time < end]
    if not window:
        return 0.0, False
    blank = sum(x.luminance < 25 or x.luminance > 230 or
                (x.detail < 2 and x.motion < 0.35) for x in window) / len(window)
    motion = sum(min(x.motion, 24) for x in window) / len(window)
    detail = sum(min(x.detail, 48) for x in window) / len(window)
    bonus = min(2.4, motion / 5.5) + min(1.1, detail / 26) - 6 * blank
    return round(bonus, 3), blank >= 0.6 and len(window) >= 2

def usable_ranges(samples: list[VisualSample], duration: float) -> list[tuple[float, float]]:
    """Only include visible footage, preserving silent workouts and static camera shots."""
    if not samples:
        return []
    intervals: list[tuple[float, float]] = []
    start: float | None = None
    last = 0.0
    for sample in samples:
        visible = (25 <= sample.luminance <= 230 and
                   (sample.detail >= 2 or sample.motion >= 0.35))
        if visible:
            if start is None:
                start = sample.time
            last = sample.time
        elif start is not None:
            end = min(duration, sample.time)
            if end - start >= 1:
                intervals.append((start, end))
            start = None
    if start is not None:
        end = min(duration, max(last + 0.5, duration if duration - last < 1.0 else last + 0.5))
        if end - start >= 1:
            intervals.append((start, end))
    return intervals
