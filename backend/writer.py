"""
README writer.

Two entry points:
  - write_from_prompt(prompt)                 -> markdown
  - write_from_facts(facts: ProjectFacts, extra_prompt="") -> markdown

Both try an LLM (Anthropic API) first if ANTHROPIC_API_KEY is set in the
environment, and fall back to a deterministic template renderer otherwise.
The template path means the app is fully usable with zero API keys and zero
external cost -- the LLM path just makes the prose nicer.
"""

from __future__ import annotations

import os
import re
from .analyzer import ProjectFacts
from .textmine import extract_features, extract_prereq_hints, extract_tech_stack

ANTHROPIC_MODEL = os.environ.get("README_GEN_MODEL", "claude-sonnet-4-5")


def _get_anthropic_client():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    try:
        import anthropic  # type: ignore
    except ImportError:
        return None
    return anthropic.Anthropic(api_key=api_key)


def _llm_complete(system: str, user: str) -> str | None:
    client = _get_anthropic_client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return "".join(block.text for block in resp.content if hasattr(block, "text")).strip()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Prompt-only mode
# ---------------------------------------------------------------------------

_PROMPT_SYSTEM = (
    "You write detailed, polished, professional GitHub README.md files in "
    "Markdown -- the kind a well-maintained open-source project would have, "
    "not a bare-bones stub. Given a short description of a project, produce "
    "a complete README with, in this order: a title; a row of shields.io "
    "badges plausible for the stack described (license badge defaulting to "
    "MIT unless told otherwise, a badge per major language/framework "
    "mentioned); a one-line tagline; a Table of Contents (anchor links to "
    "every section below); a Overview section (2-4 sentences, more detail "
    "than the prompt alone -- elaborate sensibly on what the project does "
    "and who it's for); a Features section (5-8 bulleted, specific features, "
    "inferred and elaborated from the description, not generic filler); a "
    "Tech Stack section (bulleted, grouped by frontend/backend/database/etc. "
    "when that distinction makes sense); a Prerequisites section (plausible "
    "runtime/tooling versions needed); an Installation section with "
    "numbered, copy-pasteable steps; a Usage section with at least one "
    "concrete code example; a Configuration section if the stack implies "
    "environment variables or config files (use italic placeholders for "
    "unknown values); a Contributing section (short, standard boilerplate: "
    "fork, branch, PR); a Roadmap section (3-5 bulleted checkbox items for "
    "plausible next features); a License section; and an Acknowledgments "
    "section if relevant tools/libraries were named. "
    "Do not invent specific repo URLs, author names, or real version numbers "
    "you were not given -- use italic placeholders like _your-username_ "
    "instead. Output ONLY the markdown, no commentary before or after."
)


def write_from_prompt(prompt: str) -> str:
    llm_result = _llm_complete(_PROMPT_SYSTEM, prompt)
    if llm_result:
        return llm_result
    return _template_from_prompt(prompt)


