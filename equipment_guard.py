"""Conservative gym-equipment framing evidence near tracked wrists.

This is visual evidence of a *bar-like shaft*, not a semantic classifier.
No model downloads, remote API, new dependencies, or metadata claims about
a particular kind of equipment. False positives only affect shot composition.
"""
from __future__ import annotations

import math
from statistics import median

FRAME_WIDTH = 320
FRAME_HEIGHT = 180
LEFT_WRIST, RIGHT_WRIST = 15, 16


def _wrist_pair(points: list) -> tuple[tuple[int, int], tuple[int, int]] | None:
    if len(points) <= RIGHT_WRIST:
        return None
    result = []
    for index in (LEFT_WRIST, RIGHT_WRIST):
        point = points[index]
        x, y = getattr(point, "x", math.nan), getattr(point, "y", math.nan)
        confidence = min(getattr(point, "visibility", 0.0),
                         getattr(point, "presence", 0.0))
        if not all(math.isfinite(v) for v in (x, y, confidence)):
            return None
        if confidence < 0.67 or not (0.04 < x < 0.96 and 0.05 < y < 0.95):
            return None
        result.append((round(x * FRAME_WIDTH), round(y * FRAME_HEIGHT)))
    if abs(result[0][1] - result[1][1]) > 14:
        return None
    if abs(result[0][0] - result[1][0]) < 19:
        return None
    return result[0], result[1]


def bar_like_span(frame: bytes, points: list) -> tuple[float, float] | None:
    """Locate a long, narrow high-contrast horizontal segment across two grips.

    Wrist alignment and visibility are mandatory; a horizontal line elsewhere
    in the gym does not qualify. Require bar to project beyond both wrists.
    """
    if len(frame) != FRAME_WIDTH * FRAME_HEIGHT * 3:
        return None
    pair = _wrist_pair(points)
    if pair is None:
        return None
    (ax, ay), (bx, by) = pair
    left_wrist, right_wrist = sorted((ax, bx))
    mid_y = (ay + by) // 2
    values = memoryview(frame)

    def luma(row: int, col: int) -> int:
        pos = (row * FRAME_WIDTH + col) * 3
        return (54 * values[pos] + 183 * values[pos + 1] +
                19 * values[pos + 2]) // 256

    best = None
    # A tilted bar can cross several rows; do not claim arbitrary gym lines.
    for row in range(max(8, mid_y - 7), min(FRAME_HEIGHT - 8, mid_y + 8)):
        active = []
        for x in range(FRAME_WIDTH):
            current = luma(row, x)
            neighbors = (luma(row - 5, x) + luma(row + 5, x)) // 2
            active.append(abs(current - neighbors) >= 36)

        # Bridge short wrist/hand occlusions, but demand a dense thin shaft.
        first = None
        last_good = None
        hits = 0
        for x in range(FRAME_WIDTH + 12):
            marked = x < FRAME_WIDTH and active[x]
            if marked:
                if first is None:
                    first = x
                    hits = 0
                hits += 1
                last_good = x
            if first is not None and (not marked and x - last_good > 9 or x == FRAME_WIDTH + 11):
                end = last_good
                length = end - first + 1
                if (length >= round(0.36 * FRAME_WIDTH)
                        and hits >= 0.72 * length
                        and first <= left_wrist - 12
                        and end >= right_wrist + 12
                        and abs(row - ay) <= 12
                        and abs(row - by) <= 12):
                    candidate = (first, end, hits / length)
                    if best is None or (candidate[1] - candidate[0], candidate[2]) > (
                            best[1] - best[0], best[2]):
                        best = candidate
                first = None
                last_good = None
                hits = 0
    if best is None:
        return None
    return best[0] / FRAME_WIDTH, min(1.0, (best[1] + 1) / FRAME_WIDTH)


def stable_wide_bar(readings: list[tuple[float, float, float, tuple[float, float] | None]],
                    crop_fraction: float) -> bool:
    """Require temporally stable horizontal bar evidence wider than 9:16 crop."""
    detected = [(t, bounds) for t, _, _, bounds in readings if bounds is not None]
    if len(detected) < max(2, math.ceil(len(readings) * 0.4)):
        return False
    widths = [right - left for _, (left, right) in detected]
    if median(widths) < crop_fraction * 1.10:
        return False
    # A window rail behind the lifter is unlikely to follow the wrists reliably.
    centers = [(left + right) * 0.5 for _, (left, right) in detected]
    return max(centers) - min(centers) <= 0.27


def wide_limb_span(points: list, crop_fraction: float) -> bool:
    """Detect extreme hand spread that would crop both hands/equipment.

    This is not equipment recognition. It provides a generic safety fallback
    for cable pulls and wide grip exercises even with no obvious bar shaft.
    """
    pair = _wrist_pair(points)
    if pair is None:
        return False
    xs = [p[0] / FRAME_WIDTH for p in pair]
    # Keep a small safety margin around the hands and possible nearby weights.
    return max(xs) - min(xs) + 0.10 > crop_fraction * 1.65
