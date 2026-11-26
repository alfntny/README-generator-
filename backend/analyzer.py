"""
Static project analyzer.

Walks an extracted project directory and extracts objective facts:
- primary language(s)
- dependency manifests found (package.json, requirements.txt, etc.)
- declared dependencies (top-level, not transitive)
- folder structure (pruned, depth-limited)
- likely entry points
- scripts / commands declared in manifests
- license file, existing README, CI config, docker presence

These facts are handed to the writer module, which either feeds them to
an LLM prompt or renders them with a template fallback.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

# Directories we never want to walk into or report on.
IGNORED_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", "venv", ".venv",
    "env", ".env", "dist", "build", ".next", ".nuxt", "target", "bin",
    "obj", ".idea", ".vscode", ".pytest_cache", ".mypy_cache", "coverage",
    ".tox", "vendor", ".gradle", ".cache",
}

# Extension -> language label. Order doesn't matter; it's a lookup table.
EXT_LANGUAGE = {
    ".py": "Python", ".ipynb": "Jupyter Notebook",
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript",
    ".java": "Java", ".kt": "Kotlin", ".kts": "Kotlin",
    ".go": "Go", ".rs": "Rust", ".rb": "Ruby", ".php": "PHP",
    ".c": "C", ".h": "C", ".cpp": "C++", ".cc": "C++", ".hpp": "C++",
    ".cs": "C#", ".swift": "Swift", ".m": "Objective-C",
    ".scala": "Scala", ".sh": "Shell", ".sql": "SQL",
    ".html": "HTML", ".css": "CSS", ".scss": "SCSS",
    ".vue": "Vue", ".dart": "Dart", ".lua": "Lua", ".r": "R",
}

# Manifest filename -> (ecosystem, parser function name)
MANIFEST_FILES = {
    "package.json": "node",
    "requirements.txt": "pip",
    "pyproject.toml": "pyproject",
    "Pipfile": "pipfile",
    "pom.xml": "maven",
    "build.gradle": "gradle",
    "build.gradle.kts": "gradle",
    "Cargo.toml": "cargo",
    "go.mod": "gomod",
    "Gemfile": "bundler",
    "composer.json": "composer",
    "CMakeLists.txt": "cmake",
}

ENTRY_POINT_CANDIDATES = [
    "main.py", "app.py", "manage.py", "run.py", "server.py", "wsgi.py",
    "asgi.py", "index.js", "index.ts", "server.js", "app.js", "main.js",
    "Main.java", "Program.cs", "main.go", "main.rs",
]

MAX_WALK_FILES = 4000  # safety cap for huge uploads


@dataclass
class ProjectFacts:
    root_name: str
    languages: dict = field(default_factory=dict)       # language -> file count
    manifests: list = field(default_factory=list)       # list of {file, ecosystem, deps, scripts}
    structure: list = field(default_factory=list)       # pruned tree lines
    entry_points: list = field(default_factory=list)
    has_license: bool = False
    license_name: str | None = None
    has_existing_readme: bool = False
    has_docker: bool = False
    has_ci: bool = False
    ci_systems: list = field(default_factory=list)
    total_files: int = 0

    def primary_language(self) -> str | None:
        if not self.languages:
            return None
        return max(self.languages.items(), key=lambda kv: kv[1])[0]

    def to_dict(self) -> dict:
        d = dict(self.__dict__)
        return d


def _safe_read(path: Path, limit: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:limit]
    except Exception:
        return ""


def _parse_node(path: Path) -> dict:
    data = {}
    try:
        data = json.loads(_safe_read(path))
    except Exception:
        return {"deps": [], "scripts": {}, "name": None, "description": None}
    deps = sorted(set(list((data.get("dependencies") or {}).keys())
                       + list((data.get("devDependencies") or {}).keys())))
    return {
        "deps": deps,
        "scripts": data.get("scripts") or {},
        "name": data.get("name"),
        "description": data.get("description"),
    }


def _parse_pip(path: Path) -> dict:
    deps = []
    for line in _safe_read(path).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        name = re.split(r"[=<>~!\[; ]", line)[0].strip()
        if name:
            deps.append(name)
    return {"deps": sorted(set(deps)), "scripts": {}, "name": None, "description": None}


def _parse_pyproject(path: Path) -> dict:
    text = _safe_read(path)
    deps = re.findall(r'^\s*"?([A-Za-z0-9_\-\.]+)"?\s*=\s*["\[]', text, re.MULTILINE)
    name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
    desc_match = re.search(r'^\s*description\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return {
        "deps": sorted(set(d for d in deps if d not in {"python"})),
        "scripts": {},
        "name": name_match.group(1) if name_match else None,
        "description": desc_match.group(1) if desc_match else None,
    }


def _parse_pipfile(path: Path) -> dict:
    text = _safe_read(path)
    section = text.split("[packages]")[-1] if "[packages]" in text else ""
    section = section.split("[dev-packages]")[0]
    deps = re.findall(r'^\s*([A-Za-z0-9_\-\.]+)\s*=', section, re.MULTILINE)
    return {"deps": sorted(set(deps)), "scripts": {}, "name": None, "description": None}


def _parse_maven(path: Path) -> dict:
    text = _safe_read(path)
    deps = re.findall(r"<artifactId>([^<]+)</artifactId>", text)
    return {"deps": sorted(set(deps))[:40], "scripts": {}, "name": None, "description": None}


def _parse_gradle(path: Path) -> dict:
    text = _safe_read(path)
    deps = re.findall(r"""(?:implementation|api|compile|testImplementation)\s*['"]([^'"]+)['"]""", text)
    return {"deps": sorted(set(deps)), "scripts": {}, "name": None, "description": None}


def _parse_cargo(path: Path) -> dict:
    text = _safe_read(path)
    section = text.split("[dependencies]")[-1] if "[dependencies]" in text else ""
    section = re.split(r"\n\[", section)[0]
    deps = re.findall(r'^\s*([A-Za-z0-9_\-]+)\s*=', section, re.MULTILINE)
    name_match = re.search(r'^\s*name\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return {"deps": sorted(set(deps)), "scripts": {}, "name": name_match.group(1) if name_match else None, "description": None}


def _parse_gomod(path: Path) -> dict:
    text = _safe_read(path)
    module_match = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    deps = re.findall(r"^\s+([a-zA-Z0-9\.\-_/]+)\s+v[\d\.]", text, re.MULTILINE)
    return {"deps": sorted(set(deps))[:40], "scripts": {}, "name": module_match.group(1) if module_match else None, "description": None}


def _parse_bundler(path: Path) -> dict:
    text = _safe_read(path)
    deps = re.findall(r"""gem\s+['"]([^'"]+)['"]""", text)
    return {"deps": sorted(set(deps)), "scripts": {}, "name": None, "description": None}


def _parse_composer(path: Path) -> dict:
    try:
        data = json.loads(_safe_read(path))
    except Exception:
        return {"deps": [], "scripts": {}, "name": None, "description": None}
    deps = sorted((data.get("require") or {}).keys())
    return {"deps": deps, "scripts": {}, "name": data.get("name"), "description": data.get("description")}


def _parse_cmake(path: Path) -> dict:
    return {"deps": [], "scripts": {}, "name": None, "description": None}


_PARSERS = {
    "node": _parse_node, "pip": _parse_pip, "pyproject": _parse_pyproject,
    "pipfile": _parse_pipfile, "maven": _parse_maven, "gradle": _parse_gradle,
    "cargo": _parse_cargo, "gomod": _parse_gomod, "bundler": _parse_bundler,
    "composer": _parse_composer, "cmake": _parse_cmake,
}


def analyze_project(root: str | Path) -> ProjectFacts:
    root = Path(root)
    facts = ProjectFacts(root_name=root.name)

    structure_lines = []
    file_count = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d for d in dirnames
            if d not in IGNORED_DIRS and (not d.startswith(".") or d == ".github")
        ]
        rel_dir = Path(dirpath).relative_to(root)
        depth = len(rel_dir.parts)

        if depth <= 2:
            label = "." if str(rel_dir) == "." else str(rel_dir)
            structure_lines.append((depth, label, True))

        for fname in filenames:
            file_count += 1
            if file_count > MAX_WALK_FILES:
                break
            fpath = Path(dirpath) / fname
            ext = fpath.suffix.lower()

            if depth <= 2:
                structure_lines.append((depth + 1, fname, False))

            if ext in EXT_LANGUAGE:
                lang = EXT_LANGUAGE[ext]
                facts.languages[lang] = facts.languages.get(lang, 0) + 1

            if fname in MANIFEST_FILES:
                ecosystem = MANIFEST_FILES[fname]
                parsed = _PARSERS[ecosystem](fpath)
                facts.manifests.append({
                    "file": str(fpath.relative_to(root)),
                    "ecosystem": ecosystem,
                    **parsed,
                })

            if fname in ENTRY_POINT_CANDIDATES:
                facts.entry_points.append(str(fpath.relative_to(root)))

            lower = fname.lower()
            if lower.startswith("license"):
                facts.has_license = True
                text = _safe_read(fpath, 400)
                for lic in ["MIT", "Apache", "GPL", "BSD", "MPL", "ISC", "Unlicense"]:
                    if lic.lower() in text.lower():
                        facts.license_name = lic
                        break
            if lower in {"readme.md", "readme.rst", "readme.txt", "readme"}:
                facts.has_existing_readme = True
            if lower in {"dockerfile", "docker-compose.yml", "docker-compose.yaml"}:
                facts.has_docker = True
            if ".github/workflows" in str(fpath.relative_to(root)).replace("\\", "/"):
                facts.has_ci = True
                facts.ci_systems.append("GitHub Actions")
            if lower in {".gitlab-ci.yml", ".travis.yml", "jenkinsfile", "azure-pipelines.yml"}:
                facts.has_ci = True
                facts.ci_systems.append(fname)

        if file_count > MAX_WALK_FILES:
            break

    structure_lines.sort(key=lambda t: (t[1] != ".",))
    facts.structure = [("  " * d) + ("📁 " if is_dir else "") + name
                        for d, name, is_dir in structure_lines[:200]]
    facts.total_files = file_count
    facts.ci_systems = sorted(set(facts.ci_systems))
    return facts
