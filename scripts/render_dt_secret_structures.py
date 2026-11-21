#!/usr/bin/env python3
"""Render syntax-only context for secret candidates with literals redacted."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "analysis" / "dt_manual_validation_candidates.csv"
OUTPUT = ROOT / "analysis" / "dt_secret_code_structures.txt"


def sanitize(line: str) -> str:
    if "PRIVATE KEY" in line or re.fullmatch(r"\s*[A-Za-z0-9+/=]{32,}\s*", line):
        return "<redacted key material>"
    line = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "<redacted JWT>", line)
    line = re.sub(r"`(?:\\.|[^`])*`", "`<redacted literal>`", line)
    line = re.sub(r'"(?:\\.|[^"\\])*"', '"<redacted literal>"', line)
    line = re.sub(r"'(?:\\.|[^'\\])*'", "'<redacted literal>'", line)
    line = re.sub(r"(?<![A-Za-z0-9_])[A-Za-z0-9_+/-]{24,}(?![A-Za-z0-9_])", "<redacted token>", line)
    return line


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["cwe"] == "CWE-798"]
    seen: set[tuple[str, str, str]] = set()
    blocks = []
    for row in rows:
        key = (row["repository_id"], row["file_path"], row["line_number"])
        if key in seen:
            continue
        seen.add(key)
        source = ROOT / "workspace" / row["run_id"] / "repo" / row["file_path"]
        number = int(row["line_number"] or 0)
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, number - 4)
        end = min(len(lines), number + 4)
        rendered = [
            f"{line_no:6d}{'>' if line_no == number else ' '} {sanitize(lines[line_no - 1])}"
            for line_no in range(start, end + 1)
        ]
        blocks.append(
            f"[{row['finding_id']}] {row['repository_id']} {row['rule_id']}\n"
            f"path={row['file_path']} line={number}\n" + "\n".join(rendered)
        )
    OUTPUT.write_text("\n\n".join(blocks) + "\n", encoding="utf-8")
    print(f"output={OUTPUT}")
    print(f"unique_contexts={len(seen)}")


if __name__ == "__main__":
    main()
