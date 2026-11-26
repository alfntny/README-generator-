"""
Vercel entrypoint.

Vercel's zero-config FastAPI detection introspects a module-level `app`
(the actual FastAPI instance, with its real routes) at a supported
entrypoint like this one. This file just re-exports the real app defined in
backend/main.py -- so the route definitions live in one place and work
identically under `uvicorn` locally and on Vercel. No vercel.json rewrites
are needed (and one that rewrites /api/* to this file can actually conflict
with the zero-config routing and cause 404s).
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("VERCEL", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import app  # noqa: E402  (import after sys.path tweak, on purpose)
