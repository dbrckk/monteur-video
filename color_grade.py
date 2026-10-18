"""Conservative per-rush exposure, saturation and white-balance matching.

Camera metadata is not substituted for measured light. Match rushes to a shared
robust median; never apply unlimited automatic boosts to protect highlights and
skin tones. Only existing FFmpeg visual analysis is used (no extra AI costs).
"""
from __future__ import annotations

import math
from statistics import median
from typing import Sequence


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, value))


def rush_color_stats(samples: Sequence) -> dict | None:
    valid = [x for x in samples
             if all(math.isfinite(float(v)) for v in
                    (x.luminance, x.chroma_u, x.chroma_v))
             and 30 <= x.luminance <= 224 and x.detail >= 2]
    if len(valid) < 3:
        return None
    return {
        "luma": median(x.luminance for x in valid),
        "u": median(x.chroma_u for x in valid),
        "v": median(x.chroma_v for x in valid),
        "samples": len(valid),
    }


def grade_plan(samples_by_rush: Sequence[Sequence], theme: str = "fitness") -> dict:
    """Produce safe FFmpeg filter strings for each source and audit metadata.

    Preserve creative color casts where chroma measurements are extreme.
    White balance offsets are damped, with tiny limits on all coefficients.
    """
    stats = [rush_color_stats(samples) for samples in samples_by_rush]
    valid = [x for x in stats if x]
    target_luma = _clamp(median(x["luma"] for x in valid), 76, 168) if valid else 112.0
    target_u = _clamp(median(x["u"] for x in valid), 119, 137) if valid else 128.0
    target_v = _clamp(median(x["v"] for x in valid), 119, 137) if valid else 128.0
    style = {
        "fitness": (1.065, 1.055),
        "sport": (1.055, 1.075),
        "motivation": (1.055, 1.015),
        "lifestyle": (1.025, 1.035),
        "auto": (1.035, 1.035),
    }
    contrast, saturation = style.get(theme, style["auto"])
    output = []
    for item in stats:
        if not item:
            output.append({"filter": None, "measured": False,
                           "correction": "none", "reason": "insufficient_samples"})
            continue
        # FFmpeg eq brightness uses a roughly normalized [-1,+1] offset.
        bright = _clamp((target_luma - item["luma"]) / 255, -0.048, 0.048)
        red = _clamp((target_v - item["v"]) / 255 * 0.9, -0.05, 0.05)
        blue = _clamp((target_u - item["u"]) / 255 * 0.9, -0.05, 0.05)
        vf = (f"eq=contrast={contrast:.3f}:brightness={bright:.4f}:"
              f"saturation={saturation:.3f},"
              f"colorbalance=rs={red:.4f}:bs={blue:.4f}")
        output.append({"filter": vf, "measured": True,
                       "correction": "conservative_luma_chroma_match",
                       "luma_before": round(item["luma"], 2),
                       "luma_target": round(target_luma, 2),
                       "brightness": round(bright, 4),
                       "red_shadows": round(red, 4),
                       "blue_shadows": round(blue, 4)})
    return {
        "method": "robust_per_rush_luminance_chroma",
        "target_luma": round(target_luma, 2),
        "source_grades": output,
        "bounded": True,
        "reference": "median_of_valid_sources",
    }


def adaptive_shot_filters(samples: Sequence, clips: Sequence, theme: str,
                          shared_grade: dict | None = None,
                          source_index: int = 0) -> list[str | None]:
    """Match exposure/color shot-by-shot while preserving highlight headroom.

    Apply local corrections only where enough sampled frames exist; otherwise
    reuse the safe per-source grade. Robust per-shot statistics stop one over-
    exposed segment from forcing the entire recording to a bad midpoint.
    """
    reference = shared_grade or grade_plan([samples], theme)
    source_grades = reference.get("source_grades") or []
    base = source_grades[source_index].get("filter") if source_index < len(source_grades) else None
    target = float(reference.get("target_luma", 112))
    global_stats = rush_color_stats(samples)
    if global_stats is None:
        return [base for _ in clips]
    style = {
        "fitness": (1.065, 1.055), "sport": (1.055, 1.075),
        "motivation": (1.055, 1.015), "lifestyle": (1.025, 1.035),
        "auto": (1.035, 1.035),
    }
    contrast, saturation = style.get(theme, style["auto"])
    outputs: list[str | None] = []
    for clip in clips:
        local = rush_color_stats([p for p in samples if clip.start <= p.time < clip.end])
        if not local:
            outputs.append(base)
            continue
        # Mix global and shot-specific exposure to avoid flicker and oscillation.
        local_target = .72 * target + .28 * global_stats["luma"]
        brightness = _clamp((local_target - local["luma"]) / 255, -.065, .065)
        # Avoid trying to rescue crushed blacks and clipped skies with exposure.
        if local["luma"] < 45 or local["luma"] > 207:
            brightness = _clamp(brightness, -.025, .025)
        u_delta = _clamp((global_stats["u"] - local["u"]) / 255 * .65, -.035, .035)
        v_delta = _clamp((global_stats["v"] - local["v"]) / 255 * .65, -.035, .035)
        outputs.append(
            f"eq=contrast={contrast:.3f}:brightness={brightness:.4f}:"
            f"saturation={saturation:.3f},"
            f"colorbalance=rs={v_delta:.4f}:bs={u_delta:.4f}"
        )
    return outputs
