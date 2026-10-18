"""Integration contracts for multiple uploads, idempotent job creation and filters."""
import importlib
import json
import os
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class MultiVideoApiTests(unittest.TestCase):
    def build(self, client: TestClient, filename: str, content: bytes) -> str:
        start = client.post("/api/uploads", json={
            "filename": filename, "size": len(content)})
        self.assertEqual(start.status_code, 201, start.text)
        ident = start.json()["id"]
        response = client.patch(f"/api/uploads/{ident}", content=content,
                                headers={"Upload-Offset": "0"})
        self.assertEqual(response.status_code, 200, response.text)
        return ident

    def test_complete_batch_consume_retry_and_delete_sources(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": ""}):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                a = self.build(client, "one.mp4", b"aaa")
                b = self.build(client, "two.mov", b"bbbb")
                self.assertEqual(client.post("/api/montages", json={
                    "upload_ids": [a, a]}).status_code, 422)
                self.assertEqual(client.post("/api/montages", json={
                    "upload_ids": [a, str(uuid.uuid4())]}).status_code, 409)
                self.assertEqual(client.post("/api/montages", json={
                    "upload_ids": [a, b], "theme": "unknown"}).status_code, 422)
                project_id = str(uuid.uuid4())
                payload = {"project_id": project_id, "upload_ids": [a, b],
                           "theme": "fitness", "aspect": "vertical", "seconds": 45}
                with patch.object(server.POOL, "submit") as submit:
                    response = client.post("/api/montages", json=payload)
                    self.assertEqual(response.status_code, 201, response.text)
                    self.assertEqual(response.json()["id"], project_id)
                    self.assertEqual(response.json()["source_count"], 2)
                    self.assertEqual(submit.call_count, 1)
                    self.assertEqual(submit.call_args.args, (server.run_job, project_id))
                    replay = client.post("/api/montages", json=payload)
                    self.assertEqual(replay.status_code, 201)
                    self.assertTrue(replay.json()["reused"])
                    self.assertEqual(submit.call_count, 1)
                self.assertEqual(client.get(f"/api/uploads/{a}").json()["status"], "consumed")
                self.assertEqual(client.get(f"/api/uploads/{b}").json()["status"], "consumed")
                self.assertEqual(client.post("/api/montages", json={
                    "upload_ids": [a, b]}).status_code, 409)
                self.assertEqual(client.post(f"/api/uploads/{a}/complete",
                    json={"theme": "fitness"}).status_code, 409)
                self.assertEqual(client.delete(f"/api/jobs/{project_id}").status_code, 409)

                server.update_job(project_id, status="done", progress=1, stage="done")
                Path(tmp, project_id, "final.mp4").write_bytes(b"finished")
                with server.database() as con:
                    con.execute("INSERT INTO filter_exports(job_id,preset,status) "
                                "VALUES(?,?,'queued')", (project_id, "impact"))
                self.assertEqual(client.delete(f"/api/jobs/{project_id}").status_code, 409)
                server.update_filter(project_id, "impact", status="processing")
                self.assertEqual(client.delete(f"/api/jobs/{project_id}").status_code, 409)
                server.update_filter(project_id, "impact", status="done")
                (Path(tmp) / project_id / "filters").mkdir()
                (Path(tmp) / project_id / "filters" / "impact.mp4").write_bytes(b"filtered")
                deleted = client.delete(f"/api/jobs/{project_id}")
                self.assertEqual(deleted.status_code, 200)
                self.assertEqual(deleted.json()["sources_deleted"], 2)
                self.assertFalse((Path(tmp) / project_id).exists())
                self.assertFalse((Path(tmp) / a).exists())
                self.assertFalse((Path(tmp) / b).exists())
                self.assertEqual(client.get(f"/api/jobs/{project_id}").status_code, 404)

    def test_filter_selection_status_signed_url_and_ticket_isolation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": "api-key-for-testing"}):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                auth = {"Authorization": "Bearer api-key-for-testing"}
                created = client.post("/api/uploads", headers=auth,
                                      json={"filename": "reels.mp4", "size": 3})
                self.assertEqual(created.status_code, 201)
                ident = created.json()["id"]
                client.patch(f"/api/uploads/{ident}", headers={
                    **auth, "Upload-Offset": "0"}, content=b"abc")
                with patch.object(server.POOL, "submit"):
                    self.assertEqual(client.post(f"/api/uploads/{ident}/complete",
                        headers=auth, json={"theme": "fitness"}).status_code, 200)
                filters_url = f"/api/jobs/{ident}/filters"
                self.assertEqual(client.get(filters_url, headers=auth).status_code, 409)
                self.assertEqual(client.post(filters_url, headers=auth,
                                 json={"preset": "impact"}).status_code, 409)
                server.update_job(ident, status="done", progress=1, stage="done")
                (Path(tmp) / ident / "final.mp4").write_bytes(b"original_mp4")
                self.assertEqual(client.get(filters_url).status_code, 401)
                options = client.get(filters_url, headers=auth).json()
                self.assertEqual(options["filters"][0]["id"], "original")
                self.assertIn("impact", [x["id"] for x in options["filters"]
                                         if x["recommended"]])
                self.assertEqual(client.post(filters_url, headers=auth,
                                 json={"preset": "danger"}).status_code, 422)
                with patch.object(server.POOL, "submit") as submit:
                    result = client.post(filters_url, headers=auth,
                                         json={"preset": "impact"})
                    self.assertEqual(result.status_code, 202)
                    self.assertEqual(result.json()["status"], "queued")
                    self.assertEqual(submit.call_count, 1)
                    self.assertEqual(client.post(filters_url, headers=auth,
                        json={"preset": "impact"}).json()["status"], "queued")
                    self.assertEqual(submit.call_count, 1)
                self.assertEqual(client.get(f"/api/jobs/{ident}/download-link",
                    params={"preset": "impact"}, headers=auth).status_code, 404)
                (Path(tmp) / ident / "filters").mkdir()
                (Path(tmp) / ident / "filters" / "impact.mp4").write_bytes(b"rendered_filter")
                server.update_filter(ident, "impact", status="done", progress=1)
                link = client.get(f"/api/jobs/{ident}/download-link",
                    params={"preset": "impact"}, headers=auth)
                self.assertEqual(link.status_code, 200, link.text)
                url = link.json()["url"]
                self.assertEqual(client.get(url).status_code, 200)
                self.assertEqual(client.get(url).content, b"rendered_filter")
                tampered = url.replace("preset=impact", "preset=acier")
                self.assertEqual(client.get(tampered).status_code, 401)
                self.assertEqual(client.get(f"/api/jobs/{ident}/download",
                    params={"preset": "../abc"}).status_code, 404)
                original = client.get(f"/api/jobs/{ident}/download-link", headers=auth)
                self.assertEqual(client.get(original.json()["url"]).content, b"original_mp4")
                self.assertEqual(client.get(original.json()["url"] + "&inline=1").headers[
                    "content-disposition"].split(";")[0], "inline")
                # Regenerate a filter if the indexed export has vanished.
                (Path(tmp) / ident / "filters" / "impact.mp4").unlink()
                with patch.object(server.POOL, "submit") as submit:
                    retry = client.post(filters_url, headers=auth, json={"preset": "impact"})
                    self.assertEqual(retry.status_code, 202)
                    self.assertEqual(retry.json()["status"], "queued")
                    self.assertEqual(submit.call_count, 1)

    def test_local_server_serves_mobile_pwa_assets(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": ""}):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                for path in ("/", "/manifest.webmanifest", "/icon.svg", "/sw.js"):
                    response = client.get(path)
                    self.assertEqual(response.status_code, 200, path)
                self.assertEqual(client.get("/manifest.webmanifest").json()["display"],
                                 "standalone")

    def test_montage_partial_upload_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": ""}):
            import server
            server = importlib.reload(server)
            with TestClient(server.app) as client:
                first = client.post("/api/uploads", json={
                    "filename": "unfinished.mp4", "size": 10}).json()["id"]
                second = self.build(client, "ready.mp4", b"okay")
                result = client.post("/api/montages", json={
                    "upload_ids": [first, second]})
                self.assertEqual(result.status_code, 409)
                self.assertEqual(client.get(f"/api/uploads/{second}").json()["status"],
                                 "uploading")


if __name__ == "__main__":
    unittest.main()
