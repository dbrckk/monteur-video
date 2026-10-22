"""Isolated CPU and memory probe for D-FINE-S Objects365 ONNX INT8.

This is a research-only, synthetic-input benchmark. It is *not* imported by
Monteur Studio production code, and cannot activate the model in a release.
Objects365 training-data use terms must be cleared independently before
deploying these weights in a monetized product.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import resource
import sys
import time
import urllib.request

REPOSITORY = "onnx-community/dfine_s_obj365-ONNX"
BASE = "https://huggingface.co/"
TARGET_CLASSES = {1: "Person", 323: "Dumbbell", 332: "Treadmill", 349: "Barbell"}
DOWNLOAD_MAX_BYTES = 65_000_000
MODEL_NAME = "onnx/model.onnx"


def _get_bytes(url: str, maximum: int) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "MonteurStudio-NonProduction-Benchmark/1.0"})
    with urllib.request.urlopen(request, timeout=75) as response:
        parts, size = [], 0
        while chunk := response.read(131072):
            size += len(chunk)
            if size > maximum:
                raise ValueError("Upstream data exceeds benchmark size cap")
            parts.append(chunk)
        return b"".join(parts)


def _memory_mb() -> dict[str, float | None]:
    result = {"process_peak_mib": round(
        resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1)}
    for key, path in [
        ("container_current_mib", "/sys/fs/cgroup/memory.current"),
        ("container_peak_mib", "/sys/fs/cgroup/memory.peak"),
        ("container_max_mib", "/sys/fs/cgroup/memory.max"),
    ]:
        try:
            raw = pathlib.Path(path).read_text().strip()
            result[key] = round(int(raw) / 1048576, 1) if raw != "max" else None
        except (OSError, ValueError):
            result[key] = None
    return result


def _tensor_shape(shape: list) -> tuple[int, ...]:
    # Do not allocate untrusted tensors over the 512-MiB benchmark budget.
    if len(shape) != 4:
        raise ValueError("Expected an RGB 4-D model input")
    dims = []
    for i, dimension in enumerate(shape):
        default = (1, 3, 640, 640)[i]
        value = dimension if isinstance(dimension, int) and dimension > 0 else default
        if value > (1 if i == 0 else 3 if i == 1 else 640):
            raise ValueError("Unexpectedly large model input")
        dims.append(value)
    if dims[0:2] != [1, 3]:
        raise ValueError("Unexpected channel layout")
    return tuple(dims)


def run() -> dict:
    started = time.monotonic()
    result = {
        "status": "not_qualified",
        "candidate": REPOSITORY,
        "model_file": MODEL_NAME,
        "production_enabled": False,
        "commercial_training_data_review_required": True,
        "measured_under_512_mib": False,
        "note": "Combined CPU model-load probe only, without FFmpeg/Whisper/uvicorn; not accuracy or commercial clearance.",
    }
    try:
        from numpy import float32, bool_ as np_bool, zeros, ones, isfinite
        import onnxruntime as ort

        # Resolve the exact immutable git snapshot for a reproducible report.
        metadata = json.loads(_get_bytes(
            "https://huggingface.co/api/models/" + REPOSITORY, 1_500_000))
        revision = metadata.get("sha")
        if not isinstance(revision, str) or len(revision) != 40:
            raise ValueError("Cannot pin source model snapshot")
        result["revision"] = revision
        root = BASE + REPOSITORY + "/resolve/" + revision + "/"
        config = json.loads(_get_bytes(root + "config.json", 450_000))
        labels = config["id2label"]
        for identifier, label in TARGET_CLASSES.items():
            if labels.get(str(identifier), "").lower() != label.lower():
                raise ValueError("Missing expected Objects365 label: " + label)
        result["verified_labels"] = TARGET_CLASSES

        model_bytes = _get_bytes(root + MODEL_NAME, DOWNLOAD_MAX_BYTES)
        result["weights_bytes"] = len(model_bytes)
        result["weights_sha256"] = hashlib.sha256(model_bytes).hexdigest()
        target = pathlib.Path("/tmp/gym_detector_int8.onnx")
        target.write_bytes(model_bytes)
        del model_bytes
        result["download_seconds"] = round(time.monotonic() - started, 2)
        result["after_download_memory"] = _memory_mb()

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        options.enable_mem_pattern = False
        options.enable_cpu_mem_arena = False
        session = ort.InferenceSession(
            str(target), sess_options=options, providers=["CPUExecutionProvider"])
        result["model_load_seconds"] = round(
            time.monotonic() - started - result["download_seconds"], 2)
        result["after_model_load_memory"] = _memory_mb()

        feeds = {}
        signatures = []
        for entry in session.get_inputs():
            signatures.append({
                "name": entry.name, "shape": list(entry.shape), "type": entry.type})
            if entry.name == "pixel_values":
                feeds[entry.name] = zeros(_tensor_shape(entry.shape), dtype=float32)
            elif entry.name in ("pixel_mask", "mask"):
                feeds[entry.name] = ones((1, 640, 640), dtype=np_bool)
            elif entry.name == "orig_target_sizes":
                from numpy import int64, array
                feeds[entry.name] = array([[640, 640]], dtype=int64)
            else:
                raise ValueError("Unexpected ONNX input: " + entry.name)
        if "pixel_values" not in feeds:
            raise ValueError("No valid RGB image input")
        result["input_signature"] = signatures
        inference_started = time.monotonic()
        output = session.run(None, feeds)
        result["inference_seconds_at_limited_cpu"] = round(
            time.monotonic() - inference_started, 2)
        result["output_signatures"] = [
            {"name": desc.name, "shape": list(values.shape),
             "finite": bool(isfinite(values).all())}
            for desc, values in zip(session.get_outputs(), output)
        ]
        result["dfine_only_memory"] = _memory_mb()

        # Keep D-FINE ONNX session and its arrays alive while testing real
        # MediaPipe Pose + ImageNet MobileNet coexistence in one 512MiB cgroup.
        # This mirrors the production crop inference stack, without importing
        # Whisper (which may need even more memory during transcription).
        import cv2
        import mediapipe as mp
        from scripts.download_pose_model import download as pose_download
        from scripts.download_dumbbell_model import install as dumbbell_download
        from numpy import uint8

        pose_path = pose_download(pathlib.Path("/tmp/benchmark_pose.task"))
        dumbbell_path = dumbbell_download(pathlib.Path("/tmp/benchmark_mobilenet.onnx"))
        landmark = mp.tasks.vision.PoseLandmarker.create_from_model_path(str(pose_path))
        picture = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=zeros((180, 320, 3), dtype=uint8))
        landmark.detect(picture)
        classifier = cv2.dnn.readNetFromONNX(str(dumbbell_path))
        classifier.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        classifier.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        classifier.setInput(zeros((1, 3, 224, 224), dtype=float32))
        mobile_output = classifier.forward().reshape(-1)
        if mobile_output.size != 1000 or not isfinite(mobile_output).all():
            raise ValueError("Invalid existing ImageNet model output")
        landmark.close()
        result["combined_stack_includes"] = [
            "D-FINE-S-FP32", "MediaPipe-Pose-Lite", "MobileNetV2-12"]
        result["combined_excludes"] = ["FFmpeg render", "faster-whisper", "uvicorn"]
        result["runtime_memory"] = _memory_mb()
        result["total_seconds"] = round(time.monotonic() - started, 2)
        safe_memory = result["runtime_memory"]["container_peak_mib"]
        result["measured_under_512_mib"] = (
            safe_memory is not None and safe_memory <= 512)
        outputs_valid = (
            len(output) >= 2 and
            all(isfinite(v).all() for v in output) and
            all(v.size > 0 for v in output)
        )
        result["status"] = (
            "benchmark_passed_license_pending"
            if outputs_valid and result["measured_under_512_mib"]
            else "not_qualified"
        )
    except Exception as exc:
        result["error"] = type(exc).__name__ + ": " + str(exc)[:350]
        result["runtime_memory"] = _memory_mb()
        result["total_seconds"] = round(time.monotonic() - started, 2)
    return result


if __name__ == "__main__":
    report = run()
    print("BENCHMARK_JSON=" + json.dumps(report, ensure_ascii=False, sort_keys=True),
          flush=True)
    # Failure intentionally leaves the production code and deployment intact.
    sys.exit(0 if report["status"] == "benchmark_passed_license_pending" else 2)
