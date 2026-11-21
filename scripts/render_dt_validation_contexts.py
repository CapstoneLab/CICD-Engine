#!/usr/bin/env python3
"""Render source context for manual validation without disclosing secrets."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "analysis" / "dt_manual_validation_candidates.csv"
OUTPUT = ROOT / "analysis" / "dt_manual_validation_contexts.txt"


def secret_shape(line: str) -> str:
    stripped = line.strip()
    if re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", stripped):
        return "<JWT redacted>"
    if re.search(r"BEGIN [A-Z ]*PRIVATE KEY", stripped):
        return "<private-key PEM marker>"
    if re.search(r"END [A-Z ]*PRIVATE KEY", stripped):
        return "<private-key PEM end marker>"
    left_match = re.match(r"([^:=]{1,100})\s*[:=]", stripped)
    if left_match:
        return f"{left_match.group(1).strip()} = <redacted>"
    words = re.findall(r"[A-Za-z_][A-Za-z0-9_.-]{2,}", stripped)
    safe = [
        word
        for word in words
        if len(word) < 16 and "." not in word and "_" not in word
    ]
    return " ".join(safe[:6]) + (" <redacted>" if stripped else "")


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    sections: list[str] = []
    for row in rows:
        source = ROOT / "workspace" / row["run_id"] / "repo" / row["file_path"]
        line_number = int(row["line_number"] or 0)
        header = (
            f"[{row['finding_id']}] {row['repository_id']} {row['policy_severity']} "
            f"{row['cwe']} {row['scanner']} {row['rule_id']}\n"
            f"path={row['file_path']} line={line_number} duplicate_of={row['duplicate_of']}"
        )
        if not source.is_file():
            sections.append(header + "\n<source file missing>")
            continue
        lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
        if row["cwe"] == "CWE-798":
            current = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
            context = f"safe_source_shape={secret_shape(current)}"
        else:
            start = max(1, line_number - 4)
            end = min(len(lines), line_number + 4)
            rendered = [
                f"{number:6d}{'>' if number == line_number else ' '} {lines[number - 1]}"
                for number in range(start, end + 1)
            ]
            context = "\n".join(rendered)
        sections.append(header + "\n" + context)

    OUTPUT.write_text("\n\n".join(sections) + "\n", encoding="utf-8")
    print(f"output={OUTPUT}")
    print(f"contexts={len(rows)}")


if __name__ == "__main__":
    main()
