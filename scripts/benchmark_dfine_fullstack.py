"""Research-only, hard-memory-limited full-stack D-FINE feasibility probe.

This file is never imported by the public app. Only the isolated GitHub
Actions container executes it. Objects365 academic-only dataset terms make the
pretrained D-FINE weights unsuitable for unapproved commercial deployment.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request
import wave

from scripts.benchmark_dfine_cpu import _get_bytes, _memory_mb, _tensor_shape

MODEL_REPO = "onnx-community/dfine_s_obj365-ONNX"
MODEL_REVISION = "a61e4cdfe4f9d3188a305d91e37dbf38688ffbb8"
MODEL_SHA256 = "372feaa33ac6ba67d7df8589628f6abc395b3c6981c4edc70dfcfe2949751120"
MODEL_MAX_BYTES = 45_000_000
CGROUP_LIMIT_MIB = 512
QUALIFICATION_PEAK_MIB = 420
EXPECTED_OUTPUT_SHAPES = ((1, 300, 366), (1, 300, 4))


def _assert_evidence(outputs) -> None:
    import numpy as np

    if len(outputs) != 2:
        raise ValueError("Expected D-FINE logits and bounding box arrays")
    if tuple(tuple(x.shape) for x in outputs) != EXPECTED_OUTPUT_SHAPES:
        raise ValueError("Unexpected ONNX output tensors")
    if not all(np.isfinite(x).all() for x in outputs):
        raise ValueError("Non-finite D-FINE outputs")


def _record(result: dict, stage: str) -> None:
    result["stages"].append({"stage": stage, "memory": _memory_mb(),
                             "elapsed_seconds": round(time.monotonic() -
                                                      result["_start"], 2)})


def _download_detector() -> Path:
    url = (f"https://huggingface.co/{MODEL_REPO}/resolve/{MODEL_REVISION}/"
           "onnx/model.onnx")
    payload = _get_bytes(url, MODEL_MAX_BYTES)
    if hashlib.sha256(payload).hexdigest() != MODEL_SHA256:
        raise ValueError("Detector SHA-256 mismatch (reject unexpected weights)")
    path = Path("/tmp/dfine-small-objects365-fp32.onnx")
    path.write_bytes(payload)
    del payload
    return path


def _run_ffmpeg(output: Path) -> None:
    """Run a short actual x264 portrait render while ML models remain alive."""
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
        "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=10:duration=1.2",
        "-vf", "scale=360:640:force_original_aspect_ratio=increase,"
               "crop=360:640,format=yuv420p",
        "-threads", "1", "-c:v", "libx264", "-preset", "ultrafast",
        "-crf", "28", "-an", "-t", "1.2", str(output)
    ]
    subprocess.run(command, check=True, capture_output=True, timeout=80)
    if not output.is_file() or output.stat().st_size < 5000:
        raise ValueError("Real FFmpeg output missing or unexpectedly small")


def _create_silent_wav(output: Path) -> None:
    with wave.open(str(output), "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(16000)
        audio.writeframes(b"\0" * 16000 * 2)


def _start_real_api(result: dict) -> subprocess.Popen:
    """Start the actual FastAPI server under the SAME 512-MiB cgroup."""
    env = dict(os.environ)
    env["PORT"] = "19080"
    env["APP_API_TOKEN"] = "bench-only-private-token-2026-long"
    env["EDITOR_DATA_DIR"] = "/tmp/monteur-fullstack-benchmark-data"
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "server:app",
         "--host", "127.0.0.1", "--port", "19080", "--workers", "1"],
        env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT)
    started = time.monotonic()
    while time.monotonic() - started < 50:
        if proc.poll() is not None:
            raise RuntimeError(f"Production API exited early: {proc.returncode}")
        try:
            with urllib.request.urlopen(
                    "http://127.0.0.1:19080/api/health", timeout=3) as response:
                data = json.load(response)
            if data.get("ok") is True:
                result["api_health_ok"] = True
                return proc
        except (urllib.error.URLError, TimeoutError, ValueError):
            pass
        time.sleep(1)
    proc.terminate()
    raise TimeoutError("Production API not ready under 0.1-CPU constraint")


def run() -> dict:
    begin = time.monotonic()
    result = {
        "_start": begin,
        "status": "not_qualified",
        "research_only": True,
        "production_enabled": False,
        "commercial_use_approved": False,
        "license_gate": "blocked_academic_only_Objects365_terms",
        "source": MODEL_REPO,
        "source_revision": MODEL_REVISION,
        "weights_sha256": MODEL_SHA256,
        "memory_limit_mib": CGROUP_LIMIT_MIB,
        "headroom_gate_mib": QUALIFICATION_PEAK_MIB,
        "cpu_limit_cores": 0.1,
        "stages": [],
        "note": "Tests synthetic footage only. No detector is installed in Render.",
    }
    api = None
    try:
        import numpy as np
        import onnxruntime as ort
        import cv2
        import mediapipe as mp
        from faster_whisper import WhisperModel

        _record(result, "dependencies_loaded")

        weights = _download_detector()
        _record(result, "dfine_model_downloaded_and_verified")

        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_BASIC
        options.enable_mem_pattern = False
        options.enable_cpu_mem_arena = False
        detector = ort.InferenceSession(
            str(weights), sess_options=options,
            providers=["CPUExecutionProvider"])
        inputs = detector.get_inputs()
        if len(inputs) != 1 or inputs[0].name != "pixel_values":
            raise ValueError("Unexpected detector model input")
        image = np.zeros(_tensor_shape(inputs[0].shape), np.float32)
        detected = detector.run(None, {"pixel_values": image})
        _assert_evidence(detected)
        _record(result, "dfine_cpu_inference")

        pose = mp.tasks.vision.PoseLandmarker.create_from_model_path(
            os.environ["MONTEUR_POSE_MODEL"])
        picture = mp.Image(image_format=mp.ImageFormat.SRGB,
                           data=np.zeros((180, 320, 3), dtype=np.uint8))
        pose.detect(picture)
        _record(result, "mediapipe_cpu_inference")

        classifier = cv2.dnn.readNetFromONNX(
            os.environ["MONTEUR_DUMBBELL_MODEL"])
        classifier.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
        classifier.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
        classifier.setInput(np.zeros((1, 3, 224, 224), np.float32))
        classified = classifier.forward().reshape(-1)
        if classified.size != 1000 or not np.isfinite(classified).all():
            raise ValueError("MobileNet recognition runtime failed")
        _record(result, "mobilenet_cpu_inference")

        # Hold detector, pose, classifier and their outputs in RAM while the
        # genuine ASR model and HTTP server are started.
        whisper = WhisperModel("tiny", device="cpu", compute_type="int8",
                               cpu_threads=1, num_workers=1,
                               download_root="/tmp/monteur-whisper-tiny")
        _record(result, "faster_whisper_tiny_loaded")

        wav = Path("/tmp/monteur-bench-silence.wav")
        _create_silent_wav(wav)
        segments, _ = whisper.transcribe(
            str(wav), language="fr", beam_size=1, best_of=1,
            vad_filter=False, condition_on_previous_text=False)
        # Consume generator so the real ASR engine actually executes.
        list(segments)
        _record(result, "faster_whisper_tiny_transcription")

        api = _start_real_api(result)
        _record(result, "real_api_health_checked")

        output = Path("/tmp/monteur-fullstack-portrait.mp4")
        _run_ffmpeg(output)
        _record(result, "ffmpeg_portrait_mp4_rendered_with_all_models_loaded")

        result["output_bytes"] = output.stat().st_size
        result["observed_cgroup_peak_mib"] = _memory_mb()["container_peak_mib"]
        result["reserve_mib"] = (
            round(CGROUP_LIMIT_MIB - result["observed_cgroup_peak_mib"], 1)
            if result["observed_cgroup_peak_mib"] is not None else None)
        result["engineering_fit"] = (
            result["observed_cgroup_peak_mib"] is not None
            and result["observed_cgroup_peak_mib"] <= QUALIFICATION_PEAK_MIB)
        result["status"] = ("engineering_benchmark_passed_rights_blocked"
                            if result["engineering_fit"] else "not_qualified")
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:380]}"
        result["status"] = "not_qualified"
        _record(result, "failed")
    finally:
        if api is not None:
            api.terminate()
            try:
                api.wait(timeout=6)
            except subprocess.TimeoutExpired:
                api.kill()
                api.wait(timeout=6)
        result["duration_seconds"] = round(time.monotonic() - begin, 2)
        result["last_memory"] = _memory_mb()
        result.pop("_start", None)
    return result


if __name__ == "__main__":
    answer = run()
    print("FULLSTACK_BENCHMARK_JSON=" +
          json.dumps(answer, ensure_ascii=False, sort_keys=True), flush=True)
    sys.exit(0 if answer["status"] ==
             "engineering_benchmark_passed_rights_blocked" else 2)
