# Gym equipment detection: isolated D-FINE-S ONNX benchmark

**Status:** Research-only, **NOT deployed** into `monteur-video-stable`. This experiment does not modify `Dockerfile`, `pose_reframe.py`, `editor.py` or the web UI.

## Why D-FINE Small?

The upstream D-FINE Objects365 models include **Person (1), Dumbbell (323), Treadmill (332), Barbell (349)**. The ONNX Community provides an INT8 ONNX export of the small ~10M parameter variant, reducing weight size relative to D-FINE Large. The upstream training repository: https://github.com/Peterande/D-FINE, candidate: https://huggingface.co/onnx-community/dfine_s_obj365-ONNX.

**Rights warning:** The base repository advertises Apache-2.0 for model code/weights, **but the upstream D-FINE README expressly warns that Objects365-pretrained checkpoints may be subject to Objects365 dataset terms**. This benchmark DOES NOT assert commercial rights; explicit rights validation is a requirement before using a weight in a monetized product.

## What the benchmark really does

An initial **INT8** benchmark was executed on 22 October 2026. Model SHA-256 `3355fe77be41bca48937cd5bb100de51e1bfd894e67275f6d398cfda35624838` (11.33 MB) failed at ONNX Runtime model initialization because the CPU provider lacks a `ConvInteger(10)` implementation. It was recorded as **not qualified**, without changing production. The follow-up **FP32** ONNX model (immutable HF revision `a61e4cdfe4f9d3188a305d91e37dbf38688ffbb8`, SHA-256 `372feaa33ac6ba67d7df8589628f6abc395b3c6981c4edc70dfcfe2949751120`, 42.1 MB) passed an actual synthetic CPU inference: **2.8 seconds at 0.1 CPU, 242.9 MiB peak cgroup memory** for D-FINE alone. Inputs were `pixel_values`; outputs were `logits [1,300,366]` and `pred_boxes [1,300,4]`. This is a **detector output shape**, not validation of real sports footage. The expanded follow-up **PASSED**: actual D-FINE-S FP32 inference completed in **2.3 seconds at 0.1 CPU**, then MediaPipe Pose and MobileNet both loaded and executed **simultaneously in the same 512-MiB limited container**. The maximum recorded cgroup memory was **286.8 MiB**, leaving **225.2 MiB** headroom against the 512-MiB limit (below the explicit 420-MiB co-residency gate). The reported source is immutable revision `a61e4cdfe4f9d3188a305d91e37dbf38688ffbb8`. Detailed machine-readable evidence is committed in [gym-detector-benchmark-results.json](gym-detector-benchmark-results.json), with original logs in [GitHub Actions run 39789036538](https://github.com/dbrckk/monteur-video/actions/runs/39789036538). **This still does not certify** memory of the full FFmpeg + Whisper + API stack, accuracy on real gym video, or the commercial Objects365-derived checkpoint terms; production remains unchanged.

The GitHub Actions workflow `gym-detector-benchmark.yml` automatically runs on a pull request changing this benchmark or via manual `workflow_dispatch`. It:

1. Builds a separate Python/ONNX Runtime container. The default production engine gains **no** dependency or model.
2. Runs inside Docker hard-limited to **512 MiB** container RAM, **0.1 CPU** and **128 processes/threads**.
3. Resolves the model repository's immutable source SHA, verifies Objects365 class names and records the SHA-256 of the downloaded INT8 ONNX file.
4. Inspects model inputs, runs actual CPU inference on a bounded synthetic 640×640 RGB input, validates finite scores and bounding-box-like outputs, then simultaneously loads/executes MediaPipe Pose and ImageNet MobileNet. Records inference wall time and RSS/cgroup memory peak, with a 420-MiB co-residency gate.
5. Exports `dfine-benchmark.json`, raw logs and a short markdown report as an Actions artifact. A timeout, OOM kill, model parsing error, tensor mismatch, or out-of-budget process produces **not qualified**, without silently shipping a detector.

Synthetic frames prove **runtime compatibility only**. They do not measure false detections, gym equipment visibility or visual accuracy. Real footage would still be required.

## Official licensing decision — 22 October 2026

The **Objects365 official download conditions** explicitly state that the dataset is "available for the academic purpose only". Its annotations/website have a CC BY 4.0 provision, but the Images section separately disclaims ownership of image copyrights. The D-FINE official README warns that `*_obj365`/`*_obj2coco` pretrained checkpoints **must not be assumed commercially cleared**. A published maintainer clarification request ([D-FINE issue #357](https://github.com/Peterande/D-FINE/issues/357)) also describes the checkpoint rights as unresolved.

Primary sources:
- [Objects365 Consortium official terms](https://www.objects365.org/download.html)
- [Upstream D-FINE licensing notice](https://github.com/Peterande/D-FINE)
- [D-FINE checkpoint rights clarification issue](https://github.com/Peterande/D-FINE/issues/357)

**Decision for Monteur Studio:** Objects365-derived D-FINE checkpoints remain **research-only and not shipped in any commercial/public runtime** without explicit independent commercial clearance. The Apache-2.0 notice for D-FINE source code does not, by itself, override upstream dataset or image-use constraints. This is a conservative release decision, not a legal determination that *every* derivative checkpoint is prohibited.

## Full production-stack engineering benchmark

The separate workflow [`gym-detector-fullstack.yml`](../.github/workflows/gym-detector-fullstack.yml) builds the **actual production Dockerfile with faster-whisper installed**, then builds a disposable extra layer containing ONNX Runtime and this D-FINE model. It operates inside a strict **512 MiB / 0.1 CPU** Docker cgroup with D-FINE, MediaPipe, MobileNet, Whisper tiny, the actual uvicorn/FastAPI server health endpoint, and a real FFmpeg portrait MP4 render. All tasks share the same memory budget and models stay resident during the render. The runtime records memory after each stage; a peak greater than **420 MiB** fails the engineering reserve gate, and an OOM/timeout is reported explicitly as *not qualified*.

This simulates the paid features conservatively on tiny/synthetic inputs, **not a full real-world batch of rushes**; production rights and verified gym-clip accuracy remain required even after an engineering pass. An engineering failure never automatically causes deployment changes.

## Full-stack benchmark result (22 October 2026): NOT QUALIFIED

In the first isolated full-stack run, the exact Whisper-enabled production image plus the experimental D-FINE weights reached the **512 MiB Docker cgroup memory ceiling** at the `faster-whisper tiny loaded` stage. The memory trace recorded **304.9 MiB peak after D-FINE + MediaPipe + MobileNet**, and **512.0 MiB peak after initializing Whisper Tiny**, before completing transcription, the actual API health test or FFmpeg export. The attempted transcription then failed with `TypeError: open() got an unexpected keyword argument 'metadata_errors'`; that software error is separate from the memory ceiling, and a complete video rendering benchmark was **not** achieved. Source evidence: [GitHub Actions full-stack run 39795106007](https://github.com/dbrckk/monteur-video/actions/runs/39795106007) and [persisted results](gym-detector-benchmark-results.json).

**Decision:** D-FINE-S Objects365 must not be enabled on Render Free, for **two independent reasons**: (1) official Objects365 academic-only dataset conditions, with no demonstrated commercial clearance for derived pretrained checkpoint weights; and (2) measured memory saturation once Whisper joined the video inference stack. The earlier 286.8-MiB three-model result was a useful partial benchmark but **not** a production viability proof. We will not represent this candidate as deployable, even if an isolated Actions job itself completes successfully.

**Next commercially practical approach:** retain the currently deployed MediaPipe + MobileNet + conservative geometric equipment framing; evaluate independent fully rights-cleared smaller detectors (or fine-tune on specifically commercially licensed original/synthetic gym clips) on a separate machine and use them only if full pipeline memory/accuracy gates succeed. Apache-2.0 on a model *card* alone does not establish the provenance of training data or inherited base weights.

## Controlled A/B research comparison and model provenance

The full-stack workflow now runs **two independent containers under identical hard limits** (512 MiB, 0.1 CPU): the original production-capable stack without D-FINE as a control arm, and the same stack with the D-FINE Small Objects365 research checkpoint. The experiment downloads no user footage. It reports memory peaks and errors separately, and **never infers an exact model-memory delta from a 512 MiB saturated reading**. A failure of both arms would indicate a general full-stack overload, not evidence uniquely attributable to D-FINE. A successful A/B benchmark still cannot clear Objects365 commercial training-data rights.

A separate [model rights register](model-rights-register.json) records the pretrained weights already bundled by the optional/public Docker builds. Importantly, **ImageNet's official access terms restrict access to the dataset to noncommercial research/education**. That does not by itself settle the licensing of separately distributed ImageNet-derived MobileNet weights, so the register flags their provenance for **manual commercial review**, rather than representing all Apache-2 weight cards as complete clearance. The upstream [Open Images V7 license statement](https://storage.googleapis.com/openimages/web/factsfigures_v7.html) separately states that box annotations are CC BY 4.0 and listed images CC BY 2.0, **but does not warrant individual image license validity**. Future gym detection training must audit each original source, attribution, permitted use and inherited pretrained weights independently.

## Hard release criteria

A model may only be considered for the public Render Free backend after the following are independently verified:

- Commercial training-data and model-weight rights are cleared.
- The **combined** live stack (FFmpeg + MediaPipe + MobileNet + faster-whisper + detector, one server worker) stays under 512 MiB with a meaningful reserve, rather than merely passing an isolated process probe.
- Detecting one frame at 0.1 CPU has acceptable user-visible latency for multiple uploads.
- At least 20 authorized videos with labeled equipment extents show fewer clipped subjects/weights, no unstable camera movement, and acceptable false-positive frequency compared with the current safe-reframe baseline.
- The download is pinned to a verified immutable revision and SHA-256, the public engine degrades safely when ML inference is unavailable, and the dependency can be entirely disabled.

**Until these conditions hold: current production cropping and sound/video generation stay unchanged.**
