"""Resumable local web API for long-form video ingestion and background editing."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import shutil
import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from time import time
from urllib.parse import quote
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from editor import THEMES, edit_video

ROOT = Path(os.environ.get("EDITOR_DATA_DIR", "./data")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "jobs.sqlite3"
WEB = Path(__file__).resolve().parent / "web" / "index.html"
MAX_SIZE = int(float(os.environ.get("MAX_UPLOAD_GB", "20")) * 1024 ** 3)
CHUNK_LIMIT = 16 * 1024 * 1024
API_TOKEN = os.environ.get("APP_API_TOKEN", "")
COOKIE_VALUE = hmac.new(API_TOKEN.encode(), b"monteur-session-v1", hashlib.sha256).hexdigest()
DOWNLOAD_SECRET = hmac.new(API_TOKEN.encode(), b"monteur-download-v1", hashlib.sha256).digest()
DOWNLOAD_TTL_SECONDS = 15 * 60
CORS_ORIGINS = sorted(set(
    ["https://dbrckk.github.io"] +
    [origin.strip().rstrip("/") for origin in os.environ.get("MONTEUR_CORS_ORIGINS", "").split(",") if origin.strip()]
))
if any(not origin.startswith("https://") or "*" in origin for origin in CORS_ORIGINS):
    raise RuntimeError("MONTEUR_CORS_ORIGINS must contain explicit HTTPS origins")
POOL = ThreadPoolExecutor(max_workers=1, thread_name_prefix="video-render")
WRITE_LOCK = asyncio.Lock()
ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}


def database() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=30)
    con.row_factory = sqlite3.Row
    return con


def initialize() -> None:
    with database() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, filename TEXT NOT NULL, status TEXT NOT NULL,
            expected_size INTEGER NOT NULL, stage TEXT NOT NULL DEFAULT 'upload',
            progress REAL NOT NULL DEFAULT 0, error TEXT, options TEXT,
            metadata TEXT, created_at TEXT NOT NULL
        )""")
        con.execute("UPDATE jobs SET status='failed', error='Traitement interrompu par un redémarrage' "
                    "WHERE status='processing'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    with database() as con:
        pending = [x["id"] for x in con.execute("SELECT id FROM jobs WHERE status='queued'")]
    for ident in pending:
        POOL.submit(run_job, ident)
    yield


app = FastAPI(title="Monteur Video", version="0.2.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type", "Upload-Offset"],
)


class UploadRequest(BaseModel):
    filename: str = Field(min_length=1, max_length=240)
    size: int = Field(gt=0)


class LoginRequest(BaseModel):
    token: str = ""


class ExportRequest(BaseModel):
    theme: str = "fitness"
    aspect: str = "vertical"
    seconds: int = Field(default=45, ge=10, le=180)


def authorize(request: Request) -> None:
    """Accept same-origin session cookies or bearer API tokens.

    CORS never grants access to an untrusted origin; requests still require the secret.
    """
    if not API_TOKEN:
        # Never permit the public static site to send cross-origin uploads
        # to an accidentally unauthenticated local installation.
        origin = request.headers.get("origin", "")
        if origin and origin not in {"http://localhost:8000", "http://127.0.0.1:8000"}:
            raise HTTPException(status_code=403, detail="Configurer APP_API_TOKEN pour l'accès distant")
        return
    bearer = request.headers.get("authorization", "")
    candidate = bearer[7:] if bearer.startswith("Bearer ") else ""
    if (hmac.compare_digest(candidate, API_TOKEN) or
            hmac.compare_digest(request.cookies.get("monteur_session", ""), COOKIE_VALUE)):
        return
    raise HTTPException(status_code=401, detail="Authentification requise")


def download_ticket(ident: str, expires: int) -> str:
    message = f"{ident}:{expires}".encode()
    return hmac.new(DOWNLOAD_SECRET, message, hashlib.sha256).hexdigest()


