"""Dependency-free, conservative motion-guided crop for short vertical edits.

This follows localized image motion, *not* a detected person/face. A stable
center crop is used when the video signal is ambiguous or the analysis fails.
"""
from __future__ import annotations

import math
import subprocess
from dataclasses import dataclass
from pathlib import Path

WIDTH, HEIGHT = 96, 54
FPS = 2
MAX_ANALYZE_SECONDS = 18


@dataclass(frozen=True)
class ReframePlan:
    mode: str
    anchors: tuple[tuple[float, float], ...] = ()  # local seconds, crop x from 0 to 1
    confidence: float = 0.0


def _sample_gray(source: Path, start: float, seconds: float) -> list[bytes]:
    """Read a bounded low-resolution proxy, avoiding any ML downloads."""
    seconds = min(seconds, MAX_ANALYZE_SECONDS)
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{seconds:.3f}",
               "-an", "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=fast_bilinear,format=gray",
               "-pix_fmt", "gray", "-f", "rawvideo", "pipe:1"]
    output = subprocess.run(command, check=True, capture_output=True,
                            timeout=35).stdout
    frame_size = WIDTH * HEIGHT
    return [output[i:i + frame_size] for i in range(0, len(output), frame_size)
            if len(output[i:i + frame_size]) == frame_size]


def _window_focus(frames: list[bytes], crop_fraction: float) -> tuple[float, float] | None:
    """Locate a compact, coherent moving region using grayscale frame deltas."""
    if len(frames) < 3:
        return None
    histogram = [0.0] * WIDTH
    intensity = 0.0
    compared = 0
    rows = range(4, HEIGHT - 4, 2)
    for previous, current in zip(frames, frames[1:]):
        # Ignore global exposure changes (e.g. auto-exposure or light flicker).
        old_mean = sum(previous) / len(previous)
        new_mean = sum(current) / len(current)
        global_shift = abs(new_mean - old_mean)
        for row in rows:
            base = row * WIDTH
            for col in range(WIDTH):
                difference = abs(current[base + col] - previous[base + col])
                motion = max(0.0, difference - global_shift - 6)
                histogram[col] += motion
                intensity += motion
                compared += 1
    if compared == 0 or intensity / compared < 1.65:
        return None
    # Motion generated across the whole image is usually camera movement.
    crop_columns = max(4, min(WIDTH - 1, round(WIDTH * crop_fraction)))
    sliding = sum(histogram[:crop_columns])
    peak = sliding
    for col in range(crop_columns, WIDTH):
        sliding += histogram[col] - histogram[col - crop_columns]
        peak = max(peak, sliding)
    concentration = peak / intensity if intensity else 0.0
    if concentration < max(0.54, crop_fraction + 0.17):
        return None
    centroid = sum(col * count for col, count in enumerate(histogram)) / intensity
    available = WIDTH - crop_columns
    normalized = max(0.0, min(1.0, (centroid - crop_columns / 2) / available))
    return normalized, min(1.0, (concentration - crop_fraction) / (1 - crop_fraction))


def plan_vertical_reframe(source: Path, start: float, duration: float,
                          width: int, height: int) -> ReframePlan:
    """Generate slowly moving crop anchors; fail closed to center crop.

    Work is bounded to the beginning of each selected shot (<=18s, 96x54).
    Avoid pan on static images, global lighting changes and broad motion.
    """
    if not all(math.isfinite(v) for v in (start, duration)) or duration < 1.2:
        return ReframePlan("center_fallback")
    if width <= 0 or height <= 0 or width / height < 0.78:
        return ReframePlan("center_fallback")
    crop_fraction = (height * 9 / 16) / width
    if crop_fraction >= 0.86:
        return ReframePlan("center_fallback")
    try:
        frames = _sample_gray(Path(source), start, duration)
    except (OSError, subprocess.SubprocessError, ValueError):
        return ReframePlan("center_fallback")
    if len(frames) < 4:
        return ReframePlan("center_fallback")

    measured = []
    # Three-second groups produce at most six tracking anchors.
    for index in range(0, len(frames) - 1, 6):
        window = frames[index:min(index + 7, len(frames))]
        result = _window_focus(window, crop_fraction)
        if result is not None:
            x, confidence = result
            measured.append((min(duration, (index + (len(window) - 1) / 2) / FPS),
                             x, confidence))
    if not measured:
        return ReframePlan("center_fallback")
    confidence = sum(item[2] for item in measured) / len(measured)
    # With just a transient moving object, prefer a stable and conservative crop.
    if len(measured) < 2 and duration > 4.5:
        return ReframePlan("center_fallback")
    anchors = [(0.0, measured[0][1])]
    last_time, last_x = anchors[0]
    for timestamp, wanted, _ in measured:
        if timestamp <= last_time + 1e-5:
            continue
        # Maximum movement speed is 14% of the available horizontal span/s.
        travel = min(0.38, 0.14 * (timestamp - last_time))
        current = max(last_x - travel, min(last_x + travel, wanted))
        anchors.append((timestamp, current))
        last_time, last_x = timestamp, current
    if duration > last_time:
        anchors.append((duration, last_x))
    if max(abs(x - 0.5) for _, x in anchors) < 0.035:
        return ReframePlan("center_fallback")
    return ReframePlan("motion_guided", tuple(anchors), round(confidence, 3))


def ffmpeg_crop_x(plan: ReframePlan) -> str:
    """Continuous, bounded linear interpolation for FFmpeg's per-frame crop x."""
    if plan.mode != "motion_guided" or not plan.anchors:
        return "(iw-ow)/2"
    points = plan.anchors
    expression = f"{points[-1][1]:.5f}"
    for (t0, x0), (t1, x1) in reversed(list(zip(points, points[1:]))):
        delta = max(t1 - t0, 0.001)
        interpolated = (f"({x0:.5f}+({x1-x0:.5f})*"
                        f"max(0\\,min(1\\,(t-{t0:.3f})/{delta:.3f})))")
        expression = f"if(lt(t\\,{t1:.3f})\\,{interpolated}\\,{expression})"
    return f"(iw-ow)*({expression})"
