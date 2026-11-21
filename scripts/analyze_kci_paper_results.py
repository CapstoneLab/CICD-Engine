#!/usr/bin/env python3
"""Reproduce the quantitative values used in the KCI paper draft.

The script is intentionally read-only. It selects one representative run per
verified repository, excludes the engine-generated local workflow from the
repository-level aggregate, and evaluates the policy-overlapping Benchmark
v1.2 cases contained in the A7 snapshot. Workspace-inclusive counts are
retained for sensitivity analysis.
"""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]

REPRESENTATIVE_RUNS: tuple[tuple[str, str, str], ...] = (
    ("A", "A1", "run-20260624-009"),
    ("A", "A2", "run-20260624-011"),
    ("A", "A3", "run-20260624-013"),
    ("A", "A4", "run-20260624-015"),
    ("A", "A5", "run-20260624-001"),
    ("A", "A6", "run-20260624-002"),
    ("A", "A7", "run-20260624-017"),
    ("A", "A8", "run-20260624-005"),
    ("B", "DT1", "run-20260723-002"),
    ("B", "DT2", "run-20260723-004"),
    ("B", "DT3", "run-20260723-003"),
    ("B", "DT4", "run-20260723-005"),
    ("B", "DT5", "run-20260723-014"),
    ("B", "DT6", "run-20260723-013"),
    ("B", "DT7", "run-20260723-006"),
    ("B", "DT8", "run-20260723-007"),
    ("B", "DT9", "run-20260723-008"),
    ("B", "DT10", "run-20260723-011"),
    ("B", "DT11", "run-20260723-012"),
    ("B", "DT12", "run-20260723-015"),
    ("B", "DT13", "run-20260723-009"),
    ("B", "DT14", "run-20260723-010"),
    ("C", "C1", "run-20260604-008"),
)

MISSING_TARGETS: tuple[str, ...] = ()

POLICY_CWES: dict[int, str] = {
    89: "critical",
    78: "critical",
    798: "critical",
    94: "critical",
    502: "high",
    639: "high",
    347: "high",
    319: "high",
    22: "medium",
    79: "medium",
    327: "medium",
    918: "medium",
    209: "low",
    1004: "low",
    614: "low",
    521: "low",
}

RAW_SEVERITY_MAP = {"ERROR": "high", "WARNING": "medium", "INFO": "low"}
REQUIRED_FILES = (
    "pipeline_result.json",
    "security_verdict.json",
    "security_findings.json",
    "semgrep_report.json",
    "gitleaks_report.json",
)
ENGINE_GENERATED_PATHS = frozenset({".localci/workflow.yml"})


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def seconds_between(start: str | None, end: str | None) -> float | None:
    if not start or not end:
        return None
    return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()


def extract_cwe(value: Any) -> int | None:
    if isinstance(value, list):
        value = " ".join(str(item) for item in value)
    match = re.search(r"CWE[-_ ]?(\d+)", str(value), re.IGNORECASE)
    return int(match.group(1)) if match else None


def is_engine_generated_finding(item: dict[str, Any]) -> bool:
    file_path = str(item.get("file_path", "")).removeprefix("./")
    return file_path in ENGINE_GENERATED_PATHS


