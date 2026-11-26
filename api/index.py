"""
Vercel entrypoint.

Vercel's Python runtime looks for a module-level `app` (WSGI or ASGI) in any
file under /api and wraps it as a serverless function. vercel.json rewrites
every /api/* request to this one function, which re-exports the real FastAPI
app defined in backend/main.py -- so the route definitions live in one place
and work identically under `uvicorn` locally and on Vercel.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("VERCEL", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.main import app  # noqa: E402  (import after sys.path tweak, on purpose)
