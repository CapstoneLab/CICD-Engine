#!/usr/bin/env python3
"""Build the reproducible manual-validation set for the 14 DT repositories.

No secret value or source snippet is exported.  Critical and High findings are
included in full.  All Medium CWE-79 findings and a fixed-seed sample of 24
Medium CWE-22 findings are included.
"""

from __future__ import annotations

import csv
import json
import random
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "analysis" / "dt_manual_validation_candidates.csv"
SEED = 20260723
RUNS = (
    ("DT1", "run-20260723-002"),
    ("DT2", "run-20260723-004"),
    ("DT3", "run-20260723-003"),
    ("DT4", "run-20260723-005"),
    ("DT5", "run-20260723-014"),
    ("DT6", "run-20260723-013"),
    ("DT7", "run-20260723-006"),
    ("DT8", "run-20260723-007"),
    ("DT9", "run-20260723-008"),
    ("DT10", "run-20260723-011"),
    ("DT11", "run-20260723-012"),
    ("DT12", "run-20260723-015"),
    ("DT13", "run-20260723-009"),
    ("DT14", "run-20260723-010"),
)


def load_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for label, run_id in RUNS:
        path = ROOT / "runs" / run_id / "security_findings.json"
        for source_index, finding in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            if finding.get("in_scope") is not True:
                continue
            row = {
                "repository_id": label,
                "run_id": run_id,
                "source_index": source_index,
                "scanner": finding.get("scanner_name"),
                "rule_id": finding.get("rule_id"),
                "cwe": finding.get("cwe"),
                "policy_severity": finding.get("severity"),
                "policy_item": finding.get("policy_item"),
                "file_path": finding.get("file_path"),
                "line_number": finding.get("line_number"),
                "column_number": finding.get("column_number"),
                "title": finding.get("title"),
            }
            rows.append(row)
    return rows


def main() -> None:
    rows = load_rows()
    critical_high = [
        row for row in rows if row["policy_severity"] in {"critical", "high"}
    ]
    medium_xss = [
        row
        for row in rows
        if row["policy_severity"] == "medium" and row["cwe"] == "CWE-79"
    ]
    medium_path = sorted(
        (
            row
            for row in rows
            if row["policy_severity"] == "medium" and row["cwe"] == "CWE-22"
        ),
        key=lambda row: (
            str(row["repository_id"]),
            str(row["file_path"]),
            int(row["line_number"] or 0),
            str(row["rule_id"]),
        ),
    )
    rng = random.Random(SEED)
    sampled_path = rng.sample(medium_path, 24)
    selected = critical_high + medium_xss + sampled_path
    selected.sort(
        key=lambda row: (
            int(str(row["repository_id"])[2:]),
            {"critical": 0, "high": 1, "medium": 2}[str(row["policy_severity"])],
            str(row["file_path"]),
            int(row["line_number"] or 0),
            str(row["scanner"]),
            str(row["rule_id"]),
        )
    )

    location_first: dict[tuple[object, ...], str] = {}
    output_rows: list[dict[str, object]] = []
    for number, row in enumerate(selected, start=1):
        finding_id = f"MV-{number:03d}"
        location_key = (
            row["repository_id"],
            row["cwe"],
            row["file_path"],
            row["line_number"],
        )
        duplicate_of = location_first.get(location_key, "")
        location_first.setdefault(location_key, finding_id)
        output_rows.append(
            {
                "finding_id": finding_id,
                **row,
                "sample_group": (
                    "critical_high_census"
                    if row["policy_severity"] in {"critical", "high"}
                    else "medium_cwe79_census"
                    if row["cwe"] == "CWE-79"
                    else f"medium_cwe22_random_n24_seed_{SEED}"
                ),
                "duplicate_of": duplicate_of,
                "code_context": "",
                "manual_assessment": "",
                "deployment_relevance": "",
                "review_rationale": "",
            }
        )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_rows[0]))
        writer.writeheader()
        writer.writerows(output_rows)

    counts = Counter((row["policy_severity"], row["cwe"]) for row in output_rows)
    print(f"output={OUTPUT}")
    print(f"seed={SEED}")
    print(f"selected={len(output_rows)}")
    print(f"unique_locations={len(location_first)}")
    print(f"counts={dict(counts)}")


if __name__ == "__main__":
    main()