def load_run(group: str, label: str, run_id: str) -> dict[str, Any]:
    run_dir = ROOT / "runs" / run_id
    missing = [name for name in REQUIRED_FILES if not (run_dir / name).exists()]
    if missing:
        raise FileNotFoundError(f"{run_id}: missing {', '.join(missing)}")

    pipeline = read_json(run_dir / "pipeline_result.json")
    verdict = read_json(run_dir / "security_verdict.json")
    findings = read_json(run_dir / "security_findings.json")
    semgrep = read_json(run_dir / "semgrep_report.json")
    gitleaks = read_json(run_dir / "gitleaks_report.json")

    semgrep_count = len(semgrep.get("results", []))
    gitleaks_count = len(gitleaks) if isinstance(gitleaks, list) else 0
    if len(findings) != semgrep_count + gitleaks_count:
        raise ValueError(
            f"{run_id}: normalized finding count does not match raw reports "
            f"({len(findings)} != {semgrep_count} + {gitleaks_count})"
        )

    repository_findings = [item for item in findings if not is_engine_generated_finding(item)]
    generated_findings = [item for item in findings if is_engine_generated_finding(item)]
    in_scope = sum(item.get("in_scope") is True for item in repository_findings)
    workspace_in_scope = sum(item.get("in_scope") is True for item in findings)
    raw = len(repository_findings)
    steps: dict[str, float] = {}
    for step in pipeline.get("steps", []):
        duration = seconds_between(step.get("started_at"), step.get("finished_at"))
        if duration is not None:
            steps[step["step_name"]] = duration

    return {
        "group": group,
        "label": label,
        "run_id": run_id,
        "repo_url": pipeline.get("repo_url"),
        "commit": verdict.get("scanned_commit_sha"),
        "runtime": pipeline.get("runtime_type"),
        "pipeline_status": pipeline.get("status"),
        "verdict": verdict.get("verdict"),
        "score": verdict.get("score"),
        "counts": verdict.get("counts"),
        "raw": raw,
        "in_scope": in_scope,
        "out_of_scope": raw - in_scope,
        "reduction_pct": round(((raw - in_scope) / raw * 100), 1) if raw else None,
        "workspace_raw": len(findings),
        "workspace_in_scope": workspace_in_scope,
        "workspace_out_of_scope": len(findings) - workspace_in_scope,
        "excluded_engine_generated": len(generated_findings),
        "total_seconds": seconds_between(pipeline.get("started_at"), pipeline.get("finished_at")),
        "step_seconds": steps,
        "semgrep_errors": len(semgrep.get("errors", [])),
        "semgrep_version": semgrep.get("version"),
    }


def aggregate_groups(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["group"]].append(row)

    output: list[dict[str, Any]] = []
    for group in ("A", "B", "C"):
        items = grouped[group]
        raw = sum(item["raw"] for item in items)
        in_scope = sum(item["in_scope"] for item in items)
        output.append(
            {
                "group": group,
                "repositories": len(items),
                "raw": raw,
                "in_scope": in_scope,
                "out_of_scope": raw - in_scope,
                "weighted_reduction_pct": round((raw - in_scope) / raw * 100, 1),
                "median_repo_reduction_pct": round(
                    statistics.median(
                        item["reduction_pct"]
                        for item in items
                        if item["reduction_pct"] is not None
                    ),
                    1,
                ),
                "verdicts": dict(Counter(item["verdict"] for item in items)),
                "mean_total_seconds": round(
                    statistics.mean(item["total_seconds"] for item in items), 1
                ),
                "median_total_seconds": round(
                    statistics.median(item["total_seconds"] for item in items), 1
                ),
            }
        )

    raw = sum(item["raw"] for item in rows)
    in_scope = sum(item["in_scope"] for item in rows)
    output.append(
        {
            "group": "ALL_VERIFIED",
            "repositories": len(rows),
            "raw": raw,
            "in_scope": in_scope,
            "out_of_scope": raw - in_scope,
            "weighted_reduction_pct": round((raw - in_scope) / raw * 100, 1),
            "median_repo_reduction_pct": round(
                statistics.median(
                    item["reduction_pct"]
                    for item in rows
                    if item["reduction_pct"] is not None
                ),
                1,
            ),
            "verdicts": dict(Counter(item["verdict"] for item in rows)),
        }
    )
    return output


def generated_workflow_sensitivity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    workspace_raw = sum(item["workspace_raw"] for item in rows)
    workspace_in_scope = sum(item["workspace_in_scope"] for item in rows)
    repository_raw = sum(item["raw"] for item in rows)
    repository_in_scope = sum(item["in_scope"] for item in rows)
    return {
        "excluded_path": ".localci/workflow.yml",
        "excluded_records": sum(item["excluded_engine_generated"] for item in rows),
        "workspace_inclusive": {
            "raw": workspace_raw,
            "in_scope": workspace_in_scope,
            "out_of_scope": workspace_raw - workspace_in_scope,
            "out_of_scope_pct": round(
                (workspace_raw - workspace_in_scope) / workspace_raw * 100, 1
            ),
        },
        "repository_only": {
            "raw": repository_raw,
            "in_scope": repository_in_scope,
            "out_of_scope": repository_raw - repository_in_scope,
            "out_of_scope_pct": round(
                (repository_raw - repository_in_scope) / repository_raw * 100, 1
            ),
        },
    }


