"""End-to-end free HD render with a real Reel audio recommendation.

No copyrighted track is scraped, downloaded or included in the exported MP4.
"""
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
class ReelsAudioApiTests(unittest.TestCase):
    def test_instagram_mode_recommends_song_and_exports_silent_video(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": root, "MONTEUR_RENDER_SIZE": "360",
            "MONTEUR_PUBLIC_DEMO": "1", "APP_API_TOKEN": "",
        }):
            import server
            server = importlib.reload(server)
            source = Path(root) / "gym.mp4"
            subprocess.run([
                "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "testsrc2=s=160x90:r=15:d=2.5",
                "-f", "lavfi", "-i", "sine=frequency=320:duration=2.5",
                "-t", "2.5", "-c:v", "mpeg4", "-q:v", "6",
                "-c:a", "aac", str(source)
            ], check=True, capture_output=True)
            selected = {
                "selected": {
                    "title": "FE!N (feat. Playboi Carti)",
                    "artist": "Travis Scott",
                    "url": "https://www.instagram.com/reels/audio/7572714589408356/",
                    "open_url": "https://www.instagram.com/reels/audio/7572714589408356/"
                },
                "alternatives": [], "visual_energy": "high",
                "catalog_url": "https://soundmatcha.com/for/gym/",
                "audio_automatically_embedded": False
            }
            with TestClient(server.app) as client, patch.object(server.POOL, "submit"), patch.object(
                    server, "recommend_reels_audio", return_value=selected) as discovery:
                upload = client.post("/api/uploads", json={
                    "filename": "gym.mp4", "size": source.stat().st_size})
                self.assertEqual(upload.status_code, 201, upload.text)
                upload_id = upload.json()["id"]
                chunk = client.patch(f"/api/uploads/{upload_id}", content=source.read_bytes(),
                                     headers={"Upload-Offset": "0"})
                self.assertEqual(chunk.status_code, 200, chunk.text)
                job = client.post("/api/montages", json={
                    "upload_ids": [upload_id], "theme": "fitness", "aspect": "vertical",
                    "seconds": 10, "sound_mode": "auto",
                    "music_mode": "instagram", "music_preference": "any"
                })
                self.assertEqual(job.status_code, 201, job.text)
                ident = job.json()["id"]
                server.run_job(ident)
                status = client.get(f"/api/jobs/{ident}")
                self.assertEqual(status.status_code, 200, status.text)
                payload = status.json()
                self.assertEqual(payload["status"], "done", payload.get("error"))
                discovery.assert_called_once()
                meta = payload["metadata"]
                self.assertEqual(meta["reels_music"]["selected"]["title"], selected["selected"]["title"])
                self.assertFalse(meta["soundtrack"]["music_embedded"])
                self.assertEqual(meta["soundtrack"]["original_audio_volume"], 0.0)
                final = Path(root) / ident / "final.mp4"
                self.assertTrue(final.is_file())
                audio = subprocess.check_output([
                    "ffprobe", "-v", "error", "-select_streams", "a",
                    "-show_entries", "stream=codec_name", "-of", "csv=p=0", str(final)
                ], text=True).strip()
                self.assertEqual(audio, "")
                self.assertTrue(client.get(f"/api/jobs/{ident}/download-link").is_success)

    def test_unknown_music_mode_rejected(self):
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": root, "APP_API_TOKEN": "",
        }):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                for key, invalid in (
                    ("music_mode", "stream_instagram_without_rights"),
                    ("music_preference", "unverified_language"),
                ):
                    response = client.post("/api/montages", json={
                        "upload_ids": ["00000000-0000-4000-8000-000000000001"],
                        key: invalid})
                    self.assertEqual(response.status_code, 422, response.text)


if __name__ == "__main__":
    unittest.main()
