"""V1: restart recovery, automatic retention, and retry without reuploading."""
import importlib
import os
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient


class RecoveryTests(unittest.TestCase):
    def setup_server(self, tmp):
        import server
        with patch.dict(os.environ, {
            "EDITOR_DATA_DIR": tmp, "APP_API_TOKEN": "",
            "UPLOAD_TTL_HOURS": "72", "RESULT_TTL_DAYS": "14"}):
            server = importlib.reload(server)
        return server

    def test_restart_requeues_processing_job_and_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self.setup_server(tmp)
            server.initialize()
            ident = str(uuid.uuid4())
            folder = Path(tmp) / ident
            folder.mkdir()
            (folder / "source").write_bytes(b"saved-mobile-upload")
            now = datetime.now(timezone.utc).isoformat()
            with server.database() as con:
                con.execute(
                    "INSERT INTO jobs(id,filename,status,expected_size,stage,options,"
                    "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (ident, "gym.mp4", "processing", 19, "render",
                     '{"theme":"fitness","aspect":"vertical","seconds":30}', now, now))
                con.execute("INSERT INTO filter_exports(job_id,preset,status) "
                            "VALUES(?,?,'processing')", (ident, "impact"))
            with patch.object(server.POOL, "submit") as submit:
                with TestClient(server.app) as client:
                    self.assertEqual(client.get(f"/api/jobs/{ident}").json()["status"],
                                     "queued")
                    with server.database() as con:
                        self.assertEqual(con.execute(
                            "SELECT status FROM filter_exports WHERE job_id=? AND preset='impact'",
                            (ident,)).fetchone()["status"], "queued")
                    self.assertEqual(submit.call_count, 2)
            self.assertTrue((folder / "source").exists())

    def test_failed_render_can_be_retried_without_upload(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self.setup_server(tmp)
            with TestClient(server.app) as client:
                start = client.post("/api/uploads", json={
                    "filename": "gym.mp4", "size": 4})
                ident = start.json()["id"]
                client.patch(f"/api/uploads/{ident}", content=b"data",
                             headers={"Upload-Offset": "0"})
                server.update_job(ident, status="failed", stage="failed",
                                  error="Previous FFmpeg crash",
                                  options='{"theme":"fitness","aspect":"vertical","seconds":30}')
                with patch.object(server.POOL, "submit") as submit:
                    response = client.post(f"/api/jobs/{ident}/retry")
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(client.get(f"/api/jobs/{ident}").json()["status"],
                                     "queued")
                    submit.assert_called_once()
                    self.assertEqual(client.post(
                        f"/api/jobs/{ident}/retry").status_code, 409)
                server.update_job(ident, status="failed")
                (Path(tmp) / ident / "source").unlink()
                with patch.object(server.POOL, "submit") as submit:
                    self.assertEqual(client.post(
                        f"/api/jobs/{ident}/retry").status_code, 409)
                    submit.assert_not_called()

    def test_gc_removes_orphaned_uploads_without_touching_active_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self.setup_server(tmp)
            with TestClient(server.app) as client:
                old = client.post("/api/uploads", json={
                    "filename": "stale.mp4", "size": 10}).json()["id"]
                fresh = client.post("/api/uploads", json={
                    "filename": "fresh.mp4", "size": 10}).json()["id"]
                old_time = (datetime.now(timezone.utc) -
                            timedelta(days=5)).isoformat()
                with server.database() as con:
                    con.execute("UPDATE jobs SET updated_at=? WHERE id=?",
                                (old_time, old))
                self.assertEqual(server.cleanup_expired(), 1)
                self.assertFalse((Path(tmp) / old).exists())
                self.assertTrue((Path(tmp) / fresh).exists())
                self.assertEqual(client.get(f"/api/uploads/{old}").status_code, 404)

    def test_gc_removes_old_finished_montage_and_consumed_sources_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self.setup_server(tmp)
            with TestClient(server.app) as client:
                files = []
                for name in ("one.mp4", "two.mp4"):
                    upload = client.post("/api/uploads", json={
                        "filename": name, "size": 3}).json()["id"]
                    client.patch(f"/api/uploads/{upload}", content=b"abc",
                                 headers={"Upload-Offset": "0"})
                    files.append(upload)
                with patch.object(server.POOL, "submit"):
                    result = client.post("/api/montages", json={
                        "upload_ids": files, "seconds": 30})
                    self.assertEqual(result.status_code, 201, result.text)
                ident = result.json()["id"]
                server.update_job(ident, status="done", stage="done")
                with server.database() as con:
                    con.execute("INSERT INTO filter_exports(job_id,preset,status) "
                                "VALUES(?,?,'processing')", (ident, "impact"))
                old = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
                with server.database() as con:
                    con.execute("UPDATE jobs SET updated_at=? WHERE id=?", (old, ident))
                self.assertEqual(server.cleanup_expired(), 0)
                self.assertTrue((Path(tmp) / ident).exists())
                server.update_filter(ident, "impact", status="done")
                self.assertEqual(server.cleanup_expired(), 3)
                self.assertFalse((Path(tmp) / ident).exists())
                self.assertTrue(all(not (Path(tmp) / x).exists() for x in files))

    def test_public_origin_without_secret_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            server = self.setup_server(tmp)
            with TestClient(server.app) as client:
                response = client.post("/api/uploads", json={
                    "filename": "remote.mp4", "size": 123},
                    headers={"Origin": "https://dbrckk.github.io"})
                self.assertEqual(response.status_code, 403)
                self.assertEqual(client.post("/api/uploads", json={
                    "filename": "local.mp4", "size": 123}).status_code, 201)


if __name__ == "__main__":
    unittest.main()
