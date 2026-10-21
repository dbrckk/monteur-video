"""Download the verified-license ImageNet MobileNetV2 ONNX model at build time.

The trained source model is ONNX Model Zoo's mobilenetv2-12 (Apache 2.0);
it includes the ImageNet 'dumbbell' class. Images stay on the user's own
video engine and runtime never fetches model weights from the network.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import tempfile
import urllib.request

MODEL_URL = ("https://huggingface.co/onnxmodelzoo/mobilenetv2-12/"
             "resolve/23a2a25/mobilenetv2-12.onnx?download=true")
MODEL = pathlib.Path(__file__).resolve().parent.parent / "models" / "mobilenetv2-12.onnx"
MIN_BYTES, MAX_BYTES = 10_000_000, 17_000_000
# Exact tested ONNX payload from the above source revision; prevents silently
# changing inference labels or model behavior in later Docker deployments.
MODEL_SHA256 = "c0c3f76d93fa3fd6580652a45618618a220fced18babf65774ed169de0432ad5"


def _hash_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(131072):
            digest.update(chunk)
    return digest.hexdigest()


def install(destination: pathlib.Path = MODEL) -> pathlib.Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (destination.is_file() and MIN_BYTES <= destination.stat().st_size <= MAX_BYTES
            and _hash_file(destination) == MODEL_SHA256):
        return destination
    req = urllib.request.Request(
        MODEL_URL, headers={"User-Agent": "MonteurStudio/1.0-offline-model-builder"})
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, suffix=".onnx.tmp", delete=False
    ) as out:
        tmp = pathlib.Path(out.name)
        digest = hashlib.sha256()
        try:
            with urllib.request.urlopen(req, timeout=50) as response:
                size = 0
                while chunk := response.read(131072):
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise ValueError("unexpectedly large image classifier")
                    digest.update(chunk)
                    out.write(chunk)
            out.flush()
            os.fsync(out.fileno())
            if not MIN_BYTES <= size <= MAX_BYTES:
                raise ValueError("invalid classifier size")
            if digest.hexdigest() != MODEL_SHA256:
                raise ValueError("classifier SHA-256 mismatch: unverified model weights")
            os.chmod(tmp, 0o644)
            os.replace(tmp, destination)
            print("Dumbbell ONNX sha256:", digest.hexdigest(), "bytes:", size)
        finally:
            tmp.unlink(missing_ok=True)
    return destination


if __name__ == "__main__":
    print("CPU ImageNet classifier ready at", install())
