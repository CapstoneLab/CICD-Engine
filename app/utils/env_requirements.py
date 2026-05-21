from __future__ import annotations

import os
import re
from pathlib import Path

ENV_EXAMPLE_FILES = (
    ".env.example",
    ".env.local.example",
    ".env.sample",
    ".env.template",
    "env.example",
    "env.sample",
)

_LINE_PATTERN = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env_example(path: Path) -> set[str]:
    keys: set[str] = set()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return keys

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        match = _LINE_PATTERN.match(line)
        if match:
            keys.add(match.group(1))
    return keys


def collect_required_env_keys(repo_dir: Path) -> tuple[set[str], list[Path]]:
    required: set[str] = set()
    found_files: list[Path] = []
    for filename in ENV_EXAMPLE_FILES:
        candidate = repo_dir / filename
        if candidate.exists() and candidate.is_file():
            keys = parse_env_example(candidate)
            if keys:
                required.update(keys)
                found_files.append(candidate)
    return required, found_files


def find_missing_env_keys(repo_dir: Path) -> tuple[list[str], list[Path]]:
    required, source_files = collect_required_env_keys(repo_dir)
    if not required:
        return [], source_files
    provided = set(os.environ.keys())
    missing = sorted(required - provided)
    return missing, source_files
