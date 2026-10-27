"""Printdash – ett modernt webbgränssnitt för CUPS."""

from __future__ import annotations

import os
import re
import secrets
import tempfile
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.staticfiles import StaticFiles

from .backend import BackendError, make_backend

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_MB = int(os.environ.get("PRINTDASH_MAX_UPLOAD_MB", "50"))
ALLOWED_SUFFIXES = {".pdf", ".ps", ".txt", ".png", ".jpg", ".jpeg"}
PAGE_RANGES_RE = re.compile(r"^\s*\d+(\s*-\s*\d+)?(\s*,\s*\d+(\s*-\s*\d+)?)*\s*$")

app = FastAPI(title="Printdash", docs_url="/api/docs", redoc_url=None)
backend = make_backend()

# --- Inloggning (valfri) ----------------------------------------------------
# Sätt PRINTDASH_PASSWORD för att kräva lösenord. Användarnamnet är valfritt.
_security = HTTPBasic(auto_error=False)


def require_auth(creds: Optional[HTTPBasicCredentials] = Depends(_security)) -> None:
    password = os.environ.get("PRINTDASH_PASSWORD")
    if not password:
        return
    if creds is None or not secrets.compare_digest(creds.password.encode(), password.encode()):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Inloggning krävs",
            headers={"WWW-Authenticate": 'Basic realm="Printdash"'},
        )


@app.exception_handler(BackendError)
async def _backend_error(_, exc: BackendError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


# --- API --------------------------------------------------------------------
api = Depends(require_auth)


@app.get("/api/health")
def health():
    return {"ok": True, "mock": type(backend).__name__ == "MockBackend"}


@app.get("/api/printers", dependencies=[api])
def printers():
    return [p.to_dict() for p in backend.list_printers()]


@app.get("/api/jobs", dependencies=[api])
def jobs(which: Literal["not-completed", "completed", "all"] = "not-completed", limit: int = 50):
    return [j.to_dict() for j in backend.list_jobs(which, max(1, min(limit, 500)))]


JobAction = Literal["cancel", "hold", "release", "restart"]


@app.post("/api/jobs/{job_id}/{action}", dependencies=[api])
def job_action(job_id: int, action: JobAction):
    getattr(backend, f"{action}_job")(job_id)
    return {"ok": True}


PrinterAction = Literal["pause", "resume", "default", "testpage", "cancel-all"]


@app.post("/api/printers/{name}/{action}", dependencies=[api])
def printer_action(name: str, action: PrinterAction):
    if action == "pause":
        backend.pause_printer(name)
    elif action == "resume":
        backend.resume_printer(name)
    elif action == "default":
        backend.set_default(name)
    elif action == "cancel-all":
        backend.cancel_all(name)
    else:
        return {"ok": True, "job_id": backend.test_page(name)}
    return {"ok": True}


@app.post("/api/print", dependencies=[api])
async def print_file(
    printer: str = Form(...),
    file: UploadFile = File(...),
    copies: int = Form(1),
    page_ranges: str = Form(""),
    fit_to_page: bool = Form(False),
):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Filtypen stöds inte. Tillåtna: {', '.join(sorted(ALLOWED_SUFFIXES))}")
    if not 1 <= copies <= 99:
        raise HTTPException(400, "Antal kopior måste vara 1–99")
    if page_ranges and not PAGE_RANGES_RE.match(page_ranges):
        raise HTTPException(400, "Ogiltigt sidintervall, använd t.ex. 1-3,5")

    options = {"copies": str(copies)}
    if page_ranges:
        options["page-ranges"] = page_ranges.replace(" ", "")
    if fit_to_page:
        options["fit-to-page"] = "true"

    limit = MAX_UPLOAD_MB * 1024 * 1024
    tmp = tempfile.NamedTemporaryFile(prefix="printdash-", suffix=suffix, delete=False)
    try:
        size = 0
        with tmp:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > limit:
                    raise HTTPException(413, f"Filen är större än {MAX_UPLOAD_MB} MB")
                tmp.write(chunk)
        title = file.filename or "Utskrift"
        job_id = backend.print_file(printer, tmp.name, title, options)
        return {"ok": True, "job_id": job_id}
    finally:
        # CUPS kopierar filen till sin spool direkt, så den kan tas bort nu
        os.unlink(tmp.name)


# --- Frontend ---------------------------------------------------------------
@app.get("/", include_in_schema=False, dependencies=[api])
def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
