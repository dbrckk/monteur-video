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
    # A [0,255] interval is the backwards-compatible "not measured" sentinel.
    measured = [x for x in valid if 0 <= x.luma_low <= x.luma_high <= 255
                and (x.luma_low > 0 or x.luma_high < 255)]
    return {
        "low": median(x.luma_low for x in measured) if measured else None,
        "high": median(x.luma_high for x in measured) if measured else None,
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
        # Percentile-based headroom prevents pushing already clipped whites
        # higher or crushing shadow detail in backlit phone recordings.
        if item["high"] is not None and item["high"] >= 236:
            bright = min(bright, 0.0)
        if item["low"] is not None and item["low"] <= 14:
            bright = max(bright, 0.0)
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
        "target_u": round(target_u, 2),
        "target_v": round(target_v, 2),
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
        # Local highlight/shadow protection, even when the rush average
        # exposure is deceptively normal.
        if local["high"] is not None and local["high"] >= 236:
            brightness = min(brightness, 0.0)
        if local["low"] is not None and local["low"] <= 14:
            brightness = max(brightness, 0.0)
        # Avoid trying to rescue crushed blacks and clipped skies with exposure.
        if local["luma"] < 45 or local["luma"] > 207:
            brightness = _clamp(brightness, -.025, .025)
        # A shared across-rush white balance is essential. Blend 70% global
        # reference with 30% of this rush's median to preserve lighting intent.
        target_u = .70 * float(reference.get("target_u", global_stats["u"])) + .30 * global_stats["u"]
        target_v = .70 * float(reference.get("target_v", global_stats["v"])) + .30 * global_stats["v"]
        u_delta = _clamp((target_u - local["u"]) / 255 * .75, -.045, .045)
        v_delta = _clamp((target_v - local["v"]) / 255 * .75, -.045, .045)
        outputs.append(
            f"eq=contrast={contrast:.3f}:brightness={brightness:.4f}:"
            f"saturation={saturation:.3f},"
            f"colorbalance=rs={v_delta:.4f}:bs={u_delta:.4f}"
        )
    return outputs
