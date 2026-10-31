# UGC Zero Credit — offline TikTok/Reels video pipeline (V6)

An **isolated** video assembly and quality-assurance component embedded in `monteur-video`, intended to be moved to its own repository when available. It does **not** modify the existing video API, Dockerfile, static site, or deployments. No external generation API, token, or subscription is used by these scripts.

## What is implemented

- Native speech + video montage: audio from the talking clips remains attached to the original shot; soundtrack is ducked.
- Strict input validation: licensing evidence, no URLs/network inputs, valid timing and captions, no output overwrites.
- Editorial audit and non-destructive automatic edit suggestions (`editorial_quality.py`, `auto_edit.py`).
- Local FFmpeg 1080×1920 H.264/AAC rendering and optional lightweight preview.
- Voice waveform sync drift detection, face-presence and mouth-motion heuristic, face-aware 9:16 crop with OpenCV when installed.
- Audio LUFS/true-peak checks, frozen/black frame heuristics, mobile offline review page and publication gate.

**Not implemented:** creation of photorealistic AI influencers, speech generation, phoneme-to-lip matching, automated proof of product authenticity, commercial rights verification, or automatic publishing. Native waveform sync ≠ correct lip motion; a human review is required.

## Requirements

- Python 3.10+, FFmpeg/FFprobe with H.264 encoding and audio filters, local disk.
- Optional for face QA, image ranking and V6 integration checks: `python -m pip install -r requirements_vision_optional.txt` (NumPy + OpenCV, can consume download bandwidth but no inference credits).
- Optional local faster-whisper requires a **previously downloaded and licensed** model; the code refuses automatic model downloads.

## Functional smoke test (works on Linux; no cloud calls)

```bash
cd tools/ugc_zero_credit
python3 make_synthetic_demo.py
python3 ugc.py doctor
python3 ugc.py check examples/synthetic_demo.json
python3 ugc.py render examples/synthetic_demo.json --output demo_1080x1920.mp4
python3 ugc.py audit demo_1080x1920.mp4 --full-decode
python3 functional_checks_v3.py
python3 functional_checks_v4.py
python3 functional_checks_v5.py
python3 functional_checks_v6.py
```

All demonstration assets are locally synthesized by FFmpeg (no real brand or influencer). It is **not** a publishable advertisement. The demo's captions are illustrative and are not the narration of the synthesized tone.

## Actual user-provided production

1. Copy `project_template.json` to `my_project.json` and edit media paths, claims and verified rights.
2. Provide an **authorized** original AI presenter clip with its **native** voice and synchronized face; do not replace a speaking person's soundtrack after rendering.
3. Add your owned/authorized packshot and product clips and genuine word-level timings if subtitles are desired.
4. Run `python3 ugc.py check my_project.json --strict-editorial` then `python3 ugc.py render my_project.json --require-speaking-face --output final.mp4`.
5. Review `final.report.json`, `final.qa.json`, and the output manually. Use `release_gate.py` for final human checks; no auto-publish.

See [PROCESS_V6.md](PROCESS_V6.md) for editorial limits and [RELEASE_NOTES_V6.md](RELEASE_NOTES_V6.md) for V6 checks. Manual full-quality renders consume local CPU/GPU time and disk, not external AI credits. CI is intentionally **not added** to avoid triggering GitHub Actions quotas.
