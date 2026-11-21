#!/usr/bin/env python3
"""Score a Semgrep JSON report against the complete OWASP Benchmark v1.2 truth set.

The scanner report is produced independently of the ground-truth CSV.  This
script consumes the two artifacts only after scanning, deduplicates findings at
(test ID, CWE), and emits both:

* strict metrics using the scanner's original CWE metadata; and
* harmonized metrics using a predeclared, rule-semantic mapping.

No mapping may refer to a Benchmark test ID or expected true/false label.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


TEST_ID_PATTERN = re.compile(r"(BenchmarkTest\d+)\.java$")
CWE_PATTERN = re.compile(r"CWE[-_ ]?(\d+)", re.IGNORECASE)


@dataclass(frozen=True)
class Truth:
    cwe: int
    vulnerable: bool


@dataclass(frozen=True)
class Detection:
    test_id: str
    cwe: int
    rule_id: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", required=True, type=Path)
    parser.add_argument("--semgrep-report", required=True, type=Path)
    parser.add_argument("--harmonization", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--scanner-command", default="")
    parser.add_argument("--scanner-version", default="")
    parser.add_argument("--source-commit", default="")
    parser.add_argument("--rule-config", type=Path)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_truth(path: Path) -> dict[str, Truth]:
    truth: dict[str, Truth] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.reader(handle):
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 4:
                raise ValueError(f"malformed truth row: {row!r}")
            test_id = row[0].strip()
            if not re.fullmatch(r"BenchmarkTest\d+", test_id):
                raise ValueError(f"invalid Benchmark test ID: {test_id!r}")
            truth[test_id] = Truth(
                cwe=int(row[3]),
                vulnerable=row[2].strip().lower() == "true",
            )
    if not truth:
        raise ValueError(f"no truth rows found in {path}")
    return truth


def extract_cwes(value: object) -> set[int]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple)):
        found: set[int] = set()
        for entry in value:
            found.update(extract_cwes(entry))
        return found
    return {int(match.group(1)) for match in CWE_PATTERN.finditer(str(value))}


def load_detections(path: Path) -> tuple[list[Detection], dict[str, int]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError(f"{path} is not a Semgrep JSON report")

    detections: set[Detection] = set()
    target_results = 0
    results_without_cwe = 0
    for item in data["results"]:
        test_match = TEST_ID_PATTERN.search(str(item.get("path", "")))
        if test_match is None:
            continue
        target_results += 1
        extra = item.get("extra") or {}
        metadata = extra.get("metadata") or {}
        cwes = extract_cwes(metadata.get("cwe"))
        if not cwes:
            results_without_cwe += 1
        for cwe in cwes:
            detections.add(
                Detection(
                    test_id=test_match.group(1),
                    cwe=cwe,
                    rule_id=str(item.get("check_id", "unknown")),
                )
            )

    return sorted(
        detections,
        key=lambda item: (item.test_id, item.cwe, item.rule_id),
    ), {
        "semgrep_result_count": len(data["results"]),
        "benchmark_target_result_count": target_results,
        "benchmark_target_results_without_cwe": results_without_cwe,
        "unique_test_cwe_rule_detections": len(detections),
    }


def load_harmonization(path: Path) -> tuple[dict[str, tuple[set[int], int]], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    serialized = json.dumps(data, sort_keys=True)
    if TEST_ID_PATTERN.search(serialized) or re.search(r"BenchmarkTest\d+", serialized):
        raise ValueError("harmonization must not contain Benchmark test IDs")

    overrides: dict[str, tuple[set[int], int]] = {}
    for rule_id, definition in (data.get("rule_overrides") or {}).items():
        source_cwes = {int(value) for value in definition.get("from_cwes", [])}
        target_cwe = int(definition["to_cwe"])
        if not source_cwes:
            raise ValueError(f"mapping {rule_id!r} has no from_cwes")
        overrides[str(rule_id)] = (source_cwes, target_cwe)
    return overrides, data


def harmonize(
    detections: Iterable[Detection],
    overrides: dict[str, tuple[set[int], int]],
) -> tuple[list[Detection], Counter[str]]:
    output: set[Detection] = set()
    applied: Counter[str] = Counter()
    for detection in detections:
        mapped_cwe = detection.cwe
        mapping_rule_id = None
        override = overrides.get(detection.rule_id)
        if override is not None:
            mapping_rule_id = detection.rule_id
        else:
            suffix_matches = [
                rule_id
                for rule_id in overrides
                if detection.rule_id.endswith(f".{rule_id}")
            ]
            if len(suffix_matches) > 1:
                raise ValueError(
                    f"ambiguous harmonization for namespaced rule "
                    f"{detection.rule_id!r}: {suffix_matches!r}"
                )
            if suffix_matches:
                mapping_rule_id = suffix_matches[0]
                override = overrides[mapping_rule_id]
        if override is not None:
            source_cwes, target_cwe = override
            if detection.cwe in source_cwes:
                mapped_cwe = target_cwe
                assert mapping_rule_id is not None
                applied[mapping_rule_id] += 1
        output.add(
            Detection(
                test_id=detection.test_id,
                cwe=mapped_cwe,
                rule_id=detection.rule_id,
            )
        )
    return sorted(
        output,
        key=lambda item: (item.test_id, item.cwe, item.rule_id),
    ), applied


def metric_values(tp: int, fp: int, fn: int, tn: int | None) -> dict[str, int | float | None]:
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def score(
    truth: dict[str, Truth],
    detections: Iterable[Detection],
) -> dict[str, Any]:
    benchmark_cwes = sorted({item.cwe for item in truth.values()})
    detected_pairs = {
        (item.test_id, item.cwe)
        for item in detections
        if item.test_id in truth and item.cwe in benchmark_cwes
    }

    per_cwe: dict[str, dict[str, int | float | None]] = {}
    for cwe in benchmark_cwes:
        tp = fp = fn = tn = 0
        for test_id, expected in truth.items():
            if expected.cwe != cwe:
                continue
            predicted = (test_id, cwe) in detected_pairs
            if expected.vulnerable and predicted:
                tp += 1
            elif expected.vulnerable:
                fn += 1
            elif predicted:
                fp += 1
            else:
                tn += 1
        per_cwe[f"CWE-{cwe}"] = metric_values(tp, fp, fn, tn)

    aligned_tp = sum(int(values["tp"]) for values in per_cwe.values())
    aligned_fp = sum(int(values["fp"]) for values in per_cwe.values())
    aligned_fn = sum(int(values["fn"]) for values in per_cwe.values())
    aligned_tn = sum(int(values["tn"]) for values in per_cwe.values())

    cross_pairs = {
        (test_id, predicted_cwe)
        for test_id, predicted_cwe in detected_pairs
        if predicted_cwe != truth[test_id].cwe
    }
    strict_taxonomy = metric_values(
        aligned_tp,
        aligned_fp + len(cross_pairs),
        aligned_fn,
        aligned_tn,
    )
    strict_taxonomy.update(
        {
            "same_cwe_fp": aligned_fp,
            "cross_cwe_fp": len(cross_pairs),
        }
    )

    macro = {
        name: round(
            sum(float(values[name]) for values in per_cwe.values()) / len(per_cwe),
            6,
        )
        for name in ("precision", "recall", "f1")
    }
    category_aligned = metric_values(aligned_tp, aligned_fp, aligned_fn, aligned_tn)
    return {
        "scope": [f"CWE-{cwe}" for cwe in benchmark_cwes],
        "per_cwe": per_cwe,
        "category_aligned_micro": category_aligned,
        "taxonomy_strict_micro": strict_taxonomy,
        "macro_average": macro,
        "unique_benchmark_test_cwe_detections": len(detected_pairs),
    }


def write_csv(path: Path, strict: dict[str, Any], harmonized: dict[str, Any]) -> None:
    fieldnames = [
        "mode",
        "cwe",
        "tp",
        "fp",
        "fn",
        "tn",
        "precision",
        "recall",
        "f1",
    ]
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for mode, report in (("strict", strict), ("harmonized", harmonized)):
            for cwe, values in report["per_cwe"].items():
                writer.writerow({"mode": mode, "cwe": cwe, **values})
            writer.writerow(
                {
                    "mode": mode,
                    "cwe": "MICRO_CATEGORY_ALIGNED",
                    **report["category_aligned_micro"],
                }
            )
            writer.writerow(
                {
                    "mode": mode,
                    "cwe": "MICRO_TAXONOMY_STRICT",
                    **{
                        key: value
                        for key, value in report["taxonomy_strict_micro"].items()
                        if key in fieldnames
                    },
                }
            )


def markdown_number(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.3f}"
    return str(value)


def markdown_cell(value: object) -> str:
    return markdown_number(value).replace("|", "\\|").replace("\n", " ")


def write_markdown(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# OWASP Benchmark v1.2 fair Semgrep evaluation",
        "",
        "The ground-truth CSV was used only after scanning. Findings are deduplicated "
        "at `(Benchmark test ID, CWE)`. No test-ID or expected-label exceptions are "
        "permitted in the harmonization file.",
        "",
        "## Summary",
        "",
        "| Mode | TP | FP | FN | TN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for mode in ("strict", "harmonized"):
        values = report[mode]["category_aligned_micro"]
        lines.append(
            "| "
            + " | ".join(
                [
                    mode,
                    *(
                        markdown_cell(values[name])
                        for name in ("tp", "fp", "fn", "tn", "precision", "recall", "f1")
                    ),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "The summary uses category-aligned OWASP-style scoring. "
            "`taxonomy_strict_micro` in `metrics.json` additionally penalizes alerts "
            "whose predicted Benchmark CWE differs from the test's expected CWE.",
            "",
            "## Taxonomy-strict diagnostic",
            "",
            "| Mode | TP | Same-CWE FP | Cross-CWE FP | Total FP | FN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for mode in ("strict", "harmonized"):
        values = report[mode]["taxonomy_strict_micro"]
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(value)
                for value in (
                    mode,
                    values["tp"],
                    values["same_cwe_fp"],
                    values["cross_cwe_fp"],
                    values["fp"],
                    values["fn"],
                    values["precision"],
                    values["recall"],
                    values["f1"],
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Declared CWE harmonization",
            "",
            "| Semgrep rule | From CWE | Benchmark CWE | Rationale |",
            "|---|---:|---:|---|",
        ]
    )
    harmonization = report["diagnostics"]["harmonization_document"]
    for rule_id, definition in harmonization["rule_overrides"].items():
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(value)
                for value in (
                    rule_id,
                    ", ".join(str(value) for value in definition["from_cwes"]),
                    definition["to_cwe"],
                    definition["rationale"],
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Harmonized per-CWE metrics",
            "",
            "| CWE | TP | FP | FN | TN | Precision | Recall | F1 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for cwe, values in report["harmonized"]["per_cwe"].items():
        lines.append(
            "| "
            + " | ".join(
                [
                    cwe,
                    *(
                        markdown_cell(values[name])
                        for name in ("tp", "fp", "fn", "tn", "precision", "recall", "f1")
                    ),
                ]
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Scanner: Semgrep {report['metadata']['scanner_version']}",
            f"- Source commit: `{report['metadata']['source_commit']}`",
            f"- Scanner command: `{report['metadata']['scanner_command']}`",
            f"- Truth SHA-256: `{report['artifacts']['truth_sha256']}`",
            f"- Semgrep report SHA-256: `{report['artifacts']['semgrep_report_sha256']}`",
            f"- Harmonization SHA-256: `{report['artifacts']['harmonization_sha256']}`",
        ]
    )
    if report["artifacts"].get("rule_config_sha256"):
        lines.append(
            f"- Rule config SHA-256: `{report['artifacts']['rule_config_sha256']}`"
        )
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    truth = load_truth(args.expected)
    raw_detections, diagnostics = load_detections(args.semgrep_report)
    overrides, harmonization_document = load_harmonization(args.harmonization)
    harmonized_detections, applied = harmonize(raw_detections, overrides)

    report = {
        "metadata": {
            "benchmark": "OWASP Benchmark v1.2",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scanner": "semgrep",
            "scanner_version": args.scanner_version,
            "scanner_command": args.scanner_command,
            "source_commit": args.source_commit,
            "truth_test_count": len(truth),
            "vulnerable_test_count": sum(item.vulnerable for item in truth.values()),
            "non_vulnerable_test_count": sum(
                not item.vulnerable for item in truth.values()
            ),
            "fairness_controls": [
                "Ground truth is not supplied to the scanner.",
                "Harmonization contains no Benchmark test IDs or expected labels.",
                "Raw scanner CWE metadata and strict metrics are preserved.",
                "Findings are deduplicated at test ID and CWE before scoring.",
                "All CWE categories in expectedresults-1.2.csv are scored.",
            ],
        },
        "artifacts": {
            "truth": str(args.expected),
            "truth_sha256": sha256(args.expected),
            "semgrep_report": str(args.semgrep_report),
            "semgrep_report_sha256": sha256(args.semgrep_report),
            "harmonization": str(args.harmonization),
            "harmonization_sha256": sha256(args.harmonization),
            "rule_config": str(args.rule_config) if args.rule_config else None,
            "rule_config_sha256": sha256(args.rule_config)
            if args.rule_config
            else None,
        },
        "diagnostics": {
            **diagnostics,
            "harmonization_rules": len(overrides),
            "harmonization_applications_by_rule": dict(sorted(applied.items())),
            "harmonization_document": harmonization_document,
        },
        "strict": score(truth, raw_detections),
        "harmonized": score(truth, harmonized_detections),
    }

    args.output_dir.mkdir(parents=True, exist_ok=True)
    metrics_path = args.output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    write_csv(
        args.output_dir / "metrics.csv",
        report["strict"],
        report["harmonized"],
    )
    write_markdown(args.output_dir / "REPORT.md", report)
    print(json.dumps(report["harmonized"]["category_aligned_micro"], indent=2))
    print(f"output={args.output_dir}")


if __name__ == "__main__":
    main()
