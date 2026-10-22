# Gym equipment detection: isolated D-FINE-S ONNX benchmark

**Status:** Research-only, **NOT deployed** into `monteur-video-stable`. This experiment does not modify `Dockerfile`, `pose_reframe.py`, `editor.py` or the web UI.

## Why D-FINE Small?

The upstream D-FINE Objects365 models include **Person (1), Dumbbell (323), Treadmill (332), Barbell (349)**. The ONNX Community provides an INT8 ONNX export of the small ~10M parameter variant, reducing weight size relative to D-FINE Large. The upstream training repository: https://github.com/Peterande/D-FINE, candidate: https://huggingface.co/onnx-community/dfine_s_obj365-ONNX.

**Rights warning:** The base repository advertises Apache-2.0 for model code/weights, **but the upstream D-FINE README expressly warns that Objects365-pretrained checkpoints may be subject to Objects365 dataset terms**. This benchmark DOES NOT assert commercial rights; explicit rights validation is a requirement before using a weight in a monetized product.

## What the benchmark really does

An initial **INT8** benchmark was executed on 22 October 2026. Model SHA-256 `3355fe77be41bca48937cd5bb100de51e1bfd894e67275f6d398cfda35624838` (11.33 MB) failed at ONNX Runtime model initialization because the CPU provider lacks a `ConvInteger(10)` implementation. It was recorded as **not qualified**, without changing production. The follow-up **FP32** ONNX model (immutable HF revision `a61e4cdfe4f9d3188a305d91e37dbf38688ffbb8`, SHA-256 `372feaa33ac6ba67d7df8589628f6abc395b3c6981c4edc70dfcfe2949751120`, 42.1 MB) passed an actual synthetic CPU inference: **2.8 seconds at 0.1 CPU, 242.9 MiB peak cgroup memory** for D-FINE alone. Inputs were `pixel_values`; outputs were `logits [1,300,366]` and `pred_boxes [1,300,4]`. This is a **detector output shape**, not validation of real sports footage. The expanded follow-up additionally loads the current MediaPipe + MobileNet models in the same limited container; its gate is **at most 420 MiB** to leave at least 92 MiB free. Even passing it would **not** certify the real FFmpeg + Whisper + API stack or the commercial weights rights. CI artifacts retain individual outcomes.

The GitHub Actions workflow `gym-detector-benchmark.yml` automatically runs on a pull request changing this benchmark or via manual `workflow_dispatch`. It:

1. Builds a separate Python/ONNX Runtime container. The default production engine gains **no** dependency or model.
2. Runs inside Docker hard-limited to **512 MiB** container RAM, **0.1 CPU** and **128 processes/threads**.
3. Resolves the model repository's immutable source SHA, verifies Objects365 class names and records the SHA-256 of the downloaded INT8 ONNX file.
4. Inspects model inputs, runs actual CPU inference on a bounded synthetic 640×640 RGB input, validates finite scores and bounding-box-like outputs, then simultaneously loads/executes MediaPipe Pose and ImageNet MobileNet. Records inference wall time and RSS/cgroup memory peak, with a 420-MiB co-residency gate.
5. Exports `dfine-benchmark.json`, raw logs and a short markdown report as an Actions artifact. A timeout, OOM kill, model parsing error, tensor mismatch, or out-of-budget process produces **not qualified**, without silently shipping a detector.

Synthetic frames prove **runtime compatibility only**. They do not measure false detections, gym equipment visibility or visual accuracy. Real footage would still be required.

## Hard release criteria

A model may only be considered for the public Render Free backend after the following are independently verified:

- Commercial training-data and model-weight rights are cleared.
- The **combined** live stack (FFmpeg + MediaPipe + MobileNet + faster-whisper + detector, one server worker) stays under 512 MiB with a meaningful reserve, rather than merely passing an isolated process probe.
- Detecting one frame at 0.1 CPU has acceptable user-visible latency for multiple uploads.
- At least 20 authorized videos with labeled equipment extents show fewer clipped subjects/weights, no unstable camera movement, and acceptable false-positive frequency compared with the current safe-reframe baseline.
- The download is pinned to a verified immutable revision and SHA-256, the public engine degrades safely when ML inference is unavailable, and the dependency can be entirely disabled.

**Until these conditions hold: current production cropping and sound/video generation stay unchanged.**