def evaluate_benchmark() -> dict[str, Any]:
    expected_path = ROOT / "workspace/run-20260624-017/repo/expectedresults-1.2.csv"
    findings_path = ROOT / "runs/run-20260624-017/security_findings.json"

    truth: dict[str, tuple[int, bool]] = {}
    with expected_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.reader(handle):
            if not row or row[0].startswith("#"):
                continue
            truth[row[0].strip()] = (int(row[3]), row[2].strip().lower() == "true")

    detections: set[tuple[str, int]] = set()
    for finding in read_json(findings_path):
        if finding.get("in_scope") is not True:
            continue
        test_match = re.search(r"(BenchmarkTest\d+)\.java$", finding.get("file_path", ""))
        cwe = extract_cwe(finding.get("cwe"))
        if test_match and cwe in POLICY_CWES:
            detections.add((test_match.group(1), cwe))

    overlapping = {22, 78, 79, 89, 327, 614}
    by_cwe: dict[int, dict[str, int | float]] = {}
    for cwe in sorted(overlapping):
        tp = fp = fn = tn = 0
        for test_id, (expected_cwe, real) in truth.items():
            if expected_cwe != cwe:
                continue
            predicted = (test_id, cwe) in detections
            if real and predicted:
                tp += 1
            elif real and not predicted:
                fn += 1
            elif not real and predicted:
                fp += 1
            else:
                tn += 1
        by_cwe[cwe] = metrics(tp, fp, fn, tn)

    tp = sum(1 for test, cwe in detections if truth.get(test) == (cwe, True))
    fp_same = sum(1 for test, cwe in detections if truth.get(test) == (cwe, False))
    fp_cross = sum(
        1 for test, cwe in detections if test in truth and truth[test][0] != cwe
    )
    fn = sum(
        1
        for test, (cwe, real) in truth.items()
        if cwe in overlapping and real and (test, cwe) not in detections
    )
    strict = metrics(tp, fp_same + fp_cross, fn, None)
    strict.update(
        {
            "same_cwe_fp": fp_same,
            "cross_cwe_fp": fp_cross,
            "unique_test_cwe_detections": len(detections),
        }
    )
    return {
        "scope": sorted(overlapping),
        "per_cwe": {f"CWE-{cwe}": values for cwe, values in by_cwe.items()},
        "strict_micro": strict,
    }


def metrics(tp: int, fp: int, fn: int, tn: int | None) -> dict[str, int | float | None]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
    }


