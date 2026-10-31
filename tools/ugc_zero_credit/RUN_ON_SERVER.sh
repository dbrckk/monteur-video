#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
command -v ffmpeg >/dev/null || { echo 'ffmpeg missing'; exit 2; }
command -v ffprobe >/dev/null || { echo 'ffprobe missing'; exit 2; }
python3 make_synthetic_demo.py
python3 ugc.py check examples/synthetic_demo.json
python3 ugc.py render examples/synthetic_demo.json --output demo_1080x1920.mp4
python3 ugc.py audit demo_1080x1920.mp4 --full-decode
