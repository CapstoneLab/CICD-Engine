#!/usr/bin/env python3
"""Reproduce ablation, score sensitivity, and review-adjusted DT results."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
RUNS = (
    ("DT1", "run-20260723-002"), ("DT2", "run-20260723-004"),
    ("DT3", "run-20260723-003"), ("DT4", "run-20260723-005"),
    ("DT5", "run-20260723-014"), ("DT6", "run-20260723-013"),
    ("DT7", "run-20260723-006"), ("DT8", "run-20260723-007"),
    ("DT9", "run-20260723-008"), ("DT10", "run-20260723-011"),
    ("DT11", "run-20260723-012"), ("DT12", "run-20260723-015"),
    ("DT13", "run-20260723-009"), ("DT14", "run-20260723-010"),
)
SEVERITIES = ("critical", "high", "medium", "low")
WEIGHTS = {"critical": 20.0, "high": 5.0, "medium": 1.0, "low": 0.2}
CVSS_MIDPOINTS = {"critical": 9.5, "high": 7.5, "medium": 5.0, "low": 2.0}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def finding_key(label: str, finding: dict) -> tuple:
    return (
        label,
        finding.get("cwe"),
        finding.get("file_path"),
        int(finding.get("line_number") or 0),
    )


def deduplicate(label: str, findings: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    output: list[dict] = []
    for finding in findings:
        key = finding_key(label, finding)
        if key not in seen:
            seen.add(key)
            output.append(finding)
    return output


def counts(findings: list[dict]) -> dict[str, int]:
    counter = Counter(str(finding.get("severity", "low")).lower() for finding in findings)
    return {severity: counter[severity] for severity in SEVERITIES}


def gate(value: dict[str, int]) -> str:
    if value["critical"]:
        return "BLOCK"
    if value["high"]:
        return "BLOCK_PENDING_APPROVAL"
    if value["medium"]:
        return "WARN"
    return "PASS"


def capped_score(value: dict[str, int]) -> float:
    high = min(5 * value["high"], 19)
    medium = min(value["medium"], 4)
    low = min(0.2 * value["low"], 0.9)
    raw = 100 - 20 * value["critical"] - high - medium - low
    return round(max(0, min(40, raw)) if value["critical"] else max(0, raw), 1)


def risk_sum(value: dict[str, int], weights: dict[str, float]) -> float:
    return sum(value[key] * weights[key] for key in SEVERITIES)


def rankdata(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(indexed):
        end = start + 1
        while end < len(indexed) and indexed[end][1] == indexed[start][1]:
            end += 1
        average_rank = (start + 1 + end) / 2
        for position in range(start, end):
            ranks[indexed[position][0]] = average_rank
        start = end
    return ranks


def spearman(left: list[float], right: list[float]) -> float:
    x, y = rankdata(left), rankdata(right)
    xbar, ybar = mean(x), mean(y)
    numerator = sum((a - xbar) * (b - ybar) for a, b in zip(x, y, strict=True))
    denominator = math.sqrt(sum((a - xbar) ** 2 for a in x) * sum((b - ybar) ** 2 for b in y))
    return round(numerator / denominator, 3) if denominator else 0.0


def main() -> None:
    with (ROOT / "analysis/dt_manual_validation_results.csv").open(encoding="utf-8-sig", newline="") as handle:
        reviewed = list(csv.DictReader(handle))
    review_by_source = {
        (row["run_id"], int(row["source_index"])): row for row in reviewed
    }

    repositories: list[dict] = []
    configurations: dict[str, list[dict]] = {
        "semgrep_only_policy": [],
        "combined_all_rules": [],
        "combined_policy": [],
        "combined_policy_deduplicated": [],
        "manual_ch_confirmed_raw_ml": [],
    }
    for label, run_id in RUNS:
        all_findings = read_json(ROOT / "runs" / run_id / "security_findings.json")
        repo_findings = [f for f in all_findings if f.get("file_path") != ".localci/workflow.yml"]
        in_scope = [f for f in repo_findings if f.get("in_scope") is True]
        semgrep_only = [f for f in in_scope if f.get("scanner_name") == "semgrep"]
        deduped = deduplicate(label, in_scope)

        manually_adjusted: list[dict] = []
        for source_index, finding in enumerate(all_findings):
            if finding.get("file_path") == ".localci/workflow.yml" or finding.get("in_scope") is not True:
                continue
            severity = str(finding.get("severity", "")).lower()
            if severity in {"critical", "high"}:
                review = review_by_source[(run_id, source_index)]
                if review["manual_assessment"] != "confirmed_pattern":
                    continue
            manually_adjusted.append(finding)
        manually_adjusted = deduplicate(label, manually_adjusted)

        variants = {
            "semgrep_only_policy": semgrep_only,
            "combined_all_rules": repo_findings,
            "combined_policy": in_scope,
            "combined_policy_deduplicated": deduped,
            "manual_ch_confirmed_raw_ml": manually_adjusted,
        }
        variant_rows: dict[str, dict] = {}
        for name, findings in variants.items():
            item_counts = counts(findings)
            row = {
                "repository_id": label,
                "finding_count": len(findings),
                "counts": item_counts,
                "verdict": gate(item_counts),
                "score": capped_score(item_counts),
            }
            configurations[name].append(row)
            variant_rows[name] = row

        base_counts = variant_rows["combined_policy_deduplicated"]["counts"]
        repositories.append(
            {
                "repository_id": label,
                "automatic_counts": variant_rows["combined_policy"]["counts"],
                "deduplicated_counts": base_counts,
                "automatic_score": variant_rows["combined_policy"]["score"],
                "deduplicated_score": capped_score(base_counts),
                "uncapped_hierarchical_score": round(max(0, 100 - risk_sum(base_counts, WEIGHTS)), 1),
                "review_adjusted_counts": variant_rows["manual_ch_confirmed_raw_ml"]["counts"],
                "review_adjusted_score": variant_rows["manual_ch_confirmed_raw_ml"]["score"],
                "review_adjusted_verdict": variant_rows["manual_ch_confirmed_raw_ml"]["verdict"],
                "raw_count_risk": sum(base_counts.values()),
                "hierarchical_risk": round(risk_sum(base_counts, WEIGHTS), 1),
                "cvss_midpoint_risk": round(risk_sum(base_counts, CVSS_MIDPOINTS), 1),
            }
        )

    ablation: dict[str, dict] = {}
    for name, rows in configurations.items():
        ablation[name] = {
            "finding_count": sum(row["finding_count"] for row in rows),
            "verdicts": dict(sorted(Counter(row["verdict"] for row in rows).items())),
            "per_repository": rows,
        }

    current_risk = [100 - row["deduplicated_score"] for row in repositories]
    score_sensitivity = {
        "models": {
            "implemented_capped": [100 - row["deduplicated_score"] for row in repositories],
            "uncapped_hierarchical": [row["hierarchical_risk"] for row in repositories],
            "equal_finding_count": [row["raw_count_risk"] for row in repositories],
            "cvss_band_midpoint_sum": [row["cvss_midpoint_risk"] for row in repositories],
        },
        "spearman_vs_implemented_capped": {
            "uncapped_hierarchical": spearman(current_risk, [row["hierarchical_risk"] for row in repositories]),
            "equal_finding_count": spearman(current_risk, [row["raw_count_risk"] for row in repositories]),
            "cvss_band_midpoint_sum": spearman(current_risk, [row["cvss_midpoint_risk"] for row in repositories]),
        },
        "alternative_weights": {},
        "gate_is_weight_independent": True,
    }
    alternatives = {
        "W1_20_5_1_0.2": WEIGHTS,
        "W2_16_4_1_0.25": {"critical": 16, "high": 4, "medium": 1, "low": 0.25},
        "W3_25_6_1_0.1": {"critical": 25, "high": 6, "medium": 1, "low": 0.1},
    }
    baseline = [risk_sum(row["deduplicated_counts"], WEIGHTS) for row in repositories]
    for name, weights in alternatives.items():
        values = [risk_sum(row["deduplicated_counts"], weights) for row in repositories]
        score_sensitivity["alternative_weights"][name] = {
            "weights": weights,
            "spearman_vs_W1": spearman(baseline, values),
            "repository_risk_values": [round(value, 2) for value in values],
        }

    payload = {
        "scope": {
            "repositories": 14,
            "environment": "development",
            "manual_adjustment": "Critical/High exact-location census: confirmed_pattern retained; Medium/Low retained automatically; exact duplicates removed",
        },
        "ablation": ablation,
        "score_sensitivity": score_sensitivity,
        "repositories": repositories,
    }
    output = ROOT / "analysis/dt_revision_experiments.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"output={output}")
    print(json.dumps({"ablation": ablation, "score_sensitivity": score_sensitivity}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