def severity_reclassification(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = mismatch = ungraded_secrets = 0
    transitions: Counter[str] = Counter()
    for row in rows:
        run_dir = ROOT / "runs" / row["run_id"]
        semgrep = read_json(run_dir / "semgrep_report.json")
        gitleaks = read_json(run_dir / "gitleaks_report.json")
        if isinstance(gitleaks, list):
            ungraded_secrets += len(gitleaks)
        for result in semgrep.get("results", []):
            cwe = extract_cwe(result.get("extra", {}).get("metadata", {}).get("cwe"))
            if cwe not in POLICY_CWES:
                continue
            raw = RAW_SEVERITY_MAP.get(result.get("extra", {}).get("severity"), "low")
            policy = POLICY_CWES[cwe]
            total += 1
            mismatch += raw != policy
            transitions[f"{raw}->{policy}"] += 1
    return {
        "semgrep_in_scope": total,
        "severity_mismatch": mismatch,
        "mismatch_pct": round(mismatch / total * 100, 1) if total else 0.0,
        "gitleaks_findings_without_raw_grade_mapped_to_critical": ungraded_secrets,
        "transitions": dict(sorted(transitions.items())),
    }


def _hypergeometric_probability(
    x: int,
    row_total: int,
    column_total: int,
    grand_total: int,
) -> float:
    return (
        math.comb(column_total, x)
        * math.comb(grand_total - column_total, row_total - x)
        / math.comb(grand_total, row_total)
    )


def fisher_exact_two_sided(a: int, b: int, c: int, d: int) -> dict[str, Any]:
    """Return the two-sided Fisher exact p-value for [[a, b], [c, d]]."""
    row_total = a + b
    column_total = a + c
    grand_total = a + b + c + d
    lower = max(0, row_total - (grand_total - column_total))
    upper = min(row_total, column_total)
    observed = _hypergeometric_probability(a, row_total, column_total, grand_total)
    p_value = sum(
        probability
        for x in range(lower, upper + 1)
        if (
            probability := _hypergeometric_probability(
                x, row_total, column_total, grand_total
            )
        )
        <= observed + 1e-12
    )
    denominator = b * c
    numerator = a * d
    if denominator:
        odds_ratio: float | str | None = round(numerator / denominator, 3)
    elif numerator:
        odds_ratio = "inf"
    else:
        odds_ratio = None
    corrected_or = ((a + 0.5) * (d + 0.5)) / ((b + 0.5) * (c + 0.5))
    return {
        "table": [[a, b], [c, d]],
        "odds_ratio": odds_ratio,
        "haldane_anscombe_or": round(corrected_or, 3),
        "p_value_two_sided": round(min(1.0, p_value), 4),
    }


def compare_cwe_profiles(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Compare repository-level CWE prevalence between vulnerable apps and DTs.

    Repository presence/absence is used as the unit of analysis so that a large
    monorepo cannot dominate the comparison merely by contributing more findings.
    """
    grouped: dict[str, list[set[int]]] = {"A": [], "B": []}
    finding_counts: dict[str, Counter[int]] = {"A": Counter(), "B": Counter()}
    for row in rows:
        group = row["group"]
        if group not in grouped:
            continue
        findings = read_json(ROOT / "runs" / row["run_id"] / "security_findings.json")
        cwes: list[int] = []
        for finding in findings:
            if finding.get("in_scope") is not True or is_engine_generated_finding(finding):
                continue
            cwe = extract_cwe(finding.get("cwe"))
            if cwe in POLICY_CWES:
                cwes.append(cwe)
        grouped[group].append(set(cwes))
        finding_counts[group].update(cwes)

    targets: dict[str, set[int]] = {
        "CWE-319": {319},
        "CWE-79": {79},
        "CWE-89": {89},
        "CWE-798": {798},
        "Other policy CWEs": set(POLICY_CWES) - {319, 79, 89, 798},
    }
    comparisons: dict[str, Any] = {}
    for label, target_cwes in targets.items():
        web_present = sum(bool(values & target_cwes) for values in grouped["A"])
        dt_present = sum(bool(values & target_cwes) for values in grouped["B"])
        stats = fisher_exact_two_sided(
            dt_present,
            len(grouped["B"]) - dt_present,
            web_present,
            len(grouped["A"]) - web_present,
        )
        stats.update(
            {
                "web_repositories": f"{web_present}/{len(grouped['A'])}",
                "dt_repositories": f"{dt_present}/{len(grouped['B'])}",
                "web_findings": sum(finding_counts["A"][cwe] for cwe in target_cwes),
                "dt_findings": sum(finding_counts["B"][cwe] for cwe in target_cwes),
            }
        )
        comparisons[label] = stats
    return {
        "unit": "repository presence of at least one in-scope finding",
        "web_repository_count": len(grouped["A"]),
        "dt_repository_count": len(grouped["B"]),
        "comparisons": comparisons,
    }


def main() -> None:
    rows = [load_run(*spec) for spec in REPRESENTATIVE_RUNS]
    payload = {
        "representative_runs": rows,
        "group_aggregates": aggregate_groups(rows),
        "generated_workflow_sensitivity": generated_workflow_sensitivity(rows),
        "benchmark_accuracy": evaluate_benchmark(),
        "cwe_profile_comparison": compare_cwe_profiles(rows),
        "severity_reclassification": severity_reclassification(rows),
        "missing_targets": list(MISSING_TARGETS),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
