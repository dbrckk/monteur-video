"""HTTP end-to-end V1: mobile-style chunk uploads -> async FFmpeg -> grade -> MP4.

All processing is real, but exports are downscaled for CI speed. No Whisper download
is needed; the production Docker image enables it independently.
"""
import importlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg absent")
class TrueEndToEndTests(unittest.TestCase):
    def create_clip(self, path: Path, color: str, audio: bool):
        args = ["ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-f", "lavfi", "-i", f"color=c={color}:s=160x90:r=15"]
        if audio:
            args += ["-f", "lavfi", "-i", "sine=frequency=540:sample_rate=48000"]
        args += ["-t", "3", "-c:v", "mpeg4", "-q:v", "4"]
        if audio:
            args += ["-c:a", "aac"]
        subprocess.run(args + ["-y", str(path)], check=True, capture_output=True)

    def upload_via_http(self, client: TestClient, source: Path, chunk_size: int = 11_000):
        content = source.read_bytes()
        create = client.post("/api/uploads", json={"filename": source.name,
                                                   "size": len(content)})
        self.assertEqual(create.status_code, 201, create.text)
        ident = create.json()["id"]
        for offset in range(0, len(content), chunk_size):
            response = client.patch(
                f"/api/uploads/{ident}", content=content[offset:offset + chunk_size],
                headers={"Upload-Offset": str(offset)})
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(client.get(f"/api/uploads/{ident}").json()["offset"],
                         len(content))
        return ident

    def until(self, callback, timeout=45):
        limit = time.monotonic() + timeout
        last = None
        while time.monotonic() < limit:
            last = callback()
            if last["status"] in ("done", "failed"):
                return last
            time.sleep(0.1)
        self.fail(f"Async FFmpeg operation timed out: {last}")

    def test_from_two_phone_files_to_real_filtered_download(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": ""}):
            import montage
            import server
            server = importlib.reload(server)
            home = Path(tmp)
            sources = [home / "phone-one.mp4", home / "phone-two.mp4"]
            self.create_clip(sources[0], "red", True)
            self.create_clip(sources[1], "blue", False)
            original_editor = montage.edit_many

            def faster_renders(*args, **kwargs):
                kwargs["size"] = 360
                kwargs["transcribe"] = False
                return original_editor(*args, **kwargs)

            with TestClient(server.app) as client, patch.object(
                    server, "edit_many", side_effect=faster_renders):
                uploads = [self.upload_via_http(client, source) for source in sources]
                started = client.post("/api/montages", json={
                    "upload_ids": uploads, "theme": "fitness",
                    "aspect": "vertical", "seconds": 10})
                self.assertEqual(started.status_code, 201, started.text)
                ident = started.json()["id"]
                job = self.until(lambda: client.get(f"/api/jobs/{ident}").json())
                self.assertEqual(job["status"], "done", job.get("error"))
                self.assertEqual(job["metadata"]["source_count"], 2)
                self.assertEqual(len(job["metadata"]["sources"]), 2)
                master = home / ident / "final.mp4"
                self.assertTrue(master.is_file())
                dimensions = subprocess.check_output([
                    "ffprobe", "-v", "error", "-select_streams", "v:0",
                    "-show_entries", "stream=width,height", "-of", "csv=p=0",
                    str(master)], text=True).strip()
                self.assertEqual(dimensions, "360,640")
                signed = client.get(f"/api/jobs/{ident}/download-link")
                self.assertEqual(signed.status_code, 200, signed.text)
                self.assertGreater(len(client.get(signed.json()["url"]).content), 1500)

                created = client.post(f"/api/jobs/{ident}/filters",
                                      json={"preset": "impact"})
                self.assertEqual(created.status_code, 202, created.text)
                filtered = self.until(lambda: next(
                    x for x in client.get(f"/api/jobs/{ident}/filters").json()["filters"]
                    if x["id"] == "impact"))
                self.assertEqual(filtered["status"], "done", filtered.get("error"))
                link = client.get(f"/api/jobs/{ident}/download-link",
                                  params={"preset": "impact"})
                self.assertEqual(link.status_code, 200, link.text)
                video = client.get(link.json()["url"])
                self.assertEqual(video.status_code, 200, video.text[:200] if video.status_code != 200 else "")
                self.assertGreater(len(video.content), 1500)
                self.assertNotEqual(video.content, master.read_bytes())
                self.assertEqual(client.delete(f"/api/jobs/{ident}").status_code, 200)
                self.assertFalse((home / ident).exists())
                self.assertTrue(all(not (home / x).exists() for x in uploads))


if __name__ == "__main__":
    unittest.main()
