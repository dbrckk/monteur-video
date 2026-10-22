"""Plan a 9:16 crop around real visible landmarks and equipment evidence.

This is geometry from MediaPipe landmarks + near-hand shaft evidence, not a
trained bounding-box object detector. It prefers true full-width visibility
only when a safe, smooth 9:16 crop cannot cover the measured interval.
No dependencies, new models, or network calls.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from smart_reframe import ReframePlan

# Exclude face points: profiles and hats should not dominate framing decisions.
BODY = (11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)
TORSO = (11, 12, 23, 24)


@dataclass(frozen=True)
class HorizontalBounds:
    left: float
    right: float


def visible_composition_bounds(
    landmarks: list,
    bar: tuple[float, float] | None = None,
    dumbbell_score: float = 0.0,
) -> HorizontalBounds | None:
    """Enclose visible limbs, shaft endpoints and optional hand-held weight.

    Low-confidence, invisible or nonfinite landmarks never enter the frame.
    For a confident ImageNet dumbbell classification the box is a *hand margin*,
    not a fictitious predicted dumbbell bounding box.
    """
    if len(landmarks) <= max(BODY):
        return None
    def point(index: int):
        p = landmarks[index]
        x, y = getattr(p, "x", math.nan), getattr(p, "y", math.nan)
        confidence = min(getattr(p, "visibility", 0.0),
                         getattr(p, "presence", 0.0))
        if not all(math.isfinite(v) for v in (x, y, confidence)):
            return None
        if confidence < 0.62 or not (-0.04 <= x <= 1.04 and -0.04 <= y <= 1.04):
            return None
        return max(0.0, min(1.0, x))
    body = [p for i in BODY if (p := point(i)) is not None]
    torso = [p for i in TORSO if (p := point(i)) is not None]
    if len(body) < 5 or len(torso) < 3:
        return None
    lo, hi = min(body) - 0.025, max(body) + 0.025
    # Extra room around wrists avoids trimming small handheld apparatus.
    hands = [p for i in (15, 16) if (p := point(i)) is not None]
    for x in hands:
        lo = min(lo, x - 0.045)
        hi = max(hi, x + 0.045)
    if bar is not None:
        a, b = bar
        if (math.isfinite(a) and math.isfinite(b) and
                0 <= a < b <= 1):
            lo = min(lo, a - 0.020)
            hi = max(hi, b + 0.020)
    if math.isfinite(dumbbell_score) and dumbbell_score >= 0.68:
        for x in hands:
            # Classification only: exact endpoints are unknown.
            lo = min(lo, x - 0.090)
            hi = max(hi, x + 0.090)
    return HorizontalBounds(max(0.0, lo), min(1.0, hi))


def plan_safe_composition(
    readings: list[tuple],
    duration: float,
    crop_fraction: float,
) -> ReframePlan | None:
    """Shift toward all visible evidence, or choose a full shot if too wide.

    Each observation: (local_second, original_crop_x, normalized_body_interval).
    Return None if evidence is too sparse or the original crop is already good.
    Real crop coordinates are bounded [0,1] and constrained to 14% pan/s.
    """
    if (len(readings) < 3 or not math.isfinite(duration) or duration <= 0
            or not 0.05 < crop_fraction < 0.95):
        return None
    parsed = []
    for item in readings:
        if len(item) < 3 or item[2] is None:
            continue
        t, baseline, box = item[:3]
        if (not all(math.isfinite(v) for v in (t, baseline, box.left, box.right))
                or not 0 <= t <= duration
                or not 0 <= baseline <= 1
                or not 0 <= box.left < box.right <= 1):
            continue
        parsed.append((t, baseline, box))
    if len(parsed) < max(3, math.ceil(len(readings) * 0.60)):
        return None
    width = 1 - crop_fraction
    overflow = [x for x in parsed
                if x[2].right - x[2].left > crop_fraction - 0.010]
    if len(overflow) >= max(2, math.ceil(len(parsed) * 0.25)):
        return ReframePlan("composition_safe", (), 0.0)

    positions = []
    for when, current, box in parsed:
        if box.right - box.left > crop_fraction - 0.010:
            continue
        low = max(0.0, box.right - crop_fraction)
        high = min(width, box.left)
        if low > high + 0.000001:
            continue
        target_left = max(low, min(high, current * width))
        positions.append((when, current, target_left / width, box))
    if len(positions) < max(3, math.ceil(len(parsed) * 0.70)):
        return ReframePlan("composition_safe", (), 0.0)

    # Pan smoothly, but never claim a safe crop when the speed limit leaves
    # hands/equipment outside the picture at multiple observed frames.
    anchors = [(0.0, positions[0][2])]
    failures = 0
    useful_shifts = 0
    for t, baseline, desired, box in positions:
        t0, prior = anchors[-1]
        if t > t0 + 1e-5:
            max_travel = min(0.38, 0.14 * (t - t0))
            next_x = max(prior - max_travel, min(prior + max_travel, desired))
            anchors.append((t, next_x))
        else:
            next_x = prior
        useful_shifts += abs(desired - baseline) > 0.035
        crop_left = next_x * width
        if crop_left > box.left + 0.022 or crop_left + crop_fraction < box.right - 0.022:
            failures += 1
    if failures >= max(2, math.ceil(0.25 * len(positions))):
        return ReframePlan("composition_safe", (), 0.0)
    if duration > anchors[-1][0]:
        anchors.append((duration, anchors[-1][1]))
    if useful_shifts < max(2, math.ceil(len(positions) * 0.30)):
        return None
    return ReframePlan("composition_guided", tuple(anchors), 1 - failures / len(positions))
