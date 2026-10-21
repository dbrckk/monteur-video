"""Offline, CPU-only human-pose reframing for 9:16 videos.

MediaPipe Pose Landmarker Lite is optional. No frames leave the server.
Missing model, dependency, or confident pose returns None, permitting the
existing visual-motion tracking to remain a complete fallback.
"""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
from statistics import median

from smart_reframe import ReframePlan
from equipment_guard import bar_like_span, stable_wide_bar, wide_limb_span

POSE_WIDTH, POSE_HEIGHT = 320, 180
POSE_FPS = 1
POSE_SECONDS = 14
MODEL_PATH = Path(__file__).resolve().parent / "models" / "pose_landmarker_lite.task"
# Shoulders, elbows, wrists, hips, knees, ankles. Excludes face details.
BODY = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
TORSO = (11, 12, 23, 24)


def _decode_rgb(source: Path, start: float, seconds: float) -> list[bytes]:
    """Limit untrusted input decode to a handful of low-resolution RGB frames."""
    seconds = min(seconds, POSE_SECONDS)
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
               "-ss", f"{start:.3f}", "-i", str(source), "-t", f"{seconds:.3f}",
               "-an", "-vf", f"fps={POSE_FPS},scale={POSE_WIDTH}:{POSE_HEIGHT}:flags=fast_bilinear,format=rgb24",
               "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(command, check=True, capture_output=True, timeout=35).stdout
    frame_bytes = POSE_WIDTH * POSE_HEIGHT * 3
    return [raw[i:i + frame_bytes] for i in range(0, len(raw), frame_bytes)
            if len(raw[i:i + frame_bytes]) == frame_bytes]


def _target_from_pose(points: list, fraction: float) -> tuple[float, float, float] | None:
    """Return normalized crop start, confidence and body width for one person.

    Extend towards visible wrists and ankles to avoid choosing just a face.
    The torso must be genuinely visible; inferred/occluded points are ignored.
    """
    if len(points) <= max(BODY):
        return None

    def visible(index):
        point = points[index]
        x = getattr(point, "x", float("nan"))
        y = getattr(point, "y", float("nan"))
        certainty = min(getattr(point, "visibility", 1.0),
                        getattr(point, "presence", 1.0))
        if not all(math.isfinite(v) for v in (x, y, certainty)):
            return None
        if certainty < 0.58 or not (-0.08 <= x <= 1.08 and -0.08 <= y <= 1.08):
            return None
        return max(0.0, min(1.0, x)), certainty

    torso = [item for i in TORSO if (item := visible(i)) is not None]
    body = [item for i in BODY if (item := visible(i)) is not None]
    if len(torso) < 3 or len(body) < 5:
        return None

    # Torso stabilizes crop when wrists and ankles move quickly around it.
    torso_x = median(p[0] for p in torso)
    xs = sorted(p[0] for p in body)
    low, high = xs[0], xs[-1]
    body_width = high - low
    # Offset slightly towards visible limbs and potential hand-held equipment.
    body_center = (low + high) / 2
    center = 0.58 * body_center + 0.42 * torso_x
    target = max(0.0, min(1.0, (center - fraction / 2) / (1 - fraction)))
    mean_visibility = sum(p[1] for p in torso) / len(torso)
    confidence = mean_visibility * min(1.0, len(body) / 9)
    return target, confidence, body_width


def _select_person(poses: list, fraction: float,
                   previous: float | None) -> tuple[float, float] | None:
    """Stay with an existing person if others enter the frame."""
    choices = []
    for pose in poses:
        result = _target_from_pose(pose, fraction)
        if result is None:
            continue
        x, conf, width = result
        score = conf + 0.08 * min(1.0, width / fraction)
        if previous is not None:
            score -= 0.60 * abs(x - previous)
        choices.append((score, x, conf))
    if not choices:
        return None
    _, x, confidence = max(choices, key=lambda row: row[0])
    return x, confidence


def _smooth_anchors(measured: list[tuple[float, float]], duration: float,
                    *, max_speed: float = 0.14) -> tuple[tuple[float, float], ...]:
    """Monotone times, clamped camera speed; hold last position after sampling."""
    points = [(0.0, measured[0][1])]
    for when, target in measured:
        previous_t, previous_x = points[-1]
        if when <= previous_t:
            continue
        travel = min(0.38, max_speed * (when - previous_t))
        position = max(previous_x - travel, min(previous_x + travel, target))
        points.append((when, position))
    if points[-1][0] < duration:
        points.append((duration, points[-1][1]))
    return tuple(points)


