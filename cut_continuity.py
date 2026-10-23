"""Optimize real inter-rush picture cuts after each video has been rendered.

Only reorder when external chronology is absent. This measures RGB averages of
actual encoded first/last frames: it is a color-cut heuristic, not video scene
understanding or a substitute for capture timestamps.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path
from typing import Sequence


_FRAME_BYTES = 32 * 18 * 3


def _edge_rgb(video: Path, at: float) -> tuple[float, float, float] | None:
    """Decode one real low-resolution frame without persisting user imagery."""
    try:
        result = subprocess.run([
            "ffmpeg", "-hide_banner", "-nostdin", "-v", "error",
            "-ss", f"{max(0.0, at):.3f}", "-i", str(video),
            "-map", "0:v:0", "-frames:v", "1", "-an", "-sn",
            "-vf", "scale=32:18:flags=area,format=rgb24",
            "-f", "rawvideo", "pipe:1",
        ], check=True, capture_output=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    pixels = result.stdout
    if len(pixels) != _FRAME_BYTES:
        return None
    return tuple(sum(pixels[channel::3]) / (32 * 18)
                 for channel in (0, 1, 2))


def _jump(a: tuple[float, float, float],
          b: tuple[float, float, float]) -> float:
    return sum(abs(left - right) for left, right in zip(a, b)) / 36.0


def optimize_rendered_order(
    videos: Sequence[Path], durations: Sequence[float],
    phase_profiles: Sequence[dict] | None = None,
) -> tuple[list[int], dict]:
    """Held-Karp order of interior shots, with story opener and ending fixed.

    Uses the *rendered* first/last frames, not median source colors. Keeps the
    input order if evidence is missing or the visual improvement is negligible.
    At most 10 videos are accepted by the caller (8 movable intermediates).
    """
    count = len(videos)
    original = list(range(count))
    not_evaluated = {"evaluated": False, "reordered": False,
                     "method": "rendered_rgb_edge_dynamic_programming"}
    if count < 5 or count > 10 or count != len(durations):
        return original, {**not_evaluated, "reason": "insufficient_or_invalid_sources"}
    # Reliable relative-motion phases act as hard sequencing boundaries.
    # Never let matching RGB colors move an observed effort before a quieter
    # group or across an unknown, unsampled rush. Only comparable, consecutive
    # phases can be exchanged. With weak evidence, retain legacy RGB scoring.
    known_phases = {"observed_effort", "measured_low_motion"}
    phases = ([item.get("phase", "unknown") if isinstance(item, dict)
               else "unknown" for item in phase_profiles]
              if phase_profiles is not None and len(phase_profiles) == count
              else ["unknown"] * count)
    guarded = len(set(phases) & known_phases) >= 2
    groups = [0] * count
    if guarded:
        previous = None
        for i, phase in enumerate(phases):
            # Unknown/mixed material is a unique stationary anchor.
            key = phase if phase in known_phases else ("unverified", i)
            if i and key != previous:
                groups[i] = groups[i - 1] + 1
            elif i:
                groups[i] = groups[i - 1]
            previous = key
    edges = []
    for path, length in zip(videos, durations):
        if not math.isfinite(length) or length < 0.6:
            return original, {**not_evaluated, "reason": "invalid_rendered_duration"}
        beginning = _edge_rgb(Path(path), min(0.12, length * 0.1))
        ending = _edge_rgb(Path(path), max(0.0, length - 0.35))
        if beginning is None or ending is None:
            return original, {**not_evaluated, "reason": "edge_decode_unavailable"}
        edges.append((beginning, ending))

    def jump(i: int, j: int) -> float:
        return _jump(edges[i][1], edges[j][0])

    def objective(path: Sequence[int]) -> float:
        return sum(jump(a, b) for a, b in zip(path, path[1:])) + sum(
            0.28 * abs(index - rank) for rank, index in enumerate(path))

    baseline = objective(original)
    # Dynamic program covers all permutations of interior rushes without
    # factorial enumeration and preserves the current story opening/closing.
    interior = tuple(range(1, count - 1))
    states: dict[tuple[int, int], tuple[float, tuple[int, ...]]] = {}
    for bit, item in enumerate(interior):
        states[(1 << bit, item)] = (jump(0, item) + 0.28 * abs(item - 1), (item,))
    full_mask = (1 << len(interior)) - 1
    for mask in range(1, full_mask + 1):
        for last in interior:
            previous = states.get((mask, last))
            if previous is None:
                continue
            current_cost, path = previous
            next_rank = len(path) + 1
            for bit, item in enumerate(interior):
                flag = 1 << bit
                if mask & flag:
                    continue
                if guarded and any(
                        not (mask & (1 << other_bit))
                        and groups[other] < groups[item]
                        for other_bit, other in enumerate(interior)):
                    continue
                next_key = (mask | flag, item)
                score = current_cost + jump(last, item) + 0.28 * abs(item - next_rank)
                candidate = (score, path + (item,))
                if next_key not in states or candidate < states[next_key]:
                    states[next_key] = candidate
    candidates = [(score + jump(last, count - 1), path)
                  for (mask, last), (score, path) in states.items()
                  if mask == full_mask]
    if not candidates:
        return original, {**not_evaluated, "reason": "no_valid_path"}
    best_score, best_path = min(candidates)
    proposed = [0, *best_path, count - 1]
    accepted = (proposed != original and baseline - best_score >= 0.35
                and baseline - best_score >= 0.05 * max(baseline, 0.01))
    selected = proposed if accepted else original

    def actual_jump(path):
        return round(sum(jump(a, b) for a, b in zip(path, path[1:])), 3)

    return selected, {"evaluated": True, "reordered": accepted,
                      "method": "rendered_rgb_edge_dynamic_programming",
                      "boundary_color_jump_before": actual_jump(original),
                      "boundary_color_jump_after": actual_jump(selected),
                      "protected_first_last": True,
                      "phase_guard_enabled": guarded,
                      "phase_protected_transitions": (
                          sum(groups[i] != groups[i - 1]
                              for i in range(1, count)) if guarded else 0),
                      "not_semantic_scene_recognition": True}
