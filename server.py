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
from contextlib import asynccontextmanager, suppress
from datetime import datetime, timedelta, timezone
from time import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from editor import THEMES, edit_video
from montage import MAX_SOURCES, FILTER_PRESETS, edit_many, filter_catalog, apply_filter

ROOT = Path(os.environ.get("EDITOR_DATA_DIR", "./data")).resolve()
ROOT.mkdir(parents=True, exist_ok=True)
DB = ROOT / "jobs.sqlite3"
WEB = Path(__file__).resolve().parent / "web" / "index.html"
MAX_SIZE = int(float(os.environ.get("MAX_UPLOAD_GB", "20")) * 1024 ** 3)
CHUNK_LIMIT = 16 * 1024 * 1024
UPLOAD_TTL_HOURS = max(1, int(os.environ.get("UPLOAD_TTL_HOURS", "72")))
RESULT_TTL_DAYS = max(1, int(os.environ.get("RESULT_TTL_DAYS", "14")))
CLEANUP_INTERVAL_SECONDS = 6 * 3600
API_TOKEN = os.environ.get("APP_API_TOKEN", "")
PUBLIC_DEMO = os.environ.get("MONTEUR_PUBLIC_DEMO", "0") == "1"
PUBLIC_MAX_ACTIVE = max(1, int(os.environ.get("MONTEUR_PUBLIC_MAX_ACTIVE", "3")))
PUBLIC_MAX_UPLOADS = max(MAX_SOURCES, int(os.environ.get("MONTEUR_PUBLIC_MAX_UPLOADS", "24")))
COOKIE_VALUE = hmac.new(API_TOKEN.encode(), b"monteur-session-v1", hashlib.sha256).hexdigest()
DOWNLOAD_SECRET = hmac.new(API_TOKEN.encode(), b"monteur-download-v1", hashlib.sha256).digest()
DOWNLOAD_TTL_SECONDS = 15 * 60
CORS_ORIGINS = sorted(set(
    ["https://dbrckk.github.io", "https://angled-gate-srzt937.shipstatic.com",
     "https://snappy-gate-x58qpre.shipstatic.com"] +
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
            metadata TEXT, created_at TEXT NOT NULL, updated_at TEXT
        )""")
        # SQLite migration: keep existing users' projects when upgrading.
        cols = {row["name"] for row in con.execute("PRAGMA table_info(jobs)")}
        if "updated_at" not in cols:
            con.execute("ALTER TABLE jobs ADD COLUMN updated_at TEXT")
        con.execute("UPDATE jobs SET updated_at=created_at WHERE updated_at IS NULL")
        # Renders interrupted by a restart are retried from their saved source files.
        con.execute("UPDATE jobs SET status='queued', stage='queued', progress=0, error=NULL "
                    "WHERE status='processing'")
        con.execute("""CREATE TABLE IF NOT EXISTS filter_exports (
            job_id TEXT NOT NULL, preset TEXT NOT NULL,
            status TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0,
            error TEXT, PRIMARY KEY(job_id, preset)
        )""")
        con.execute("UPDATE filter_exports SET status='queued', progress=0, error=NULL "
                    "WHERE status='processing'")


def cleanup_expired(now: datetime | None = None) -> int:
    """Prune abandoned uploads and old completed jobs, never live jobs/renders.

    All DB changes happen in one transaction; file deletion follows the commit.
    A consumed source is deleted only with its parent montage.
    """
    now = now or datetime.now(timezone.utc)
    to_remove: list[str] = []
    with database() as con:
        con.execute("BEGIN IMMEDIATE")
        rows = list(con.execute(
            "SELECT id,status,created_at,updated_at,options FROM jobs "
            "WHERE status IN ('uploading','done','failed')"))
        for row in rows:
            try:
                stamp = datetime.fromisoformat(row["updated_at"] or row["created_at"])
                if stamp.tzinfo is None:
                    stamp = stamp.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                continue
            cutoff = (timedelta(hours=UPLOAD_TTL_HOURS)
                      if row["status"] == "uploading"
                      else timedelta(days=RESULT_TTL_DAYS))
            if now - stamp < cutoff:
                continue
            # Prevent deleting a master whose filter still needs it.
            active = con.execute(
                "SELECT COUNT(*) FROM filter_exports WHERE job_id=? "
                "AND status IN ('queued','processing')", (row["id"],)).fetchone()[0]
            if active:
                continue
            options = json.loads(row["options"]) if row["options"] else {}
            sources = options.get("sources", []) if isinstance(options, dict) else []
            con.execute("DELETE FROM filter_exports WHERE job_id=?", (row["id"],))
            con.execute("DELETE FROM jobs WHERE id=?", (row["id"],))
            to_remove.append(row["id"])
            for source_id in sources:
                cur = con.execute("DELETE FROM jobs WHERE id=? AND status='consumed'",
                                  (source_id,))
                if cur.rowcount:
                    to_remove.append(source_id)
    for ident in to_remove:
        shutil.rmtree(ROOT / ident, ignore_errors=True)
    return len(to_remove)


async def periodic_cleanup() -> None:
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        await asyncio.to_thread(cleanup_expired)


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize()
    cleanup_expired()
    with database() as con:
        pending = [x["id"] for x in con.execute("SELECT id FROM jobs WHERE status='queued'")]
    for ident in pending:
        POOL.submit(run_job, ident)
    with database() as con:
        filters = list(con.execute(
            "SELECT job_id, preset FROM filter_exports WHERE status='queued'"))
    for item in filters:
        POOL.submit(run_filter, item["job_id"], item["preset"])
    janitor = asyncio.create_task(periodic_cleanup())
    try:
        yield
    finally:
        janitor.cancel()
        with suppress(asyncio.CancelledError):
            await janitor


app = FastAPI(title="Monteur Video", version="1.0.0", lifespan=lifespan)
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
    seconds: int = Field(default=0, ge=0, le=180)


class MontageRequest(ExportRequest):
    upload_ids: list[str] = Field(min_length=1, max_length=MAX_SOURCES)
    project_id: str | None = None


class FilterRequest(BaseModel):
    preset: str


def authorize(request: Request) -> None:
    """Accept same-origin session cookies or bearer API tokens.

    CORS never grants access to an untrusted origin; requests still require the secret.
    """
    if PUBLIC_DEMO and not API_TOKEN:
        origin = request.headers.get("origin", "")
        if origin and origin not in CORS_ORIGINS and origin not in {"http://localhost:8000", "http://127.0.0.1:8000"}:
            raise HTTPException(status_code=403, detail="Origine non autorisée")
        return
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


def download_ticket(ident: str, expires: int, preset: str = "original") -> str:
    message = f"{ident}:{preset}:{expires}".encode()
    return hmac.new(DOWNLOAD_SECRET, message, hashlib.sha256).hexdigest()


def validate_ticket(ident: str, expires: str | None, signature: str | None,
                    preset: str = "original") -> bool:
    if not expires or not signature:
        return False
    try:
        expiration = int(expires)
    except (ValueError, TypeError):
        return False
    now = int(time())
    if expiration < now or expiration > now + DOWNLOAD_TTL_SECONDS:
        return False
    return hmac.compare_digest(download_ticket(ident, expiration, preset), signature)



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
    if not fields or not fields.keys() <= allowed:
        raise ValueError("Mise à jour non autorisée")
    updates = ", ".join(f"{key}=?" for key in fields)
    with database() as con:
        con.execute(f"UPDATE jobs SET {updates}, updated_at=? WHERE id=?",
                    (*fields.values(), datetime.now(timezone.utc).isoformat(), ident))


def run_job(ident: str) -> None:
    job = get_job(ident)
    folder = ROOT / ident
    settings = json.loads(job["options"])
    render_size = int(os.environ.get("MONTEUR_RENDER_SIZE", "1080"))
    if render_size not in (360, 480, 720, 1080):
        raise ValueError("MONTEUR_RENDER_SIZE must be 360, 480, 720 or 1080")
    try:
        update_job(ident, status="processing", stage="probe", progress=0.01)
        progress = lambda value, stage: update_job(
            ident, progress=round(value, 3), stage=stage)
        if "sources" in settings:
            sources = [str(uuid.UUID(src)) for src in settings["sources"]]
            with database() as con:
                names = {
                    row["id"]: row["filename"]
                    for row in con.execute(
                        f"SELECT id,filename FROM jobs WHERE id IN ({','.join('?' for _ in sources)})",
                        sources)
                }
            result = edit_many(
                [source_path(src) for src in sources], folder / "final.mp4",
                theme=settings["theme"], aspect=settings["aspect"],
                target_seconds=settings["seconds"],
                source_names=[names[src] for src in sources],
                size=render_size, progress=progress,
            )
        else:
            result = edit_video(source_path(ident), folder / "final.mp4",
                                theme=settings["theme"], aspect=settings["aspect"],
                                target_seconds=settings["seconds"],
                                size=render_size, progress=progress)
        (folder / "metadata.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        # Delete only temporary re-encoded segments: raw source remains for re-use.
        shutil.rmtree(folder / "segments", ignore_errors=True)
        shutil.rmtree(folder / "rushes", ignore_errors=True)
        update_job(ident, status="done", progress=1.0, stage="done",
                   metadata=json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        shutil.rmtree(folder / "segments", ignore_errors=True)
        shutil.rmtree(folder / "rushes", ignore_errors=True)
        update_job(ident, status="failed", stage="failed",
                   error=f"{type(exc).__name__}: {str(exc)[:1500]}")


def update_filter(ident: str, preset: str, **fields: object) -> None:
    if not fields.keys() <= {"status", "progress", "error"}:
        raise ValueError("Mise à jour de filtre non autorisée")
    updates = ", ".join(f"{key}=?" for key in fields)
    with database() as con:
        con.execute(f"UPDATE filter_exports SET {updates} WHERE job_id=? AND preset=?",
                    (*fields.values(), ident, preset))


def run_filter(ident: str, preset: str) -> None:
    """Post-process only the immutable finished master."""
    folder = ROOT / ident
    destination = folder / "filters" / f"{preset}.mp4"
    try:
        update_filter(ident, preset, status="processing", progress=0.01, error=None)
        apply_filter(folder / "final.mp4", destination, preset,
                     progress=lambda value, _: update_filter(
                         ident, preset, progress=round(value, 3)))
        update_filter(ident, preset, status="done", progress=1.0)
    except Exception as exc:
        destination.unlink(missing_ok=True)
        update_filter(ident, preset, status="failed",
                      error=f"{type(exc).__name__}: {str(exc)[:1500]}")


@app.get("/", response_class=HTMLResponse)
def homepage():
    return HTMLResponse(WEB.read_text(encoding="utf-8"))


@app.get("/manifest.webmanifest")
def mobile_manifest():
    return FileResponse(WEB.parent / "manifest.webmanifest",
                        media_type="application/manifest+json")


@app.get("/icon.svg")
def mobile_icon():
    return FileResponse(WEB.parent / "icon.svg", media_type="image/svg+xml")


@app.get("/sw.js")
def mobile_service_worker():
    return FileResponse(WEB.parent / "sw.js", media_type="application/javascript",
                        headers={"Service-Worker-Allowed": "/",
                                 "Cache-Control": "no-cache"})


@app.get("/api/health")
def health():
    return {"ok": True, "version": app.version, "transcription_optional": True,
            "max_upload_bytes": MAX_SIZE, "max_sources": MAX_SOURCES,
            "upload_ttl_hours": UPLOAD_TTL_HOURS,
            "result_ttl_days": RESULT_TTL_DAYS}


@app.get("/api/session", dependencies=[Depends(authorize)])
def session_info():
    """Authenticated readiness check for remote mobile clients."""
    return {"ok": True, "version": app.version,
            "max_sources": MAX_SOURCES, "max_upload_bytes": MAX_SIZE,
            "free_disk_bytes": shutil.disk_usage(ROOT).free,
            "upload_ttl_hours": UPLOAD_TTL_HOURS,
            "result_ttl_days": RESULT_TTL_DAYS}


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
    if PUBLIC_DEMO:
        with database() as con:
            uploads = con.execute("SELECT COUNT(*) FROM jobs WHERE status='uploading'").fetchone()[0]
        if uploads >= PUBLIC_MAX_UPLOADS:
            raise HTTPException(status_code=429, detail="Trop de transferts en cours, réessayer plus tard")
    ident = str(uuid.uuid4())
    folder = ROOT / ident
    folder.mkdir(mode=0o700)
    source_path(ident).touch(mode=0o600)
    now = datetime.now(timezone.utc).isoformat()
    with database() as con:
        con.execute("INSERT INTO jobs(id,filename,status,expected_size,stage,created_at,updated_at)"
                    "VALUES(?,?,?,?,?,?,?)",
                    (ident, Path(data.filename).name, "uploading", data.size, "upload", now, now))
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
        update_job(job["id"], progress=round((offset + written) / job["expected_size"], 3))
        return {"offset": offset + written, "size": job["expected_size"]}


@app.post("/api/uploads/{ident}/complete", dependencies=[Depends(authorize)])
def complete_upload(ident: str, data: ExportRequest):
    job = get_job(ident)
    if data.theme not in THEMES or data.aspect not in {"vertical", "youtube"}:
        raise HTTPException(status_code=422, detail="Configuration inconnue")
    # Prevent two clients finishing the same upload simultaneously.
    with database() as con:
        con.execute("BEGIN IMMEDIATE")
        current = con.execute("SELECT status,expected_size FROM jobs WHERE id=?",
                              (job["id"],)).fetchone()
        if current is None or current["status"] != "uploading":
            raise HTTPException(status_code=409, detail="Fichier déjà validé")
        source = source_path(job["id"])
        if not source.is_file() or source.stat().st_size != current["expected_size"]:
            raise HTTPException(status_code=409, detail="Fichier incomplet")
        con.execute("UPDATE jobs SET status='queued',stage='queued', options=?,"
                    "updated_at=? WHERE id=?",
                    (data.model_dump_json(), datetime.now(timezone.utc).isoformat(),
                     job["id"]))
    POOL.submit(run_job, job["id"])
    return {"id": job["id"], "status": "queued"}


@app.post("/api/montages", status_code=201, dependencies=[Depends(authorize)])
def create_montage(data: MontageRequest):
    """Atomically consume 1–10 fully uploaded rushes into one montage job.

    An optional client-generated UUID makes retry safe if a mobile connection
    drops after the server has already accepted the creation request.
    """
    if data.theme not in THEMES or data.aspect not in {"vertical", "youtube"}:
        raise HTTPException(status_code=422, detail="Paramètres de montage inconnus")
    try:
        ids = [str(uuid.UUID(item)) for item in data.upload_ids]
        ident = str(uuid.UUID(data.project_id)) if data.project_id else str(uuid.uuid4())
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Identifiant invalide") from exc
    if len(set(ids)) != len(ids):
        raise HTTPException(status_code=422, detail="Une vidéo ne peut apparaître deux fois")
    if ident in ids:
        raise HTTPException(status_code=422, detail="Identifiant de montage en conflit")
    settings = {"theme": data.theme, "aspect": data.aspect,
                "seconds": data.seconds, "sources": ids}
    with database() as con:
        con.execute("BEGIN IMMEDIATE")
        existing = con.execute("SELECT * FROM jobs WHERE id=?", (ident,)).fetchone()
        if existing is not None:
            if existing["options"] and json.loads(existing["options"]) == settings:
                return {"id": ident, "status": existing["status"],
                        "source_count": len(ids), "reused": True}
            raise HTTPException(status_code=409, detail="Identifiant de montage déjà utilisé")
        rows = {
            row["id"]: row
            for row in con.execute(
                f"SELECT * FROM jobs WHERE id IN ({','.join('?' for _ in ids)})", ids)
        }
        total_size = 0
        for source_id in ids:
            row = rows.get(source_id)
            if row is None or row["status"] != "uploading":
                raise HTTPException(status_code=409, detail="Fichier indisponible ou déjà utilisé")
            source = source_path(source_id)
            if not source.is_file() or source.stat().st_size != row["expected_size"]:
                raise HTTPException(status_code=409, detail="Transfert incomplet")
            total_size += row["expected_size"]
        (ROOT / ident).mkdir(mode=0o700, exist_ok=False)
        now = datetime.now(timezone.utc).isoformat()
        con.execute(
            "INSERT INTO jobs(id,filename,status,expected_size,stage,options,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (ident, f"Montage de {len(ids)} vidéos", "queued",
             total_size, "queued", json.dumps(settings), now, now))
        con.execute(
            f"UPDATE jobs SET status='consumed',stage='consumed' "
            f"WHERE id IN ({','.join('?' for _ in ids)})", ids)
    POOL.submit(run_job, ident)
    return {"id": ident, "status": "queued",
            "source_count": len(ids), "reused": False}


@app.get("/api/jobs/{ident}", dependencies=[Depends(authorize)])
def job_status(ident: str):
    data = get_job(ident)
    expires_at = None
    if data["status"] in {"done", "failed"}:
        stamp = datetime.fromisoformat(data["updated_at"] or data["created_at"])
        expires_at = (stamp + timedelta(days=RESULT_TTL_DAYS)).isoformat()
    return {"id": data["id"], "filename": data["filename"],
            "status": data["status"], "stage": data["stage"],
            "progress": data["progress"], "error": data["error"],
            "expires_at": expires_at,
            "metadata": json.loads(data["metadata"]) if data["metadata"] else None}


@app.post("/api/jobs/{ident}/retry", dependencies=[Depends(authorize)])
def retry_failed_job(ident: str):
    """Re-queue an unsuccessful render without requiring a fresh smartphone upload."""
    job = get_job(ident)
    with database() as con:
        con.execute("BEGIN IMMEDIATE")
        current = con.execute(
            "SELECT status,options FROM jobs WHERE id=?", (job["id"],)).fetchone()
        if current is None or current["status"] != "failed" or not current["options"]:
            raise HTTPException(status_code=409, detail="Montage non relançable")
        options = json.loads(current["options"])
        sources = options.get("sources", [job["id"]])
        for source_id in sources:
            if not source_path(source_id).is_file():
                raise HTTPException(
                    status_code=409,
                    detail="Rush source manquant : nouvelle importation nécessaire")
        con.execute(
            "UPDATE jobs SET status='queued',stage='queued',progress=0,"
            "error=NULL,metadata=NULL,updated_at=? WHERE id=?",
            (datetime.now(timezone.utc).isoformat(), job["id"]))
    POOL.submit(run_job, job["id"])
    return {"id": job["id"], "status": "queued"}


@app.get("/api/jobs/{ident}/filters", dependencies=[Depends(authorize)])
def list_job_filters(ident: str):
    job = get_job(ident)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Le montage n'est pas encore terminé")
    settings = json.loads(job["options"])
    catalog = filter_catalog(settings["theme"])
    with database() as con:
        statuses = {
            row["preset"]: dict(row)
            for row in con.execute(
                "SELECT preset,status,progress,error FROM filter_exports WHERE job_id=?",
                (job["id"],))
        }
    for item in catalog:
        state = statuses.get(item["id"])
        item.update(status=state["status"] if state else (
            "done" if item["id"] == "original" else "available"),
            progress=state["progress"] if state else (1.0 if item["id"] == "original" else 0.0),
            error=state["error"] if state else None)
    return {"theme": settings["theme"], "filters": catalog}


@app.post("/api/jobs/{ident}/filters", status_code=202, dependencies=[Depends(authorize)])
def create_filter_export(ident: str, data: FilterRequest):
    job = get_job(ident)
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail="Le montage n'est pas terminé")
    if data.preset not in FILTER_PRESETS or data.preset == "original":
        raise HTTPException(status_code=422, detail="Filtre inconnu")
    if not (ROOT / job["id"] / "final.mp4").exists():
        raise HTTPException(status_code=404, detail="Montage original absent")
    with database() as con:
        con.execute("BEGIN IMMEDIATE")
        row = con.execute(
            "SELECT * FROM filter_exports WHERE job_id=? AND preset=?",
            (job["id"], data.preset)).fetchone()
        if row is not None:
            if row["status"] in {"processing", "queued"}:
                return {"preset": data.preset, "status": row["status"]}
            if row["status"] == "done" and (
                    ROOT / job["id"] / "filters" / f"{data.preset}.mp4").is_file():
                return {"preset": data.preset, "status": "done"}
            # Missing/corrupted output can be regenerated by the user.
        if row:
            con.execute(
                "UPDATE filter_exports SET status='queued', progress=0, error=NULL "
                "WHERE job_id=? AND preset=?", (job["id"], data.preset))
        else:
            con.execute(
                "INSERT INTO filter_exports(job_id,preset,status) VALUES(?,?,'queued')",
                (job["id"], data.preset))
    POOL.submit(run_filter, job["id"], data.preset)
    return {"preset": data.preset, "status": "queued"}


@app.get("/api/jobs/{ident}/download-link", dependencies=[Depends(authorize)])
def get_download_link(ident: str, preset: str = "original"):
    job = get_job(ident)
    if preset not in FILTER_PRESETS:
        raise HTTPException(status_code=404, detail="Filtre inexistant")
    if job["status"] != "done":
        raise HTTPException(status_code=404, detail="Montage non disponible")
    if preset != "original":
        with database() as con:
            export = con.execute(
                "SELECT status FROM filter_exports WHERE job_id=? AND preset=?",
                (job["id"], preset)).fetchone()
        if export is None or export["status"] != "done":
            raise HTTPException(status_code=404, detail="Filtre non encore disponible")
    destination = (ROOT / job["id"] / "final.mp4" if preset == "original"
                   else ROOT / job["id"] / "filters" / f"{preset}.mp4")
    if not destination.exists():
        raise HTTPException(status_code=404, detail="Fichier vidéo absent")
    expires = int(time()) + DOWNLOAD_TTL_SECONDS
    token = download_ticket(job["id"], expires, preset)
    return {"url": f"/api/jobs/{job['id']}/download?expires={expires}&ticket={token}&preset={preset}",
            "expires_in": DOWNLOAD_TTL_SECONDS, "preset": preset}


@app.get("/api/jobs/{ident}/download")
def download_video(ident: str, request: Request, expires: str | None = None,
                   ticket: str | None = None, inline: bool = False,
                   preset: str = "original"):
    job = get_job(ident)
    if preset not in FILTER_PRESETS:
        raise HTTPException(status_code=404, detail="Filtre inconnu")
    if not validate_ticket(job["id"], expires, ticket, preset):
        authorize(request)
    if preset != "original":
        with database() as con:
            export = con.execute(
                "SELECT status FROM filter_exports WHERE job_id=? AND preset=?",
                (job["id"], preset)).fetchone()
        if export is None or export["status"] != "done":
            raise HTTPException(status_code=404, detail="Filtre indisponible")
    destination = (ROOT / job["id"] / "final.mp4" if preset == "original"
                   else ROOT / job["id"] / "filters" / f"{preset}.mp4")
    if job["status"] != "done" or not destination.exists():
        raise HTTPException(status_code=404, detail="Montage non disponible")
    return FileResponse(destination, media_type="video/mp4",
                        filename=f"montage-{job['id'][:8]}-{preset}.mp4",
                        content_disposition_type="inline" if inline else "attachment",
                        headers={"Cache-Control": "private, no-store",
                                 "Referrer-Policy": "no-referrer"})


@app.delete("/api/jobs/{ident}", dependencies=[Depends(authorize)])
def delete_job(ident: str):
    job = get_job(ident)
    if job["status"] not in {"done", "failed", "uploading"}:
        raise HTTPException(status_code=409, detail="Traitement en cours")
    settings = json.loads(job["options"]) if job["options"] else {}
    attached = settings.get("sources", [])
    with database() as con:
        con.execute("BEGIN IMMEDIATE")
        active = con.execute(
            "SELECT COUNT(*) FROM filter_exports WHERE job_id=? "
            "AND status IN ('queued','processing')", (job["id"],)).fetchone()[0]
        if active:
            raise HTTPException(status_code=409,
                                detail="Attendre la fin des filtres avant de supprimer les fichiers")
        con.execute("DELETE FROM filter_exports WHERE job_id=?", (job["id"],))
        con.execute("DELETE FROM jobs WHERE id=?", (job["id"],))
        for source_id in attached:
            con.execute("DELETE FROM jobs WHERE id=? AND status='consumed'", (source_id,))
    shutil.rmtree(ROOT / job["id"], ignore_errors=True)
    for source_id in attached:
        shutil.rmtree(ROOT / source_id, ignore_errors=True)
    return {"deleted": True, "sources_deleted": len(attached)}
