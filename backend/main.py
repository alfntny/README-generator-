"""
FastAPI app for the README generator.

Endpoints:
  POST /api/generate-from-prompt   { "prompt": str }                -> { "readme": str }
  POST /api/generate-from-upload   multipart form: files[] + prompt -> { "readme": str, "facts": {...} }
  GET  /api/health                                                  -> { "status": "ok" }

Serves the static frontend from ../public at "/" during local dev.
"""

from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .analyzer import analyze_project
from .writer import write_from_facts, write_from_prompt

app = FastAPI(title="README Generator")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB total, generous for a student project
ALLOWED_ARCHIVE_EXTS = {".zip"}


class PromptRequest(BaseModel):
    prompt: str


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.post("/api/generate-from-prompt")
def generate_from_prompt(body: PromptRequest):
    if not body.prompt or not body.prompt.strip():
        raise HTTPException(400, "prompt must not be empty")
    readme = write_from_prompt(body.prompt)
    return {"readme": readme}


@app.post("/api/generate-from-upload")
async def generate_from_upload(
    files: list[UploadFile] = File(...),
    prompt: str = Form(default=""),
):
    if not files:
        raise HTTPException(400, "no files uploaded")

    with tempfile.TemporaryDirectory(prefix="readmegen_") as tmp:
        tmp_path = Path(tmp)
        extract_root = tmp_path / "project"
        extract_root.mkdir()

        total_bytes = 0
        for f in files:
            contents = await f.read()
            total_bytes += len(contents)
            if total_bytes > MAX_UPLOAD_BYTES:
                raise HTTPException(413, "upload too large")

            safe_name = Path(f.filename or "file").name
            dest = extract_root / safe_name

            if dest.suffix.lower() in ALLOWED_ARCHIVE_EXTS:
                zip_path = tmp_path / safe_name
                zip_path.write_bytes(contents)
                try:
                    with zipfile.ZipFile(zip_path) as zf:
                        _safe_extract(zf, extract_root)
                except zipfile.BadZipFile:
                    raise HTTPException(400, f"{safe_name} is not a valid zip file")
            else:
                # preserve relative path if the browser sent one (webkitRelativePath)
                rel = getattr(f, "filename", None) or safe_name
                rel_path = extract_root / Path(rel)
                rel_path.parent.mkdir(parents=True, exist_ok=True)
                rel_path.write_bytes(contents)

        facts = analyze_project(extract_root)
        readme = write_from_facts(facts, extra_prompt=prompt)
        return JSONResponse({"readme": readme, "facts": facts.to_dict()})


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> None:
    """Extract a zip while refusing path-traversal entries (zip-slip)."""
    dest = dest.resolve()
    for member in zf.infolist():
        member_path = (dest / member.filename).resolve()
        if not str(member_path).startswith(str(dest)):
            continue  # skip anything trying to escape the extraction dir
        zf.extract(member, dest)


# --- static frontend --------------------------------------------------------
# Only mounted for local dev (`uvicorn backend.main:app`). On Vercel, files
# under /public are served directly by the platform and never reach this
# function -- see vercel.json's rewrite, which sends only /api/* here.

_static_dir = Path(__file__).resolve().parent.parent / "public"
if _static_dir.exists() and not os.environ.get("VERCEL"):
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="frontend")
