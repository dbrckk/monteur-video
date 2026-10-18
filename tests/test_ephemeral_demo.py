"""Free public demo must allow ten source uploads and bound real render slots."""
import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class PublicDemoTests(unittest.TestCase):
    def test_ten_rushes_allowed_and_render_queue_limited(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp,
            "APP_API_TOKEN": "",
            "MONTEUR_PUBLIC_DEMO": "1",
            "MONTEUR_PUBLIC_MAX_ACTIVE": "3",
            "MONTEUR_PUBLIC_MAX_UPLOADS": "12",
        }):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client, patch.object(server.POOL, "submit"):
                ids = []
                for n in range(10):
                    resp = client.post("/api/uploads", json={
                        "filename": f"clip-{n}.mp4", "size": 1},
                        headers={"Origin": "https://dbrckk.github.io"})
                    self.assertEqual(resp.status_code, 201, resp.text)
                    ident = resp.json()["id"]
                    uploaded = client.patch(f"/api/uploads/{ident}",
                        content=b"x", headers={"Upload-Offset": "0",
                            "Origin": "https://dbrckk.github.io"})
                    self.assertEqual(uploaded.status_code, 200, uploaded.text)
                    ids.append(ident)
                self.assertEqual(client.post("/api/montages", json={
                    "upload_ids": ids,
                }, headers={"Origin": "https://evil.example"}).status_code, 403)
                for index in range(3):
                    resp = client.post("/api/montages", json={
                        "upload_ids": [ids[index]],
                    }, headers={"Origin": "https://dbrckk.github.io"})
                    self.assertEqual(resp.status_code, 201, resp.text)
                blocked = client.post("/api/montages", json={
                    "upload_ids": [ids[3]],
                }, headers={"Origin": "https://dbrckk.github.io"})
                self.assertEqual(blocked.status_code, 429)
                self.assertIn("occupé", blocked.json()["detail"])
                for ident in ids[4:]:
                    self.assertEqual(client.get(f"/api/uploads/{ident}").status_code, 200)

    def test_lost_job_is_an_explicit_404(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": "",
            "MONTEUR_PUBLIC_DEMO": "1",
        }):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                import uuid
                ident = str(uuid.uuid4())
                response = client.get(f"/api/jobs/{ident}")
                self.assertEqual(response.status_code, 404)
                self.assertEqual(response.json()["detail"], "Projet introuvable")


if __name__ == "__main__":
    unittest.main()
