"""Low-memory FFmpeg visual signals for editing, not person/action recognition.

At 2 FPS and 192 pixels wide, measure frame-to-frame change, luminance,
and edge detail in one decode. Helps avoid black/frozen/out-of-focus sections.
"""
from __future__ import annotations

import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from editor import analysis_windows, execute, probe_media


@dataclass(frozen=True)
class VisualSample:
    time: float
    luminance: float
    motion: float
    detail: float
    chroma_u: float = 128.0
    chroma_v: float = 128.0


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


def _read_chroma(path: Path) -> dict[float, tuple[float, float]]:
    values: dict[float, tuple[float, float]] = {}
    time = None
    u = v = None
    for line in path.read_text(encoding="utf-8").splitlines():
        found_time = re.search(r"pts_time:([0-9]+(?:\.[0-9]+)?)", line)
        if found_time:
            if time is not None and u is not None and v is not None:
                values[time] = (u, v)
            time = round(float(found_time.group(1)), 2)
            u = v = None
        found_u = re.search(r"lavfi\.signalstats\.UAVG=([0-9]+(?:\.[0-9]+)?)", line)
        found_v = re.search(r"lavfi\.signalstats\.VAVG=([0-9]+(?:\.[0-9]+)?)", line)
        if found_u:
            u = float(found_u.group(1))
        if found_v:
            v = float(found_v.group(1))
    if time is not None and u is not None and v is not None:
        values[time] = (u, v)
    return values


def analyze_visual(source: Path, duration: float | None = None,
                   progress: Callable[[float], None] | None = None) -> list[VisualSample]:
    """Inspect representative windows rather than exhaustively decoding long footage.

    Return actual source-relative timestamps so highlights can span the full rush.
    A broken sampled interval does not prevent the other intervals from being used.
    """
    try:
        duration = float(duration if duration is not None else probe_media(source)["duration"])
        windows = analysis_windows(duration)
        collected: list[VisualSample] = []
        with tempfile.TemporaryDirectory(prefix="monteur-visual-") as temporary:
            folder = Path(temporary)
            paths = {key: folder / (key + ".txt")
                     for key in ("light", "motion", "detail")}
            graph = (
                "[0:v]fps=2,scale=192:-2,format=yuv420p,split=3[l][m][e];"
                f"[l]signalstats,metadata=print:file={paths['light']}[lo];"
                f"[m]tblend=all_mode=difference,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={paths['motion']}[mo];"
                f"[e]sobel,signalstats,metadata=print:key=lavfi.signalstats.YAVG:file={paths['detail']}[eo]"
            )
            for i, (start, length) in enumerate(windows):
                try:
                    for path in paths.values():
                        path.unlink(missing_ok=True)
                    execute(["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                             "-filter_complex_threads", "1", "-ss", str(start),
                             "-i", str(source), "-t", str(length),
                             "-filter_complex", graph, "-map", "[lo]", "-map", "[mo]",
                             "-map", "[eo]", "-an", "-f", "null", "-"], timeout=90)
                    light = _read_metrics(paths["light"])
                    chroma = _read_chroma(paths["light"])
                    motion = _read_metrics(paths["motion"])
                    detail = _read_metrics(paths["detail"])
                    collected.extend(
                        VisualSample(round(start + t, 2), light[t],
                                     motion.get(t, 0.0), detail.get(t, 0.0),
                                     *chroma.get(t, (128.0, 128.0)))
                        for t in sorted(light)
                    )
                except (OSError, RuntimeError, ValueError):
                    pass
                if progress:
                    progress((i + 1) / len(windows))
        return collected
    except (OSError, RuntimeError, ValueError):
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
    visible_frames = [(25 <= s.luminance <= 230 and
                       (s.detail >= 2 or s.motion >= 0.35)) for s in samples]
    # Motion essentially zero for >=3s is usually a frozen frame or dead time.
    # Do not discard individual static gym frames between moving repetitions.
    i = 0
    while i < len(samples):
        if samples[i].motion > 0.25:
            i += 1
            continue
        j = i + 1
        while j < len(samples) and samples[j].motion <= 0.25:
            j += 1
        if j - i >= 6:
            for k in range(i, j):
                visible_frames[k] = False
        i = j
    start: float | None = None
    last: float | None = None
    for sample, visible in zip(samples, visible_frames):
        # Sparse window sampling must not mark unseen minutes as verified footage.
        if start is not None and last is not None and sample.time - last > 1.5:
            end = min(duration, last + 0.5)
            if end - start >= 1:
                intervals.append((start, end))
            start = None
        if visible:
            if start is None:
                start = sample.time
            last = sample.time
        else:
            if start is not None:
                end = min(duration, sample.time)
                if end - start >= 1:
                    intervals.append((start, end))
                start = None
            last = sample.time
    if start is not None and last is not None:
        end = min(duration, last + 0.5)
        if end - start >= 1:
            intervals.append((start, end))
    return intervals
