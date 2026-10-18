"""An API montage must deliver an MP4 with an original soundtrack, not raw mic audio."""
import importlib
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg required")
class MusicJobTests(unittest.TestCase):
    def test_real_single_rush_fitness_job_contains_music(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": root,
            "MONTEUR_RENDER_SIZE": "360",
            "APP_API_TOKEN": "",
            "MONTEUR_PUBLIC_DEMO": "0",
        }):
            import server
            server = importlib.reload(server)
            video = Path(root) / "input.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
                "-y", "-f", "lavfi", "-i", "testsrc2=s=160x90:r=15:d=2.5",
                "-f", "lavfi", "-i", "sine=frequency=220:duration=2.5",
                "-t", "2.5", "-c:v", "mpeg4", "-q:v", "7",
                "-c:a", "aac", str(video),
            ], check=True, capture_output=True)
            with TestClient(server.app) as client, patch.object(server.POOL, "submit"):
                upload = client.post("/api/uploads", json={
                    "filename": "lift.mp4", "size": video.stat().st_size})
                self.assertEqual(upload.status_code, 201, upload.text)
                source_id = upload.json()["id"]
                sent = client.patch(f"/api/uploads/{source_id}", content=video.read_bytes(),
                    headers={"Upload-Offset": "0"})
                self.assertEqual(sent.status_code, 200, sent.text)
                payload = {"upload_ids": [source_id], "seconds": 10,
                           "theme": "fitness", "aspect": "vertical",
                           "sound_mode": "mute"}
                created = client.post("/api/montages", json=payload)
                self.assertEqual(created.status_code, 201, created.text)
                job_id = created.json()["id"]
                server.run_job(job_id)
                finished = client.get(f"/api/jobs/{job_id}")
                self.assertEqual(finished.status_code, 200)
                data = finished.json()
                self.assertEqual(data["status"], "done", data.get("error"))
                self.assertEqual(data["metadata"]["soundtrack"]["origin"],
                                 "original_generated")
                self.assertEqual(data["metadata"]["soundtrack"]["original_audio_volume"], 0)
                self.assertEqual(data["metadata"]["cut_style"] if "cut_style" in data["metadata"]
                                 else data["metadata"]["source_count"], 1)
                mp4 = Path(root) / job_id / "final.mp4"
                self.assertTrue(mp4.is_file())
                self.assertGreater(mp4.stat().st_size, 10000)
                self.assertTrue(client.get(f"/api/jobs/{job_id}/download-link").is_success)

    def test_unknown_audio_mode_rejected(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": root, "APP_API_TOKEN": "",
        }):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                self.assertEqual(client.post("/api/montages", json={
                    "upload_ids": ["00000000-0000-4000-8000-000000000001"],
                    "sound_mode": "free-form"
                }).status_code, 422)


if __name__ == "__main__":
    unittest.main()
