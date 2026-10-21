"""Local CPU ImageNet dumbbell *classification* around MediaPipe wrists.

MobileNetV2-12 is Apache-2.0. It has ImageNet label 543 ('dumbbell').
This is NOT an object detector: results have no bounding boxes and cannot
guarantee that other gym gear, bars or machines are visible. Never upload
user frames, download models at inference time, or pretend unknown classes
were recognized.
"""
from __future__ import annotations

import math
import os
import threading
from functools import lru_cache
from pathlib import Path

FRAME_WIDTH, FRAME_HEIGHT = 320, 180
DUMBBELL_IMAGENET_INDEX = 543
MODEL_PATH = Path(__file__).resolve().parent / "models" / "mobilenetv2-12.onnx"
MODEL_MIN_BYTES, MODEL_MAX_BYTES = 10_000_000, 17_000_000
_LOCK = threading.Lock()


@lru_cache(maxsize=1)
def _network(model_path: str):
    import cv2
    net = cv2.dnn.readNetFromONNX(model_path)
    net.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    net.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    return net


def _candidate_hands(points: list, crop_fraction: float,
                     crop_x: float) -> list[tuple[float, float]]:
    if len(points) <= 16 or not (0.05 < crop_fraction < 1.0 and
                                 0 <= crop_x <= 1 and math.isfinite(crop_x)):
        return []
    left = (1 - crop_fraction) * crop_x
    right = left + crop_fraction
    candidates = []
    for index in (15, 16):
        p = points[index]
        x, y = getattr(p, "x", math.nan), getattr(p, "y", math.nan)
        score = min(getattr(p, "visibility", 0.0),
                    getattr(p, "presence", 0.0))
        if (all(math.isfinite(v) for v in (x, y, score))
                and 0.02 < x < 0.98 and 0.05 < y < 0.95 and score >= 0.70
                and min(abs(x - left), abs(x - right)) < 0.13):
            candidates.append((x, y))
    return candidates


def classify_handheld_dumbbell(frame: bytes, points: list,
                              crop_fraction: float, crop_x: float) -> float:
    """Return a conservative local dumbbell probability or 0 on failure.

    Only inspect windows adjacent to an at-risk crop boundary. The OpenCV
    runtime ships with optional MediaPipe; no torch or ONNX Runtime is needed.
    """
    if os.environ.get("MONTEUR_DUMBBELL_CLASSIFIER", "1") == "0":
        return 0.0
    if len(frame) != FRAME_WIDTH * FRAME_HEIGHT * 3:
        return 0.0
    hands = _candidate_hands(points, crop_fraction, crop_x)
    if not hands:
        return 0.0
    model = Path(os.environ.get("MONTEUR_DUMBBELL_MODEL", str(MODEL_PATH)))
    if not model.is_file() or not MODEL_MIN_BYTES <= model.stat().st_size <= MODEL_MAX_BYTES:
        return 0.0

    try:
        import cv2
        import numpy as np
        picture = np.frombuffer(frame, dtype=np.uint8).reshape(
            FRAME_HEIGHT, FRAME_WIDTH, 3)
        network = _network(str(model))
        best = 0.0
        for x, y in hands[:2]:
            cx, cy = round(x * FRAME_WIDTH), round(y * FRAME_HEIGHT)
            half = 66
            x0 = max(0, min(FRAME_WIDTH - 2 * half, cx - half))
            y0 = max(0, min(FRAME_HEIGHT - 2 * half, cy - half))
            patch = picture[y0:y0 + 2 * half, x0:x0 + 2 * half, :]
            resized = cv2.resize(patch, (224, 224),
                                 interpolation=cv2.INTER_LINEAR)
            image = resized.astype(np.float32) * (1.0 / 255.0)
            image = (image - np.array([0.485, 0.456, 0.406], np.float32)) / (
                np.array([0.229, 0.224, 0.225], np.float32))
            blob = np.ascontiguousarray(image.transpose(2, 0, 1)[None, ...])
            with _LOCK:
                network.setInput(blob)
                raw = network.forward().reshape(-1)
            if raw.size != 1000 or not np.all(np.isfinite(raw)):
                return 0.0
            shifted = raw - np.max(raw)
            exps = np.exp(shifted)
            probability = exps[DUMBBELL_IMAGENET_INDEX] / np.sum(exps)
            # Never select a weak label hidden under stronger classes.
            if int(np.argmax(raw)) == DUMBBELL_IMAGENET_INDEX:
                best = max(best, float(probability))
        return best
    except Exception:
        # Never compromise an otherwise renderable user's montage.
        return 0.0


def stable_dumbbell_evidence(readings: list[float]) -> bool:
    """Require sustained, high-confidence classification near crop edges."""
    if len(readings) < 3:
        return False
    hits = sum(v >= 0.68 and math.isfinite(v) for v in readings)
    return hits >= max(2, math.ceil(len(readings) * 0.35))
