"""Fetch Google's Apache-2.0 Pose Landmarker Lite bundle during Docker build.

Versioned HTTPS URL, byte cap and transactional write: no downloads or network
calls while editing user videos. Requires neither an API key nor an account.
"""
from __future__ import annotations

import os
import pathlib
import tempfile
import urllib.request
import zipfile

MODEL_URL = ("https://storage.googleapis.com/mediapipe-models/"
             "pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task")
MODEL_DIR = pathlib.Path(__file__).resolve().parent.parent / "models"
MODEL_FILE = MODEL_DIR / "pose_landmarker_lite.task"
MIN_BYTES = 500_000
MAX_BYTES = 15_000_000


def download(destination: pathlib.Path = MODEL_FILE) -> pathlib.Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and MIN_BYTES <= destination.stat().st_size <= MAX_BYTES:
        return destination
    request = urllib.request.Request(MODEL_URL, headers={"User-Agent": "Monteur-Studio-model-build/1.0"})
    with tempfile.NamedTemporaryFile(dir=destination.parent, suffix=".task", delete=False) as temporary:
        candidate = pathlib.Path(temporary.name)
        try:
            with urllib.request.urlopen(request, timeout=45) as response:
                size = 0
                while chunk := response.read(65536):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("Pose model exceeds bounded download size")
                    temporary.write(chunk)
            if size < MIN_BYTES or not zipfile.is_zipfile(candidate):
                raise ValueError("Invalid MediaPipe Pose model bundle")
            os.replace(candidate, destination)
        finally:
            candidate.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    print("Offline pose model ready:", download())