def _template_from_prompt(prompt: str) -> str:
    title = _guess_title(prompt)
    slug = _slug(title)
    tagline = prompt.strip().splitlines()[0]
    if len(tagline) > 120:
        tagline = tagline[:117].rstrip() + "..."

    tech_found = extract_tech_stack(prompt)
    badges = " ".join(
        [_badge(name, "", color, logo=logo) for name, (color, logo) in list(tech_found.items())[:4]]
        + [_badge("license", "MIT", "green")]
    )

    features = extract_features(prompt)
    if not features:
        features = [
            "_Add your key features here_",
            "_What makes it different from similar projects?_",
            "_What's the core workflow a user goes through?_",
        ]

    tech_lines = [f"- **{name}**" for name in tech_found] if tech_found else [
        "- _List your languages, frameworks, and major libraries here_",
    ]

    prereqs = extract_prereq_hints(prompt) or ["_Runtime(s) needed, e.g. Python 3.10+, Node.js 18+_"]

    return f"""# {title}

{badges}

> {tagline}

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [Roadmap](#roadmap)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Overview

{prompt.strip()}

## Features

{chr(10).join('- ' + f for f in features)}

## Tech Stack

{chr(10).join(tech_lines)}

## Prerequisites

{chr(10).join('- ' + p for p in prereqs)}

## Installation

```bash
git clone https://github.com/your-username/{slug}.git
cd {slug}

# install dependencies, e.g.:
# pip install -r requirements.txt
# or
# npm install
```

## Usage

```bash
# example command to run the project
```

_Add a short example of typical input/output or a screenshot here._

## Configuration

_List any environment variables or config files your project needs, e.g.:_

```
API_KEY=your-key-here
```

## Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m "Add your feature"`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

## Roadmap

- [ ] _Next feature or improvement_
- [ ] _Another planned addition_
- [ ] _Something you'd like help with_

## License

This project is licensed under the MIT License. See the [LICENSE](LICENSE) file for details.

## Acknowledgments

{('- Built with ' + ', '.join(list(tech_found.keys())[:6])) if tech_found else '- _Credit any libraries, tutorials, or inspiration here_'}
"""


def _badge(label: str, value: str, color: str, logo: str | None = None) -> str:
    text = f"{label}-{value}" if value else label
    url = f"https://img.shields.io/badge/{text.replace(' ', '%20')}-{color}.svg"
    if logo:
        url += f"?logo={logo}&logoColor=white"
    return f"![{label}]({url})"


def _guess_title(prompt: str) -> str:
    first_line = prompt.strip().splitlines()[0] if prompt.strip() else "Project"
    words = first_line.split()
    return " ".join(w.capitalize() for w in words[:6]) if words else "Project"


def _slug(text: str) -> str:
    return "-".join(text.lower().split())


# ---------------------------------------------------------------------------
# Upload / static-analysis mode
# ---------------------------------------------------------------------------

_FACTS_SYSTEM = (
    "You write detailed, polished, professional GitHub README.md files in "
    "Markdown from a structured fact-sheet about a real codebase -- the kind "
    "of thorough README a well-maintained open-source project would have, "
    "not a bare-bones stub. Use ONLY the facts given to make factual claims "
    "-- never invent dependencies, commands, or features that aren't implied "
    "by the facts. Where elaboration is reasonable (e.g. describing likely "
    "use cases, writing a Contributing section, a Roadmap of plausible next "
    "steps), clearly generic/illustrative content is fine, but keep it "
    "clearly in that register rather than stated as fact. If something "
    "concrete is unknown (like a precise entry command), write a sensible "
    "generic placeholder in italics rather than inventing specifics. "
    "Sections, in this order: title (infer a reasonable name from the root "
    "folder name if nothing better is available); a row of shields.io "
    "badges for the detected primary language(s), license (or 'unlicensed' "
    "if none found), and CI status if detected; a one-line tagline; a Table "
    "of Contents (anchor links to every section below); an Overview section "
    "(3-5 sentences synthesizing what the project likely does and who it's "
    "for, from its structure, languages and dependencies -- more than one "
    "throwaway line); Features (5-8 bulleted, inferred conservatively from "
    "the detected stack, Docker/CI presence, etc.); Tech Stack (from the "
    "languages/manifests given, grouped sensibly); Project Structure (use "
    "the provided tree, trimmed if long); Prerequisites (runtime versions "
    "implied by the manifests, e.g. 'Python 3.10+' if requirements.txt was "
    "found); Installation (derive real commands from the manifests given, "
    "e.g. pip install -r requirements.txt, npm install, numbered steps); "
    "Usage (use any detected entry point for a real run command); "
    "Configuration (only if Docker/env-like files were detected -- otherwise "
    "a short italic placeholder); Contributing (short standard boilerplate: "
    "fork, branch, PR); Roadmap (3-5 bulleted checkbox items, plausible "
    "next steps, clearly illustrative); License (use the detected license "
    "name, or say 'No license file detected' and suggest adding one); and "
    "Acknowledgments (credit any notable detected dependencies/frameworks). "
    "Output ONLY the markdown, no commentary before or after."
)


