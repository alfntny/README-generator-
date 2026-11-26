# README Generator

A small web app that generates a GitHub `README.md` two ways:

1. **Describe it** — type a short prompt about your project and get a full README draft.
2. **Upload it** — drag in your project files (or a `.zip`), and it statically analyzes
   the codebase (languages, dependency manifests, entry points, license, CI, Docker)
   and writes a README grounded in those facts.

If an `ANTHROPIC_API_KEY` is set in the environment, both modes use Claude to write
natural prose. Without a key, a deterministic template renderer takes over — so the
app works fully offline / for free, just with slightly more boilerplate phrasing.

## Project structure

```
readme-generator/
├── api/
│   └── index.py        # Vercel serverless entrypoint; re-exports backend.main:app
├── backend/
│   ├── analyzer.py     # static analysis of an uploaded project (languages, manifests, structure...)
│   ├── writer.py       # turns a prompt or analysis facts into README markdown (LLM + template fallback)
│   └── main.py          # FastAPI app: /api/generate-from-prompt, /api/generate-from-upload
├── public/
│   ├── index.html
│   ├── style.css
│   └── app.js          # tabs, drag-and-drop upload, markdown preview, copy/download
├── vercel.json          # routes /api/* to api/index.py; everything else is static from /public
├── requirements.txt
└── README.md
```

## Running it locally

```bash
pip install -r requirements.txt

# optional, for LLM-written prose instead of the template:
export ANTHROPIC_API_KEY=sk-ant-...

uvicorn backend.main:app --reload --port 8000
```

Then open **http://localhost:8000** — the FastAPI app serves the frontend directly,
so there's nothing else to start.

## Deploying to Vercel

```bash
npm i -g vercel   # if you don't have the CLI
vercel             # from the project root; follow the prompts
```

- `vercel.json` rewrites every `/api/*` request to the single `api/index.py`
  function, which just imports the real FastAPI app from `backend/main.py` —
  so there's one set of route definitions, used both locally and on Vercel.
- Everything in `public/` is served by Vercel directly as static assets; the
  function is never hit for `/`, `/style.css`, etc.
- If you want LLM-written prose instead of the template fallback, set
  `ANTHROPIC_API_KEY` under **Project Settings → Environment Variables** on
  Vercel (and redeploy — env var changes don't apply retroactively).
- **Upload size**: Vercel's serverless functions have a request body limit
  (4.5 MB on the Hobby plan). That's plenty for a handful of source files,
  but a large zipped repo (with build artifacts, `node_modules`, etc. left
  in) can exceed it before the app's own 25 MB check ever runs. Zip just the
  source files, or if you need bigger uploads, host the backend on a plain
  VM/Render/Railway instead and keep only the frontend on Vercel.

## API

### `POST /api/generate-from-prompt`
```json
{ "prompt": "A Flask app that tracks water intake, with login and weekly charts." }
```
→ `{ "readme": "# ...markdown..." }`

### `POST /api/generate-from-upload`
Multipart form:
- `files` — one or more files, a folder (via `webkitdirectory`), or a single `.zip`
- `prompt` — optional extra context string

→ `{ "readme": "# ...markdown...", "facts": { ...detected languages, deps, structure... } }`

## What the analyzer detects

- **Languages**, by file extension, counted and ranked
- **Dependency manifests**: `package.json`, `requirements.txt`, `pyproject.toml`,
  `Pipfile`, `pom.xml`, `build.gradle(.kts)`, `Cargo.toml`, `go.mod`, `Gemfile`,
  `composer.json`, `CMakeLists.txt` — each parsed for its top-level dependency names
- **Entry points** (`main.py`, `app.py`, `index.js`, `Main.java`, …)
- **License** file + detected license name (MIT/Apache/GPL/BSD/…)
- **Docker** (`Dockerfile`, `docker-compose.yml`)
- **CI config** (GitHub Actions, GitLab CI, Travis, Jenkins, Azure Pipelines)
- A depth-limited **folder tree**

Uploads are capped at 25 MB total, and zip extraction is guarded against path-traversal
("zip-slip") entries.

## Notes / next steps

- Swap in a different model via the `README_GEN_MODEL` env var.
- The template fallback is intentionally conservative — it never invents dependencies
  or commands it didn't detect, so it's safe to use with no API key at all.
- Vercel isn't the only option — any host that runs a Python ASGI app works
  (Render, Railway, Fly.io, a plain VM with `uvicorn`/`gunicorn`), and the
  frontend has no build step either way.
