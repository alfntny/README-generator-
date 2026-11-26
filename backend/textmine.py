"""
Lightweight, free, no-LLM text mining for the prompt-mode README fallback.

Given the free-text description a user types ("A virtual mouse system that
lets you control your cursor with hand gestures... built with Python,
OpenCV, MediaPipe..."), this pulls out:

  - extract_tech_stack(text)   -> {display_name: (color, logo)}  for a known
                                   tech keyword dictionary
  - extract_features(text)     -> list[str] of feature-ish bullet points,
                                   derived from the sentences themselves
  - extract_prereq_hints(text) -> list[str] of plausible prerequisites
                                   (runtimes implied by the tech found, plus
                                   hardware like "a webcam" if mentioned)

None of this is an LLM call -- it's regex/keyword matching over the prompt
text, so it's free and deterministic, but it only surfaces what's already
written in the prompt. It won't invent anything the user didn't say.
"""

from __future__ import annotations

import re

# display name -> (shields.io color, shields.io logo slug or None)
TECH_KEYWORDS: dict[str, tuple[str, str, str | None]] = {
    "node.js": ("Node.js", "339933", "nodedotjs"),
    "node": ("Node.js", "339933", "nodedotjs"),
    "next.js": ("Next.js", "000000", "nextdotjs"),
    "react": ("React", "61DAFB", "react"),
    "vue": ("Vue.js", "4FC08D", "vuedotjs"),
    "angular": ("Angular", "DD0031", "angular"),
    "express": ("Express", "000000", "express"),
    "flask": ("Flask", "000000", "flask"),
    "django": ("Django", "092E20", "django"),
    "fastapi": ("FastAPI", "009688", "fastapi"),
    "python": ("Python", "3776AB", "python"),
    "javascript": ("JavaScript", "F7DF1E", "javascript"),
    "typescript": ("TypeScript", "3178C6", "typescript"),
    "java": ("Java", "007396", "java"),
    "kotlin": ("Kotlin", "7F52FF", "kotlin"),
    "swift": ("Swift", "FA7343", "swift"),
    "c++": ("C++", "00599C", "cplusplus"),
    "c#": ("C#", "239120", "csharp"),
    "go": ("Go", "00ADD8", "go"),
    "rust": ("Rust", "000000", "rust"),
    "sqlite": ("SQLite", "003B57", "sqlite"),
    "postgresql": ("PostgreSQL", "4169E1", "postgresql"),
    "postgres": ("PostgreSQL", "4169E1", "postgresql"),
    "mysql": ("MySQL", "4479A1", "mysql"),
    "mongodb": ("MongoDB", "47A248", "mongodb"),
    "redis": ("Redis", "DC382D", "redis"),
    "docker": ("Docker", "2496ED", "docker"),
    "kubernetes": ("Kubernetes", "326CE5", "kubernetes"),
    "tensorflow": ("TensorFlow", "FF6F00", "tensorflow"),
    "pytorch": ("PyTorch", "EE4C2C", "pytorch"),
    "scikit-learn": ("scikit-learn", "F7931E", "scikitlearn"),
    "opencv": ("OpenCV", "5C3EE8", "opencv"),
    "mediapipe": ("MediaPipe", "0097A7", None),
    "chart.js": ("Chart.js", "FF6384", "chartdotjs"),
    "bootstrap": ("Bootstrap", "7952B3", "bootstrap"),
    "tailwind": ("Tailwind CSS", "06B6D4", "tailwindcss"),
    "html": ("HTML5", "E34F26", "html5"),
    "css": ("CSS3", "1572B6", "css3"),
    "graphql": ("GraphQL", "E10098", "graphql"),
    "aws": ("AWS", "232F3E", "amazonaws"),
    "firebase": ("Firebase", "FFCA28", "firebase"),
    "pandas": ("Pandas", "150458", "pandas"),
    "numpy": ("NumPy", "013243", "numpy"),
    "keras": ("Keras", "D00000", "keras"),
    "jupyter": ("Jupyter", "F37626", "jupyter"),
    "streamlit": ("Streamlit", "FF4B4B", "streamlit"),
    "gradio": ("Gradio", "FF7C00", None),
    "yolo": ("YOLO", "111111", None),
    "selenium": ("Selenium", "43B02A", "selenium"),
    "sql": ("SQL", "4479A1", "postgresql"),
    "nltk": ("NLTK", "154F5C", None),
    "spacy": ("spaCy", "09A3D5", None),
}

# keyword -> prerequisite line (checked independently of TECH_KEYWORDS,
# since these describe runtimes/hardware, not "tech stack" items)
_PREREQ_KEYWORDS = [
    ("python", "Python 3.9+"),
    ("node", "Node.js 18+"),
    ("docker", "Docker"),
    ("webcam", "A webcam (for video capture)"),
    ("camera", "A camera"),
    ("microphone", "A microphone"),
    ("gpu", "A CUDA-capable GPU (recommended for faster inference)"),
    ("cuda", "A CUDA-capable GPU"),
    ("arduino", "An Arduino board"),
    ("raspberry pi", "A Raspberry Pi"),
]

_STOPWORD_START = re.compile(
    r"^(built with|built using|uses|using|made with|written in)\b", re.IGNORECASE
)


def extract_tech_stack(text: str) -> dict[str, tuple[str, str | None]]:
    """Return {display_name: (color, logo)} for every known tech keyword
    found in the text, longest keyword first so 'node.js' wins over 'node'."""
    lower = text.lower()
    found: dict[str, tuple[str, str | None]] = {}
    for kw in sorted(TECH_KEYWORDS, key=len, reverse=True):
        name, color, logo = TECH_KEYWORDS[kw]
        if name in found:
            continue
        pattern = r"(?<![a-z0-9])" + re.escape(kw) + r"(?![a-z0-9])"
        if re.search(pattern, lower):
            found[name] = (color, logo)
    return found


def extract_prereq_hints(text: str) -> list[str]:
    lower = text.lower()
    hints = []
    for kw, hint in _PREREQ_KEYWORDS:
        if kw in lower and hint not in hints:
            hints.append(hint)
    return hints


def extract_features(text: str, max_features: int = 8) -> list[str]:
    """Turn the free-text description into feature-ish bullets by splitting
    on sentence boundaries and then on top-level conjunctions, rather than
    handing back generic placeholders. Best-effort, not real NLP."""
    text = text.strip()
    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)
    clauses: list[str] = []
    for sentence in sentences:
        sentence = sentence.strip()
        if not sentence:
            continue
        # Break compound sentences on top-level conjunctions/semicolons so
        # "Tracks the finger to move the cursor, and uses pinches to click"
        # becomes two bullets instead of one run-on.
        parts = re.split(r";\s+|,\s+and\s+|\s+and\s+(?=\w+s\b)", sentence)
        for part in parts:
            part = part.strip(" .")
            if part:
                clauses.append(part)

    cleaned = []
    seen = set()
    for clause in clauses:
        clause = _STOPWORD_START.sub("", clause).strip(" ,")
        if len(clause) < 12:
            continue
        clause = clause[0].upper() + clause[1:]
        key = clause.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(clause)

    return cleaned[:max_features]
