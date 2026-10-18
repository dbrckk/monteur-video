import importlib
import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient


class UploadContractTests(unittest.TestCase):
    def test_resumable_upload_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["EDITOR_DATA_DIR"] = tmp
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                response = client.post("/api/uploads", json={"filename": "../../raw.mp4", "size": 6})
                self.assertEqual(response.status_code, 201)
                ident = response.json()["id"]
                res = client.patch(f"/api/uploads/{ident}",
                                   content=b"abc", headers={"Upload-Offset": "0"})
                self.assertEqual(res.status_code, 200)
                self.assertEqual(res.json()["offset"], 3)
                wrong = client.patch(f"/api/uploads/{ident}",
                                     content=b"123", headers={"Upload-Offset": "0"})
                self.assertEqual(wrong.status_code, 409)
                self.assertEqual(client.get(f"/api/uploads/{ident}").json()["offset"], 3)
                self.assertEqual(client.post(f"/api/uploads/{ident}/complete",
                                 json={"theme": "fitness"}).status_code, 409)
                client.patch(f"/api/uploads/{ident}",
                             content=b"def", headers={"Upload-Offset": "3"})
                with patch.object(server.POOL, "submit") as submit:
                    finished = client.post(f"/api/uploads/{ident}/complete",
                        json={"theme": "fitness", "aspect": "vertical", "seconds": 45})
                    self.assertEqual(finished.status_code, 200)
                    submit.assert_called_once()
                job = client.get(f"/api/jobs/{ident}").json()
                self.assertEqual(job["status"], "queued")
                self.assertEqual(client.delete(f"/api/jobs/{ident}").status_code, 409)

    def test_reject_unsupported_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["EDITOR_DATA_DIR"] = tmp
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                self.assertEqual(client.post("/api/uploads",
                    json={"filename": "payload.exe", "size": 300}).status_code, 415)
