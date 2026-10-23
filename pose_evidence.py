"""Optional bounded human pose evidence from actual video frames.

Enabled in the full Docker image with a local model; optional in lightweight
installations without native ML wheels. Uses the supported MediaPipe Tasks API
to detect visible knee/elbow flexion cycles, not exercise identity, repetition
counts or technique. Video/model errors preserve FFmpeg rendering.
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



def elbow_angles(landmarks: list, visibility: float = 0.65) -> list[float]:
    """Visible shoulder-elbow-wrist angles; no inference for hidden limbs."""
    found = []
    for shoulder, elbow, wrist in ((11, 13, 15), (12, 14, 16)):
        if len(landmarks) <= wrist:
            continue
        group = [landmarks[i] for i in (shoulder, elbow, wrist)]
        if any(not math.isfinite(float(getattr(p, "visibility", 0)))
               or not math.isfinite(float(getattr(p, "presence", 1.0)))
               or min(p.visibility, getattr(p, "presence", 1.0)) < visibility
               for p in group):
            continue
        angle = joint_angle((group[0].x, group[0].y),
                            (group[1].x, group[1].y),
                            (group[2].x, group[2].y))
        if angle is not None:
            found.append(angle)
    return found


def _measure_joint_windows(source: Path, windows: list[tuple[float, float]],
                           model_path: Path) -> list[list[dict]]:
    """Run the current MediaPipe Tasks API with bounded local CPU frames.

    Keep results separated by scan window; MediaPipe VIDEO timestamps must be
    strictly increasing. Multi-person footage is ambiguous without reliable
    identity tracking: never attach arbitrary joints to the subject.
    """
    import mediapipe as mp
    import numpy as np

    opts = mp.tasks.vision.PoseLandmarkerOptions(
        base_options=mp.tasks.BaseOptions(
            model_asset_path=str(model_path),
            delegate=mp.tasks.BaseOptions.Delegate.CPU),
        running_mode=mp.tasks.vision.RunningMode.VIDEO,
        num_poses=2,
        min_pose_detection_confidence=0.60,
        min_pose_presence_confidence=0.60,
        min_tracking_confidence=0.60,
        output_segmentation_masks=False)
    results = []
    previous_millis = -1
    with mp.tasks.vision.PoseLandmarker.create_from_options(opts) as detector:
        for start, length in windows:
            collected = []
            previous_center = None
            for time, rgb in _decode_frames(source, start, length):
                if len(rgb) != FRAME_SIZE:
                    continue
                millis = round(time * 1000)
                if millis <= previous_millis:
                    continue
                previous_millis = millis
                array = np.frombuffer(rgb, dtype=np.uint8).copy().reshape(
                    HEIGHT, WIDTH, 3)
                picture = mp.Image(image_format=mp.ImageFormat.SRGB, data=array)
                detected = detector.detect_for_video(picture, millis)
                # Do not switch from one athlete to another in group shots.
                if len(detected.pose_landmarks) != 1:
                    continue
                points = detected.pose_landmarks[0]
                # Stable torso position is a conservative identity safeguard.
                # Drop implausible one-second jumps rather than blend two gym
                # athletes into a fictional joint movement.
                torso = [p.x for index in (11, 12, 23, 24)
                         if index < len(points)
                         for p in (points[index],)
                         if (math.isfinite(p.x) and
                             min(getattr(p, "visibility", 0.0),
                                 getattr(p, "presence", 1.0)) >= 0.65)]
                if len(torso) < 2:
                    continue
                center = median(torso)
                if previous_center is not None and abs(center - previous_center) > 0.22:
                    continue
                previous_center = center
                knees = knee_angles(points)
                elbows = elbow_angles(points)
                collected.append({
                    "time": time,
                    "knee": median(knees) if knees else None,
                    "elbow": median(elbows) if elbows else None,
                })
            results.append(collected)
    return results


def analyze_pose(source: Path, duration: float) -> dict:
    """Bounded offline joint evidence, with FFmpeg-only fallback on errors.

    Only exact supported MediaPipe Tasks inference is accepted. This evidence
    may guide highlight selection; it does NOT identify an exercise, athlete,
    completed repetition or correct technique.
    """
    if os.getenv("MONTEUR_ENABLE_POSE", "0") != "1":
        return {"status": "disabled", "method": "mediapipe_tasks_visible_joints"}
    if not math.isfinite(duration) or duration < 3.0:
        return {"status": "insufficient_evidence", "reason": "video_too_short"}
    model = Path(os.getenv("MONTEUR_POSE_MODEL",
                            str(Path(__file__).resolve().parent /
                                "models" / "pose_landmarker_lite.task")))
    if not model.is_file():
        return {"status": "unavailable", "reason": "offline_pose_model_missing"}
    try:
        from editor import analysis_windows
        windows = analysis_windows(duration)
        if len(windows) > 3:
            windows = [windows[0], windows[len(windows) // 2], windows[-1]]
        observed = _measure_joint_windows(Path(source), windows, model)
        intervals = []
        for scan in observed:
            for joint in ("knee", "elbow"):
                points = [(frame["time"], frame[joint])
                          for frame in scan if frame.get(joint) is not None]
                report = knee_flexion_evidence(
                    points, min_swing=22.0 if joint == "knee" else 28.0)
                if not report["detected"]:
                    continue
                intervals.append({
                    "start": round(points[0][0], 2),
                    "end": round(min(duration, points[-1][0] + 0.5), 2),
                    "joint": joint,
                    "kind": "observed_joint_flexion_extension",
                    "confidence": report["confidence"],
                    "not_exercise_repetition_count": True,
                })
        return {
            "status": "measured" if any(observed) else "insufficient_evidence",
            "method": "mediapipe_tasks_visible_joints",
            "valid_frames": sum(len(scan) for scan in observed),
            "motion_intervals": intervals,
            "detected": bool(intervals),
            "exercise_classification": None,
            "repetition_count": None,
        }
    except (ImportError, FileNotFoundError):
        return {"status": "unavailable", "reason": "optional_pose_runtime_missing"}
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError,
            AttributeError, TypeError) as exc:
        return {"status": "unavailable", "reason": type(exc).__name__}