def write_from_facts(facts: ProjectFacts, extra_prompt: str = "") -> str:
    facts_blob = _facts_to_text(facts)
    user_msg = facts_blob
    if extra_prompt.strip():
        user_msg += f"\n\nAdditional context from the user:\n{extra_prompt.strip()}"

    llm_result = _llm_complete(_FACTS_SYSTEM, user_msg)
    if llm_result:
        return llm_result
    return _template_from_facts(facts, extra_prompt)


def _facts_to_text(facts: ProjectFacts) -> str:
    lines = [f"Project root folder name: {facts.root_name}", f"Total files scanned: {facts.total_files}"]

    if facts.languages:
        langs = ", ".join(f"{lang} ({count} files)" for lang, count in
                           sorted(facts.languages.items(), key=lambda kv: -kv[1]))
        lines.append(f"Languages detected: {langs}")

    if facts.manifests:
        lines.append("Dependency manifests found:")
        for m in facts.manifests:
            dep_list = ", ".join(m["deps"][:25]) if m["deps"] else "(none declared)"
            lines.append(f"  - {m['file']} [{m['ecosystem']}]: {dep_list}")
            if m.get("scripts"):
                lines.append(f"    scripts: {m['scripts']}")
            if m.get("name"):
                lines.append(f"    declared name: {m['name']}")
            if m.get("description"):
                lines.append(f"    declared description: {m['description']}")

    if facts.entry_points:
        lines.append(f"Likely entry points: {', '.join(facts.entry_points)}")

    lines.append(f"Has LICENSE file: {facts.has_license}" + (f" ({facts.license_name})" if facts.license_name else ""))
    lines.append(f"Has existing README: {facts.has_existing_readme}")
    lines.append(f"Has Dockerfile/compose: {facts.has_docker}")
    lines.append(f"Has CI config: {facts.has_ci}" + (f" ({', '.join(facts.ci_systems)})" if facts.ci_systems else ""))

    if facts.structure:
        lines.append("Folder structure (partial, depth-limited):")
        lines.extend(facts.structure[:120])

    return "\n".join(lines)


_INSTALL_COMMANDS = {
    "node": "npm install",
    "pip": "pip install -r requirements.txt",
    "pyproject": "pip install .",
    "pipfile": "pipenv install",
    "maven": "mvn install",
    "gradle": "./gradlew build",
    "cargo": "cargo build",
    "gomod": "go build ./...",
    "bundler": "bundle install",
    "composer": "composer install",
    "cmake": "cmake . && make",
}

_RUN_HINTS = {
    "node": "node {entry}",
    "pip": "python {entry}",
    "pyproject": "python {entry}",
    "pipfile": "python {entry}",
}


_LANGUAGE_BADGE_COLORS = {
    "Python": ("3776AB", "python"), "JavaScript": ("F7DF1E", "javascript"),
    "TypeScript": ("3178C6", "typescript"), "Java": ("007396", "java"),
    "Go": ("00ADD8", "go"), "Rust": ("000000", "rust"), "Ruby": ("CC342D", "ruby"),
    "PHP": ("777BB4", "php"), "C++": ("00599C", "cplusplus"), "C": ("A8B9CC", "c"),
    "C#": ("239120", "csharp"), "Kotlin": ("7F52FF", "kotlin"), "Swift": ("FA7343", "swift"),
    "HTML": ("E34F26", "html5"), "CSS": ("1572B6", "css3"), "SQL": ("4479A1", "postgresql"),
}


