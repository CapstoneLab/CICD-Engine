#!/usr/bin/env python3
"""Collect repository size, language, type, and lineage metadata at fixed commits."""

from __future__ import annotations

import csv
import json
import subprocess
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPECS = (
    ("DT1", "run-20260723-002", "sample_application", "Azure-DT-sample"),
    ("DT2", "run-20260723-004", "demo_application", "Autodesk-DT-demo"),
    ("DT3", "run-20260723-003", "demo_application", "Autodesk-DT-demo"),
    ("DT4", "run-20260723-005", "platform", "DTaaS"),
    ("DT5", "run-20260723-014", "core_library_monorepo", "iTwin"),
    ("DT6", "run-20260723-013", "component_library_monorepo", "iTwin"),
    ("DT7", "run-20260723-006", "demo_application", "Vertex-demo"),
    ("DT8", "run-20260723-007", "demo_application", "Vertex-demo"),
    ("DT9", "run-20260723-008", "demo_application", "Vertex-demo"),
    ("DT10", "run-20260723-011", "iot_platform_monorepo", "OpenRemote"),
    ("DT11", "run-20260723-012", "research_application", "GeoTwin"),
    ("DT12", "run-20260723-015", "research_application", "NUS-DT"),
    ("DT13", "run-20260723-009", "starter_application", "Water-DT"),
    ("DT14", "run-20260723-010", "editor_platform_monorepo", "Meteor3D"),
)
LANGUAGE = {
    ".js": "JavaScript", ".jsx": "JavaScript", ".mjs": "JavaScript", ".cjs": "JavaScript",
    ".ts": "TypeScript", ".tsx": "TypeScript", ".py": "Python", ".java": "Java",
    ".cs": "C#", ".go": "Go", ".rs": "Rust", ".cpp": "C/C++", ".cc": "C/C++",
    ".c": "C/C++", ".h": "C/C++", ".hpp": "C/C++", ".vue": "Vue",
    ".html": "HTML", ".htm": "HTML", ".css": "CSS", ".scss": "CSS", ".less": "CSS",
    ".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".xml": "XML",
    ".gradle": "Gradle", ".kt": "Kotlin", ".kts": "Kotlin", ".sh": "Shell",
    ".ps1": "PowerShell", ".rb": "Ruby", ".php": "PHP", ".sql": "SQL",
}
LOCK_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "cargo.lock"}
PROGRAMMING_LANGUAGES = {
    "JavaScript", "TypeScript", "Python", "Java", "C#", "Go", "Rust",
    "C/C++", "Vue", "HTML", "CSS", "Gradle", "Kotlin", "Shell",
    "PowerShell", "Ruby", "PHP", "SQL",
}


def is_generated(path: str, head: str) -> bool:
    lower = path.lower()
    parts = set(Path(lower).parts)
    return (
        Path(lower).name in LOCK_NAMES
        or ".min." in lower
        or bool(parts & {"dist", "build", "coverage", "generated", "vendor"})
        or "@generated" in head.lower()
        or "generated file" in head.lower()
        or lower.endswith("common/scripts/install-run.js")
    )


def main() -> None:
    rows: list[dict[str, object]] = []
    for label, run_id, repo_type, lineage in SPECS:
        repo = ROOT / "workspace" / run_id / "repo"
        run = ROOT / "runs" / run_id
        pipeline = json.loads((run / "pipeline_result.json").read_text())
        verdict = json.loads((run / "security_verdict.json").read_text())
        semgrep = json.loads((run / "semgrep_report.json").read_text())
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=repo, check=True, capture_output=True
        ).stdout.split(b"\0")
        tracked_count = sum(bool(item) for item in tracked)
        scanned = [
            str(path) for path in semgrep.get("paths", {}).get("scanned", [])
            if str(path) != ".localci/workflow.yml"
        ]
        language_loc: Counter[str] = Counter()
        generated_loc = generated_files = text_files = physical_nonblank = 0
        for relative in scanned:
            path = repo / relative
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            nonblank = sum(bool(line.strip()) for line in text.splitlines())
            if not nonblank:
                continue
            text_files += 1
            physical_nonblank += nonblank
            language_loc[LANGUAGE.get(path.suffix.lower(), "Other")] += nonblank
            if is_generated(relative, "\n".join(text.splitlines()[:10])):
                generated_files += 1
                generated_loc += nonblank
        top_languages = "; ".join(
            f"{language}:{loc}" for language, loc in language_loc.most_common(4)
        )
        programming = Counter({
            language: loc for language, loc in language_loc.items()
            if language in PROGRAMMING_LANGUAGES
        })
        programming_loc = sum(programming.values())
        top_programming_languages = "; ".join(
            f"{language}:{loc}" for language, loc in programming.most_common(4)
        )
        owner = pipeline["repo_url"].rstrip("/").split("/")[-2]
        rows.append({
            "repository_id": label,
            "run_id": run_id,
            "repository_url": pipeline["repo_url"],
            "fork_owner": owner,
            "full_commit_sha": verdict["scanned_commit_sha"],
            "repository_type": repo_type,
            "code_lineage_cluster": lineage,
            "tracked_files": tracked_count,
            "semgrep_scanned_files": len(scanned),
            "scanned_text_files": text_files,
            "physical_nonblank_loc": physical_nonblank,
            "programming_nonblank_loc": programming_loc,
            "generated_flagged_files": generated_files,
            "generated_flagged_loc": generated_loc,
            "top_languages_by_nonblank_loc": top_languages,
            "top_programming_languages": top_programming_languages,
        })

    out_csv = ROOT / "analysis/dt_repository_metadata.csv"
    out_json = ROOT / "analysis/dt_repository_metadata.json"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"csv={out_csv}")
    print(f"json={out_json}")
    for row in rows:
        print("|".join(str(row[key]) for key in (
            "repository_id", "repository_type", "code_lineage_cluster", "tracked_files",
            "semgrep_scanned_files", "physical_nonblank_loc", "generated_flagged_loc",
            "programming_nonblank_loc", "top_programming_languages",
        )))


if __name__ == "__main__":
    main()
