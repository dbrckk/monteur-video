"""Security regressions for static GitHub Pages clients and Android downloads."""
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class MobileApiTests(unittest.TestCase):
    def test_bearer_auth_cors_and_temporary_mp4_link(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ,
            {"EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": "strong-example-token-123",
             "MONTEUR_CORS_ORIGINS": "https://studio.example.org"},
        ):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                path = "/api/uploads"
                payload = {"filename": "android.mov", "size": 4}
                self.assertEqual(client.post(path, json=payload).status_code, 401)

                forbidden = client.options(path, headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                })
                self.assertNotIn("access-control-allow-origin", forbidden.headers)

                approved = client.options(path, headers={
                    "Origin": "https://dbrckk.github.io",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                })
                self.assertEqual(approved.status_code, 200)
                self.assertEqual(approved.headers["access-control-allow-origin"],
                                 "https://dbrckk.github.io")

                shipstatic = client.options(path, headers={
                    "Origin": "https://angled-gate-srzt937.shipstatic.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                })
                self.assertEqual(shipstatic.status_code, 200)
                self.assertEqual(shipstatic.headers["access-control-allow-origin"],
                                 "https://angled-gate-srzt937.shipstatic.com")

                v2 = client.options(path, headers={
                    "Origin": "https://snappy-gate-x58qpre.shipstatic.com",
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization,content-type",
                })
                self.assertEqual(v2.status_code, 200)
                self.assertEqual(v2.headers["access-control-allow-origin"],
                                 "https://snappy-gate-x58qpre.shipstatic.com")

                token = {"Authorization": "Bearer strong-example-token-123"}
                response = client.post(path, json=payload, headers=token)
                self.assertEqual(response.status_code, 201)
                ident = response.json()["id"]
                self.assertEqual(client.patch(
                    f"{path}/{ident}", content=b"data",
                    headers={**token, "Upload-Offset": "0"}
                ).status_code, 200)

                # Simulate completed rendering without invoking FFmpeg here.
                server.update_job(ident, status="done", stage="done", progress=1.0)
                Path(tmp, ident, "final.mp4").write_bytes(b"fake-mp4-for-api-test")
                link_api = f"/api/jobs/{ident}/download-link"
                self.assertEqual(client.get(link_api).status_code, 401)
                link = client.get(link_api, headers=token)
                self.assertEqual(link.status_code, 200)
                url = link.json()["url"]
                self.assertIn("ticket=", url)
                self.assertEqual(client.get(url).status_code, 200)
                self.assertEqual(client.get(url).content, b"fake-mp4-for-api-test")
                self.assertIn("attachment", client.get(url).headers["content-disposition"])
                self.assertEqual(client.get(f"/api/jobs/{ident}/download").status_code, 401)
                self.assertEqual(client.get(url.replace("ticket=", "ticket=modified")).status_code, 401)
                self.assertFalse(server.validate_ticket(ident, "not-a-number", "a"))
                self.assertFalse(server.validate_ticket(
                    ident, str(int(server.time()) - 10), "invalid"))
                self.assertEqual(client.get(link_api, headers={
                    "Authorization": "Bearer incorrect"}).status_code, 401)

    def test_local_cookie_keeps_working(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {"EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": "another-example-token"}
        ):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                self.assertEqual(client.post("/api/login", json={
                    "token": "another-example-token"}).status_code, 200)
                self.assertEqual(client.post("/api/uploads", json={
                    "filename": "gym.mp4", "size": 5}).status_code, 201)


if __name__ == "__main__":
    unittest.main()
