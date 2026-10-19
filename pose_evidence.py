"""Optional bounded human pose evidence from actual video frames.

Disabled by default. MediaPipe Solutions is deliberately optional because the
stable free CPU render service must remain functional without native ML wheels.
When enabled, infer only visible knee flexion/extension cycles, not squat
identity or correct exercise technique. Video and model errors fail open.
"""
from __future__ import annotations

import math
import os
import subprocess
from pathlib import Path
from statistics import median

WIDTH, HEIGHT = 192, 256
FRAME_SIZE = WIDTH * HEIGHT * 3


def joint_angle(a: tuple[float, float], b: tuple[float, float],
                c: tuple[float, float]) -> float | None:
    """Angle ABC in degrees; reject degenerate or non-finite landmarks."""
    values = [*a, *b, *c]
    if not all(math.isfinite(v) for v in values):
        return None
    ax, ay = a[0] - b[0], a[1] - b[1]
    cx, cy = c[0] - b[0], c[1] - b[1]
    lengths = math.hypot(ax, ay) * math.hypot(cx, cy)
    if lengths < 1e-7:
        return None
    return math.degrees(math.acos(max(-1.0, min(1.0, (ax * cx + ay * cy) / lengths))))


def knee_angles(landmarks: list, visibility: float = 0.65) -> list[float]:
    """MediaPipe knee angle landmarks; skip occluded joints, never interpolate."""
    pairs = [(23, 25, 27), (24, 26, 28)]
    found = []
    for hip, knee, ankle in pairs:
        if len(landmarks) <= ankle:
            continue
        group = [landmarks[k] for k in (hip, knee, ankle)]
        if any(not math.isfinite(float(p.visibility)) or p.visibility < visibility
               for p in group):
            continue
        angle = joint_angle((group[0].x, group[0].y),
                            (group[1].x, group[1].y),
                            (group[2].x, group[2].y))
        if angle is not None:
            found.append(angle)
    return found


def knee_flexion_evidence(frames: list[tuple[float, float]],
                          *, min_swing: float = 22.0) -> dict:
    """Verify repeated clear bend/extend transitions without counting exercises."""
    frames = sorted((float(t), float(angle)) for t, angle in frames
                    if math.isfinite(float(t)) and math.isfinite(float(angle))
                    and 0 <= angle <= 180)
    if len(frames) < 6:
        return {"detected": False, "reason": "insufficient_visible_joints"}
    if any(b[0] - a[0] > 2.2 or b[0] <= a[0]
           for a, b in zip(frames, frames[1:])):
        return {"detected": False, "reason": "unsampled_gaps"}
    angles = [v for _, v in frames]
    if max(angles) - min(angles) < min_swing:
        return {"detected": False, "reason": "limited_joint_range"}
    middle = median(angles)
    high = middle + 0.2 * min_swing
    low = middle - 0.2 * min_swing
    states = []
    for _, angle in frames:
        state = "extended" if angle >= high else "bent" if angle <= low else None
        if state is not None and (not states or states[-1] != state):
            states.append(state)
    if len(states) < 3:
        return {"detected": False, "reason": "insufficient_phase_changes"}
    return {"detected": True, "kind": "observed_knee_flexion_extension",
            "confidence": min(0.80, round(0.42 + 0.045 * (len(states) - 2), 2)),
            "knee_angle_range_degrees": round(max(angles) - min(angles), 1),
            "repetition_count": None,
            "exercise_classification": None}


def _decode_frames(source: Path, start: float, length: float):
    """At most eight low-resolution RGB frames per bounded FFmpeg subprocess."""
    command = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
               "-ss", str(start), "-i", str(source), "-t", str(min(8.0, length)),
               "-an", "-vf", f"fps=1,scale={WIDTH}:{HEIGHT}:force_original_aspect_ratio=decrease,"
                             f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2,format=rgb24",
               "-frames:v", "8", "-f", "rawvideo", "pipe:1"]
    raw = subprocess.run(command, capture_output=True, timeout=25, check=True).stdout
    for i in range(min(8, len(raw) // FRAME_SIZE)):
        yield start + i, raw[i * FRAME_SIZE:(i + 1) * FRAME_SIZE]


def analyze_pose(source: Path, duration: float) -> dict:
    """Opt-in pose inference. Preserve rendering when unavailable or unreliable."""
    if os.getenv("MONTEUR_ENABLE_POSE", "0") != "1":
        return {"status": "disabled", "method": "optional_mediapipe_pose"}
    try:
        import mediapipe as mp
        import numpy as np
        from editor import analysis_windows
        if not hasattr(mp, "solutions") or not hasattr(mp.solutions, "pose"):
            return {"status": "unavailable", "reason": "mediapipe_solutions_unavailable"}
        points: list[tuple[float, float]] = []
        with mp.solutions.pose.Pose(static_image_mode=True, model_complexity=0,
                                     min_detection_confidence=0.65) as pose:
            for start, length in analysis_windows(duration):
                for time, data in _decode_frames(source, start, length):
                    img = np.frombuffer(data, dtype=np.uint8).reshape((HEIGHT, WIDTH, 3))
                    result = pose.process(img)
                    if result.pose_landmarks is None:
                        continue
                    angles = knee_angles(result.pose_landmarks.landmark)
                    if angles:
                        points.append((time, median(angles)))
        evidence = knee_flexion_evidence(points)
        return {"status": "measured", "method": "mediapipe_visible_knee_angles",
                "valid_frames": len(points), **evidence}
    except (ImportError, FileNotFoundError):
        return {"status": "unavailable", "reason": "optional_pose_runtime_missing"}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}
