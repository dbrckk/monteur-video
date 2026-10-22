"""Bounded, whole-shot RGB sampling for pose and gym-equipment inference.

For short clips preserve the exact original 1fps FFmpeg proxy. For long
clips distribute at most 14 frames' worth of sampled footage across up to
four independently sought windows, so last-minute subjects and equipment
are not ignored. No heavyweight decoding of the entire long source.
"""
from __future__ import annotations

import math
import subprocess
import time
from pathlib import Path

WIDTH, HEIGHT = 320, 180
FPS = 1
MAX_FRAMES = 14
MAX_WINDOWS = 4
WINDOW_SECONDS = 3.5
DECODE_BUDGET_SECONDS = 45


def _window_offsets(duration: float) -> tuple[tuple[float, float], ...]:
    """Return evenly spread non-overlapping windows, with bounded total work."""
    if not math.isfinite(duration) or duration <= 0:
        return ()
    if duration <= MAX_FRAMES:
        return ((0.0, duration),)
    count = min(MAX_WINDOWS, max(2, math.ceil(duration / 20)))
    length = min(WINDOW_SECONDS, MAX_FRAMES / count, duration / count)
    end = duration - length
    return tuple((end * i / (count - 1), length) for i in range(count))


def _read_proxy_window(source: Path, start: float, length: float,
                       timeout: float) -> list[bytes]:
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-i", str(source),
               "-t", f"{length:.3f}", "-an",
               "-vf", f"fps={FPS},scale={WIDTH}:{HEIGHT}:flags=fast_bilinear,format=rgb24",
               "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(command, check=True, capture_output=True,
                         timeout=timeout).stdout
    frame_size = WIDTH * HEIGHT * 3
    return [raw[i:i + frame_size] for i in range(0, len(raw), frame_size)
            if len(raw[i:i + frame_size]) == frame_size]


def sample_rgb_timeline(
    source: Path, start: float, duration: float
) -> list[bytes | tuple[float, bytes]]:
    """Capture localized RGB evidence across the full selected shot.

    Short shots return original plain bytes for compatibility; long shots
    return (local_video_second, rgb_frame) so MediaPipe timestamps and FFmpeg
    panning align with real shot time rather than 1-second mock indices.
    """
    windows = _window_offsets(duration)
    if not windows or not math.isfinite(start) or start < 0:
        return []
    if len(windows) == 1:
        return _read_proxy_window(Path(source), start, windows[0][1],
                                  DECODE_BUDGET_SECONDS)
    started = time.monotonic()
    samples = []
    for offset, length in windows:
        remaining = DECODE_BUDGET_SECONDS - (time.monotonic() - started)
        if remaining <= 1.0:
            raise subprocess.TimeoutExpired("ffmpeg full-shot sampling",
                                            DECODE_BUDGET_SECONDS)
        frames = _read_proxy_window(Path(source), start + offset, length,
                                    remaining)
        # FPS filter emits at most ceil(window duration) frames per window.
        for i, frame in enumerate(frames[:math.ceil(length)]):
            samples.append((min(duration, offset + i / FPS), frame))
        if len(samples) >= MAX_FRAMES:
            return samples[:MAX_FRAMES]
    return samples