def validate_ticket(ident: str, expires: str | None, signature: str | None) -> bool:
    if not expires or not signature:
        return False
    try:
        expiration = int(expires)
    except (ValueError, TypeError):
        return False
    now = int(time())
    if expiration < now or expiration > now + DOWNLOAD_TTL_SECONDS:
        return False
    return hmac.compare_digest(download_ticket(ident, expiration), signature)



def get_job(ident: str) -> dict:
    try:
        ident = str(uuid.UUID(ident))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="Projet introuvable") from exc
    with database() as con:
        row = con.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Projet introuvable")
    return dict(row)


def source_path(ident: str) -> Path:
    return ROOT / ident / "source"


def update_job(ident: str, **fields: object) -> None:
    allowed = {"status", "stage", "progress", "error", "metadata", "options"}
    if not fields.keys() <= allowed:
        raise ValueError("Mise à jour non autorisée")
    updates = ", ".join(f"{key}=?" for key in fields)
    with database() as con:
        con.execute(f"UPDATE jobs SET {updates} WHERE id=?",
                    (*fields.values(), ident))


def run_job(ident: str) -> None:
    job = get_job(ident)
    folder = ROOT / ident
    settings = json.loads(job["options"])
    try:
        update_job(ident, status="processing", stage="probe", progress=0.01)
        result = edit_video(source_path(ident), folder / "final.mp4",
                            theme=settings["theme"], aspect=settings["aspect"],
                            target_seconds=settings["seconds"],
                            progress=lambda value, stage: update_job(
                                ident, progress=round(value, 3), stage=stage))
        (folder / "metadata.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        # Delete only temporary re-encoded segments: raw source remains for re-use.
        shutil.rmtree(folder / "segments", ignore_errors=True)
        update_job(ident, status="done", progress=1.0, stage="done",
                   metadata=json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        shutil.rmtree(folder / "segments", ignore_errors=True)
        update_job(ident, status="failed", stage="failed",
                   error=f"{type(exc).__name__}: {str(exc)[:1500]}")


@app.get("/", response_class=HTMLResponse)
def homepage():
    return HTMLResponse(WEB.read_text(encoding="utf-8"))


@app.get("/api/health")
def health():
    return {"ok": True, "transcription_optional": True, "max_upload_bytes": MAX_SIZE}


@app.post("/api/login")
def login(data: LoginRequest, response: Response, request: Request):
    if API_TOKEN and not hmac.compare_digest(data.token, API_TOKEN):
        raise HTTPException(status_code=401, detail="Clé incorrecte")
    if API_TOKEN:
        response.set_cookie("monteur_session", COOKIE_VALUE, max_age=86400,
                            httponly=True, samesite="strict",
                            secure=request.url.scheme == "https")
    return {"ok": True}


@app.post("/api/uploads", status_code=201, dependencies=[Depends(authorize)])
def begin_upload(data: UploadRequest):
    suffix = Path(data.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Format de fichier non supporté")
    if data.size > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Fichier trop volumineux pour la limite configurée")
    if data.size > shutil.disk_usage(ROOT).free * 0.7:
        raise HTTPException(status_code=507, detail="Espace disque insuffisant")
    ident = str(uuid.uuid4())
    folder = ROOT / ident
    folder.mkdir(mode=0o700)
    source_path(ident).touch(mode=0o600)
    now = datetime.now(timezone.utc).isoformat()
    with database() as con:
        con.execute("INSERT INTO jobs(id,filename,status,expected_size,stage,created_at)"
                    "VALUES(?,?,?,?,?,?)",
                    (ident, Path(data.filename).name, "uploading", data.size, "upload", now))
    return {"id": ident, "offset": 0, "size": data.size}


@app.get("/api/uploads/{ident}", dependencies=[Depends(authorize)])
def upload_status(ident: str):
    job = get_job(ident)
    return {"id": job["id"], "offset": source_path(job["id"]).stat().st_size,
            "size": job["expected_size"], "status": job["status"]}


@app.patch("/api/uploads/{ident}", dependencies=[Depends(authorize)])
async def append_chunk(ident: str, request: Request):
    async with WRITE_LOCK:
        job = get_job(ident)
        if job["status"] != "uploading":
            raise HTTPException(status_code=409, detail="Transfert déjà terminé")
        source = source_path(job["id"])
        offset = source.stat().st_size
        try:
            declared_offset = int(request.headers.get("upload-offset", "-1"))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Offset invalide") from exc
        if declared_offset != offset:
            raise HTTPException(status_code=409, detail=f"Offset actuel : {offset}",
                                headers={"Upload-Offset": str(offset)})
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                length = int(content_length)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="Taille de bloc invalide") from exc
            if length > CHUNK_LIMIT or offset + length > job["expected_size"]:
                raise HTTPException(status_code=413, detail="Bloc trop volumineux")
        written = 0
        with source.open("r+b") as stream:
            stream.seek(offset)
            try:
                async for piece in request.stream():
                    written += len(piece)
                    if written > CHUNK_LIMIT or offset + written > job["expected_size"]:
                        raise HTTPException(status_code=413, detail="Bloc trop volumineux")
                    stream.write(piece)
            except BaseException:
                stream.truncate(offset)
                raise
        return {"offset": offset + written, "size": job["expected_size"]}


@app.post("/api/uploads/{ident}/complete", dependencies=[Depends(authorize)])
def complete_upload(ident: str, data: ExportRequest):
    job = get_job(ident)
    if job["status"] != "uploading":
        raise HTTPException(status_code=409, detail="Fichier déjà validé")
    if data.theme not in THEMES or data.aspect not in {"vertical", "youtube"}:
        raise HTTPException(status_code=422, detail="Configuration inconnue")
    if source_path(job["id"]).stat().st_size != job["expected_size"]:
        raise HTTPException(status_code=409, detail="Fichier incomplet")
    update_job(job["id"], status="queued", stage="queued",
               options=data.model_dump_json())
    POOL.submit(run_job, job["id"])
    return {"id": job["id"], "status": "queued"}


@app.get("/api/jobs/{ident}", dependencies=[Depends(authorize)])
def job_status(ident: str):
    data = get_job(ident)
    return {"id": data["id"], "filename": data["filename"],
            "status": data["status"], "stage": data["stage"],
            "progress": data["progress"], "error": data["error"],
            "metadata": json.loads(data["metadata"]) if data["metadata"] else None}


@app.get("/api/jobs/{ident}/download-link", dependencies=[Depends(authorize)])
def get_download_link(ident: str):
    job = get_job(ident)
    if job["status"] != "done" or not (ROOT / job["id"] / "final.mp4").exists():
        raise HTTPException(status_code=404, detail="Montage non disponible")
    expires = int(time()) + DOWNLOAD_TTL_SECONDS
    token = download_ticket(job["id"], expires)
    return {"url": f"/api/jobs/{job['id']}/download?expires={expires}&ticket={token}",
            "expires_in": DOWNLOAD_TTL_SECONDS}


@app.get("/api/jobs/{ident}/download")
def download_video(ident: str, request: Request, expires: str | None = None,
                   ticket: str | None = None, inline: bool = False):
    job = get_job(ident)
    if not validate_ticket(job["id"], expires, ticket):
        authorize(request)
    destination = ROOT / job["id"] / "final.mp4"
    if job["status"] != "done" or not destination.exists():
        raise HTTPException(status_code=404, detail="Montage non disponible")
    return FileResponse(destination, media_type="video/mp4",
                        filename=f"montage-{ident[:8]}.mp4",
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, no-store",
                                 "Referrer-Policy": "no-referrer"})


@app.delete("/api/jobs/{ident}", dependencies=[Depends(authorize)])
def delete_job(ident: str):
    job = get_job(ident)
    if job["status"] not in {"done", "failed", "uploading"}:
        raise HTTPException(status_code=409, detail="Traitement en cours")
    with database() as con:
        con.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
    shutil.rmtree(ROOT / job["id"], ignore_errors=True)
    return {"deleted": True}
