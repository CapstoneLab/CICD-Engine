#!/usr/bin/env python3
"""Summarize CWE-798 candidates without printing credential material."""

from __future__ import annotations

import csv
import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "analysis" / "dt_manual_validation_candidates.csv"


def path_role(path: str) -> str:
    lowered = path.lower()
    if any(part in lowered for part in ("/test/", "/tests/", ".test.", "test_")):
        return "test"
    if any(part in lowered for part in ("readme", "/docs/", ".md")):
        return "documentation"
    if any(part in lowered for part in (".example", ".template", "/templates/")):
        return "example_or_template"
    if any(part in lowered for part in ("docker-compose", "kubernetes/", ".github/workflows/")):
        return "deployment_or_ci"
    return "source_or_resource"


def extract_material(source: Path, line_number: int, rule_id: str) -> tuple[str, str]:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
    if "private-key" in rule_id or "PRIVATE KEY" in line:
        return source.read_text(encoding="utf-8", errors="replace"), "PEM_private_key"
    if re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", line):
        token = re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", line)
        return (token.group(0) if token else line), "JWT"
    split = re.split(r"[:=]", line, maxsplit=1)
    material = split[1].strip() if len(split) == 2 else line.strip()
    return material, "literal_or_rule_match"


def safe_name(source: Path, line_number: int) -> str:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    line = lines[line_number - 1] if 0 < line_number <= len(lines) else ""
    if re.search(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", line):
        return "jwt_literal"
    if "PRIVATE KEY" in line:
        return "private_key"
    left = re.split(r"[:=]", line, maxsplit=1)[0].strip()
    left = re.sub(r"[^A-Za-z0-9_@. -]", "", left)
    return left[-60:] or "unlabeled"


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row["cwe"] == "CWE-798"]

    material_groups: dict[str, str] = {}
    group_counter = 0
    output = []
    for row in rows:
        source = ROOT / "workspace" / row["run_id"] / "repo" / row["file_path"]
        line_number = int(row["line_number"] or 0)
        material, value_type = extract_material(source, line_number, row["rule_id"])
        digest = hashlib.sha256(material.encode("utf-8", errors="replace")).hexdigest()
        if digest not in material_groups:
            group_counter += 1
            material_groups[digest] = f"SG-{group_counter:02d}"
        lowered = material.lower()
        placeholder = bool(
            re.search(r"dummy|example|sample|changeme|replace|your[-_ ]|test[-_ ]|fake", lowered)
        )
        output.append(
            (
                row["finding_id"],
                row["repository_id"],
                row["rule_id"],
                path_role(row["file_path"]),
                row["file_path"],
                safe_name(source, line_number),
                value_type,
                len(material),
                "yes" if placeholder else "no",
                material_groups[digest],
                row["duplicate_of"] or "-",
            )
        )

    print("id | repo | rule | role | path | variable | value_type | length | placeholder_signal | value_group | duplicate")
    for values in output:
        print(" | ".join(str(value) for value in values))


if __name__ == "__main__":
    main()