def _template_from_facts(facts: ProjectFacts, extra_prompt: str = "") -> str:
    title = " ".join(w.capitalize() for w in re_split_name(facts.root_name))
    slug = _slug(title)
    primary_lang = facts.primary_language() or "code"
    top_langs = [lang for lang, _ in sorted(facts.languages.items(), key=lambda kv: -kv[1])[:3]]

    # --- badges ---
    badges = []
    for lang in top_langs[:2]:
        color, logo = _LANGUAGE_BADGE_COLORS.get(lang, ("555555", None))
        badges.append(_badge(lang, "", color, logo=logo))
    if facts.license_name:
        badges.append(_badge("license", facts.license_name, "green"))
    else:
        badges.append(_badge("license", "unlicensed", "lightgrey"))
    if facts.has_ci:
        badges.append(_badge("CI", "passing", "brightgreen"))
    if facts.has_docker:
        badges.append(_badge("Docker", "ready", "2496ED", logo="docker"))

    # --- overview ---
    manifest_bit = f" with {len(facts.manifests)} dependency manifest(s) detected" if facts.manifests else ""
    key_deps = []
    for m in facts.manifests:
        key_deps.extend(m["deps"][:5])
    deps_bit = f" Notable dependencies include {', '.join(sorted(set(key_deps))[:6])}." if key_deps else ""
    overview_default = (
        f"{title} is a {primary_lang} project{manifest_bit}.{deps_bit} "
        f"_Edit this overview with more detail: what does {title} actually do, and who is it for?_"
    )
    overview = f"{extra_prompt.strip()}\n\n{overview_default}" if extra_prompt.strip() else overview_default

    # --- features --- (mine the user's own context text first -- real
    # content beats generic placeholders -- then add what static analysis
    # itself can vouch for)
    features = extract_features(extra_prompt) if extra_prompt.strip() else []
    if facts.manifests:
        features.append(f"Built on {', '.join(top_langs) if top_langs else primary_lang}")
    if facts.has_docker:
        features.append("Containerized with Docker for consistent local/deployed environments")
    if facts.has_ci:
        features.append(f"Continuous integration configured via {', '.join(facts.ci_systems)}")
    if facts.entry_points:
        features.append(f"Clear entry point (`{facts.entry_points[0]}`) to get running quickly")
    if len(facts.manifests) > 1:
        features.append("Multi-component project spanning more than one dependency ecosystem")
    if not features:
        features = [
            "_Add the features that actually matter to a user here_",
            "_What problem does this solve, and what makes it different?_",
        ]

    # --- tech stack --- (facts from the code itself, plus anything named
    # in the user's context text that the analyzer wouldn't see, e.g. a
    # hardware/ML library mentioned only in prose)
    tech_stack_lines = []
    if facts.languages:
        for lang, count in sorted(facts.languages.items(), key=lambda kv: -kv[1]):
            tech_stack_lines.append(f"- **{lang}** ({count} file{'s' if count != 1 else ''})")
    for m in facts.manifests:
        if m["deps"]:
            tech_stack_lines.append(f"- Key {m['ecosystem']} dependencies: " + ", ".join(m["deps"][:10]))
    if facts.has_docker:
        tech_stack_lines.append("- Docker for containerization")
    if facts.has_ci:
        tech_stack_lines.append(f"- {', '.join(facts.ci_systems)} for CI")
    if extra_prompt.strip():
        mentioned_only = {
            name for name in extract_tech_stack(extra_prompt)
            if name not in top_langs and name.lower() not in " ".join(tech_stack_lines).lower()
        }
        if mentioned_only:
            tech_stack_lines.append("- Also mentioned: " + ", ".join(sorted(mentioned_only)))
    if not tech_stack_lines:
        tech_stack_lines = ["- _Not clearly detected from the uploaded files_"]

    # --- prerequisites ---
    prereqs = []
    for m in facts.manifests:
        hint = _PREREQ_HINTS.get(m["ecosystem"])
        if hint and hint not in prereqs:
            prereqs.append(hint)
    if facts.has_docker:
        prereqs.append("Docker (if you'd rather run it containerized)")
    if extra_prompt.strip():
        for hint in extract_prereq_hints(extra_prompt):
            if hint not in prereqs:
                prereqs.append(hint)
    if not prereqs:
        prereqs.append("_List any runtimes or tools a user needs installed first_")

    # --- installation ---
    install_steps = ["git clone <repo-url>", f"cd {facts.root_name}"]
    for m in facts.manifests:
        cmd = _INSTALL_COMMANDS.get(m["ecosystem"])
        if cmd:
            install_steps.append(cmd)

    # --- usage ---
    usage_cmd = None
    if facts.entry_points:
        entry = facts.entry_points[0]
        for m in facts.manifests:
            hint = _RUN_HINTS.get(m["ecosystem"])
            if hint:
                usage_cmd = hint.format(entry=entry)
                break
        if not usage_cmd:
            usage_cmd = f"# run {entry}"

    structure_block = "\n".join(facts.structure[:60]) if facts.structure else "_(structure unavailable)_"

    license_section = (
        f"This project is licensed under the {facts.license_name} License. "
        "See the [LICENSE](LICENSE) file for details."
        if facts.license_name else
        "_No license file detected. Consider adding a LICENSE file so others know how they can use this._"
    )

    config_section = (
        "This project uses Docker; see `Dockerfile`" +
        (" and `docker-compose.yml`" if any("compose" in str(s) for s in facts.structure) else "") +
        " for environment configuration."
        if facts.has_docker else
        "_List any environment variables or config files this project needs, e.g.:_\n\n```\nAPI_KEY=your-key-here\n```"
    )

    acknowledgments = []
    for m in facts.manifests:
        acknowledgments.extend(m["deps"][:3])
    ack_line = (
        "Thanks to the maintainers of " + ", ".join(sorted(set(acknowledgments))[:6]) + "."
        if acknowledgments else "_Credit any libraries, tutorials, or inspiration here_"
    )

    return f"""# {title}

{' '.join(badges)}

> {title} — {primary_lang} project{manifest_bit}.

## Table of Contents

- [Overview](#overview)
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Prerequisites](#prerequisites)
- [Installation](#installation)
- [Usage](#usage)
- [Configuration](#configuration)
- [Contributing](#contributing)
- [Roadmap](#roadmap)
- [License](#license)
- [Acknowledgments](#acknowledgments)

## Overview

{overview}

## Features

{chr(10).join('- ' + f for f in features)}

## Tech Stack

{chr(10).join(tech_stack_lines) if tech_stack_lines else '- _Not clearly detected from the uploaded files_'}

## Project Structure

```
{structure_block}
```

## Prerequisites

{chr(10).join('- ' + p for p in prereqs)}

## Installation

```bash
{chr(10).join(install_steps)}
```

## Usage

```bash
{usage_cmd or '# add the command used to run this project'}
```

## Configuration

{config_section}

## Contributing

Contributions are welcome!

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -m "Add your feature"`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

## Roadmap

- [ ] _Next feature or improvement_
- [ ] _Another planned addition_
- [ ] _Something you'd like help with_

## License

{license_section}

## Acknowledgments

{ack_line}
"""


_PREREQ_HINTS = {
    "node": "Node.js (see package.json for version constraints)",
    "pip": "Python 3.x",
    "pyproject": "Python 3.x",
    "pipfile": "Python 3.x + pipenv",
    "maven": "Java + Maven",
    "gradle": "Java + Gradle",
    "cargo": "Rust (via rustup)",
    "gomod": "Go",
    "bundler": "Ruby + Bundler",
    "composer": "PHP + Composer",
    "cmake": "CMake + a C/C++ toolchain",
}


def re_split_name(name: str) -> list[str]:
    import re
    return [p for p in re.split(r"[-_\s]+", name) if p] or [name]