def _infer_poses(frames: list[bytes], model: Path,
                 fraction: float) -> list[tuple[float, float, float]]:
    """Run real Google Pose Landmarker detections on decoded RGB frames."""
    import mediapipe as mp
    import numpy as np

    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(model_asset_path=str(model),
                                          delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=2,
        min_pose_detection_confidence=0.55,
        min_pose_presence_confidence=0.55,
        min_tracking_confidence=0.55,
        output_segmentation_masks=False)
    measured = []
    previous = None
    with mp.tasks.vision.PoseLandmarker.create_from_options(opts) as detector:
        for i, frame in enumerate(frames):
            # Use writable contiguous storage; MediaPipe's C++ bridge expects it.
            values = np.frombuffer(frame, dtype=np.uint8).copy().reshape(
                POSE_HEIGHT, POSE_WIDTH, 3)
            picture = mp.Image(image_format=mp.ImageFormat.SRGB, data=values)
            result = detector.detect_for_video(picture, i * 1000 // POSE_FPS)
            chosen = _select_person(result.pose_landmarks, fraction, previous)
            if chosen is not None:
                x, confidence = chosen
                # Use the *same* detected athlete for wrists/equipment evidence.
                matches = [(abs(_target_from_pose(pose, fraction)[0] - x), pose)
                           for pose in result.pose_landmarks
                           if _target_from_pose(pose, fraction) is not None]
                person_points = min(matches, key=lambda item: item[0])[1] if matches else []
                bar_bounds = bar_like_span(frame, person_points)
                spread_risk = wide_limb_span(person_points, fraction)
                measured.append((i / POSE_FPS, x, confidence, bar_bounds, spread_risk))
                previous = x
    return measured


def plan_pose_reframe(source: Path, start: float, duration: float,
                      width: int, height: int) -> ReframePlan | None:
    """Track an athlete, keeping a full-frame safety layout for credible wide gear."""
    if os.environ.get("MONTEUR_POSE_REFRAME", "1") == "0":
        return None
    if not all(math.isfinite(v) for v in (start, duration)) or duration < 1.5:
        return None
    if width <= 0 or height <= 0 or width / height < 0.78:
        return None
    fraction = (height * 9 / 16) / width
    if fraction >= 0.86 or fraction <= 0:
        return None
    model = Path(os.environ.get("MONTEUR_POSE_MODEL", str(MODEL_PATH)))
    if not model.is_file():
        return None
    try:
        frames = _decode_rgb(Path(source), start, duration)
        if len(frames) < 2:
            return None
        measured = _infer_poses(frames, model, fraction)
        if len(measured) < 2 or len(measured) / len(frames) < 0.35:
            return None
        confidence = median(item[2] for item in measured)
        if confidence < 0.55:
            return None
        # Avoid huge jumps when a detected subject disappears then reappears.
        if any(b[0] - a[0] > 4.0 for a, b in zip(measured, measured[1:])):
            return None
        # An actual bar-like shaft near both tracked hands is crop-critical.
        # If it will not fit, keep the *entire* rush width over a blurred
        # background rather than misidentify a barbell or cut off plates.
        if stable_wide_bar([r[:4] for r in measured if len(r) >= 4],
                           fraction):
            return ReframePlan("equipment_safe", (), round(confidence, 3))
        # Even with invisible gear, an exceptionally wide grip merits a
        # conservative full-scene layout (not an equipment detection).
        spread = [r[4] for r in measured if len(r) >= 5]
        if (len(spread) >= 2 and sum(spread) >= max(2, math.ceil(len(spread) * 0.60))):
            return ReframePlan("wide_grip_safe", (), round(confidence, 3))
        anchors = _smooth_anchors([(t, x) for t, x, _ in measured], duration)
        if max(abs(x - 0.5) for _, x in anchors) < 0.035:
            return None
        return ReframePlan("pose_guided", anchors, round(confidence, 3))
    except (OSError, ValueError, RuntimeError, ImportError,
            subprocess.SubprocessError):
        return None
