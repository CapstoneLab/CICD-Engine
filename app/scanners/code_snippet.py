from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import SecurityFinding


CONTEXT_LINES = 28
MASK = "****"


def enrich_with_code_snippets(
    findings: list["SecurityFinding"],
    repo_dir: Path,
    gitleaks_report: Path | None = None,
) -> None:
    secret_matches = _load_gitleaks_matches(gitleaks_report) if gitleaks_report else {}

    for finding in findings:
        if not finding.file_path or finding.line_number <= 0:
            continue
        snippet, start_line = _read_snippet(repo_dir, finding.file_path, finding.line_number)
        if snippet is None or start_line is None:
            continue

        if finding.scanner_name == "gitleaks":
            secret_value = secret_matches.get(
                _gitleaks_key(finding.file_path, finding.line_number)
            )
            if secret_value:
                snippet = snippet.replace(secret_value, MASK)

        finding.code_snippet = snippet
        finding.code_snippet_start_line = start_line


def _read_snippet(
    repo_dir: Path,
    file_path: str,
    line_number: int,
) -> tuple[str | None, int | None]:
    try:
        candidate = (repo_dir / file_path).resolve()
        repo_root = repo_dir.resolve()
        if not candidate.is_relative_to(repo_root):
            return None, None
        if not candidate.exists() or not candidate.is_file():
            return None, None
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None, None

    lines = text.splitlines()
    if not lines:
        return None, None

    target_index = max(0, line_number - 1)
    start_index = max(0, target_index - CONTEXT_LINES)
    end_index = min(len(lines), target_index + CONTEXT_LINES + 1)
    snippet = "\n".join(lines[start_index:end_index])
    return snippet, start_index + 1


def format_snippet_for_log(snippet: str, start_line: int) -> str:
    one_line = snippet.replace("\\", "\\\\").replace("\n", "\\n")
    return f"start_line={start_line} | {one_line}"


def _load_gitleaks_matches(report_file: Path) -> dict[str, str]:
    if not report_file or not report_file.exists():
        return {}
    try:
        data = json.loads(report_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, list):
        return {}
    matches: dict[str, str] = {}
    for item in data:
        if not isinstance(item, dict):
            continue
        file_path = str(item.get("File", ""))
        line_number = int(item.get("StartLine", item.get("Line", 0)) or 0)
        secret = str(item.get("Match", "") or item.get("Secret", "") or "")
        if not file_path or line_number <= 0 or not secret:
            continue
        matches[_gitleaks_key(file_path, line_number)] = secret
    return matches


def _gitleaks_key(file_path: str, line_number: int) -> str:
    return f"{file_path}::{line_number}"
