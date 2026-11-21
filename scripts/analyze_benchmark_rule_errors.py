#!/usr/bin/env python3
"""Attribute OWASP Benchmark TP/FP detections to the archived Semgrep rules.

Counts are unique test cases within each rule. A test case can be matched by
multiple rules, so rule-level rows are diagnostic and do not sum to the strict
micro totals reported in the paper.
"""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED = ROOT / "workspace/run-20260624-017/repo/expectedresults-1.2.csv"
FINDINGS = ROOT / "runs/run-20260624-017/security_findings.json"
OUTPUT = ROOT / "analysis/benchmark_rule_error_analysis.csv"
OVERLAPPING_CWES = (22, 78, 79, 89, 327, 614)


def load_truth() -> dict[str, tuple[int, bool]]:
    truth: dict[str, tuple[int, bool]] = {}
    with EXPECTED.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or row[0].startswith("#"):
                continue
            truth[row[0].strip()] = (
                int(row[3]),
                row[2].strip().lower() == "true",
            )
    return truth


def extract_cwe(value: object) -> int | None:
    match = re.search(r"CWE[-_ ]?(\d+)", str(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


def main() -> None:
    truth = load_truth()
    findings = json.loads(FINDINGS.read_text(encoding="utf-8"))
    rules = defaultdict(
        lambda: defaultdict(
            lambda: {
                "tp": set(),
                "fp_same_cwe": set(),
                "fp_cross_cwe": set(),
            }
        )
    )

    detections: set[tuple[str, int]] = set()
    for finding in findings:
        if finding.get("in_scope") is not True:
            continue
        test_match = re.search(
            r"(BenchmarkTest\d+)\.java$",
            str(finding.get("file_path", "")),
        )
        cwe = extract_cwe(finding.get("cwe"))
        if not test_match or cwe not in OVERLAPPING_CWES:
            continue
        test_id = test_match.group(1)
        rule_id = str(finding.get("rule_id", ""))
        expected = truth.get(test_id)
        detections.add((test_id, cwe))
        if expected == (cwe, True):
            rules[cwe][rule_id]["tp"].add(test_id)
        elif expected == (cwe, False):
            rules[cwe][rule_id]["fp_same_cwe"].add(test_id)
        elif expected is not None and expected[0] != cwe:
            rules[cwe][rule_id]["fp_cross_cwe"].add(test_id)

    totals: dict[int, dict[str, int]] = {}
    for cwe in OVERLAPPING_CWES:
        totals[cwe] = {
            "tp": sum(
                1
                for test_id, (expected_cwe, real) in truth.items()
                if expected_cwe == cwe and real and (test_id, cwe) in detections
            ),
            "fp": sum(
                1
                for test_id, (expected_cwe, real) in truth.items()
                if expected_cwe == cwe and not real and (test_id, cwe) in detections
            ),
            "fn": sum(
                1
                for test_id, (expected_cwe, real) in truth.items()
                if expected_cwe == cwe and real and (test_id, cwe) not in detections
            ),
        }

    rows: list[dict[str, str | int]] = []
    for cwe in OVERLAPPING_CWES:
        if not rules[cwe]:
            rows.append(
                {
                    "cwe": f"CWE-{cwe}",
                    "cwe_total_tp": totals[cwe]["tp"],
                    "cwe_total_fp": totals[cwe]["fp"],
                    "cwe_total_fn": totals[cwe]["fn"],
                    "rule_id": "(no matching in-scope rule)",
                    "rule_tp_unique_tests": 0,
                    "rule_fp_same_cwe_unique_tests": 0,
                    "rule_fp_cross_cwe_unique_tests": 0,
                }
            )
            continue
        for rule_id, values in sorted(
            rules[cwe].items(),
            key=lambda item: (
                -len(item[1]["tp"]),
                -len(item[1]["fp_same_cwe"]),
                item[0],
            ),
        ):
            rows.append(
                {
                    "cwe": f"CWE-{cwe}",
                    "cwe_total_tp": totals[cwe]["tp"],
                    "cwe_total_fp": totals[cwe]["fp"],
                    "cwe_total_fn": totals[cwe]["fn"],
                    "rule_id": rule_id,
                    "rule_tp_unique_tests": len(values["tp"]),
                    "rule_fp_same_cwe_unique_tests": len(values["fp_same_cwe"]),
                    "rule_fp_cross_cwe_unique_tests": len(values["fp_cross_cwe"]),
                }
            )

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    print(f"output={OUTPUT}")
    print(f"rows={len(rows)}")
    for cwe in OVERLAPPING_CWES:
        print(f"CWE-{cwe}={totals[cwe]}")


if __name__ == "__main__":
    main()
