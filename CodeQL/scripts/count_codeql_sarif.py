#!/usr/bin/env python3
"""Count CodeQL SARIF findings for the paper baseline experiment."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def _tags_for_rule(rule: dict[str, Any]) -> list[str]:
    tags = []
    properties = rule.get("properties") or {}
    for key in ("tags", "precision", "security-severity"):
        value = properties.get(key)
        if isinstance(value, list):
            tags.extend(str(item) for item in value)
        elif value is not None:
            tags.append(str(value))
    return tags


def _cwes_for_rule(rule: dict[str, Any]) -> list[str]:
    cwes = set()
    for tag in _tags_for_rule(rule):
        lowered = tag.lower()
        if lowered.startswith("external/cwe/cwe-"):
            cwes.add("CWE-" + lowered.rsplit("-", 1)[-1])
        elif lowered.startswith("cwe-"):
            cwes.add("CWE-" + lowered.split("cwe-", 1)[1].upper())
    return sorted(cwes)


def _level_for_result(result: dict[str, Any], rule: dict[str, Any] | None) -> str:
    if result.get("level"):
        return str(result["level"])
    if rule:
        default_config = rule.get("defaultConfiguration") or {}
        if default_config.get("level"):
            return str(default_config["level"])
    return "none"


def collect_counts(sarif_dir: Path) -> dict[str, Any]:
    sarif_files = sorted(sarif_dir.rglob("*.sarif")) if sarif_dir.exists() else []
    total_results = 0
    level_counts: Counter[str] = Counter()
    rule_counts: Counter[str] = Counter()
    cwe_counts: Counter[str] = Counter()

    for sarif_file in sarif_files:
        with sarif_file.open("r", encoding="utf-8") as fp:
            sarif = json.load(fp)

        for run in sarif.get("runs", []):
            rules_by_id = {
                rule.get("id"): rule
                for tool in [run.get("tool") or {}]
                for driver in [tool.get("driver") or {}]
                for rule in driver.get("rules", [])
                if rule.get("id")
            }

            for result in run.get("results", []):
                total_results += 1
                rule_id = str(result.get("ruleId") or "unknown")
                rule = rules_by_id.get(rule_id)
                rule_counts[rule_id] += 1
                level_counts[_level_for_result(result, rule)] += 1
                for cwe in _cwes_for_rule(rule or {}):
                    cwe_counts[cwe] += 1

    return {
        "sarif_files": [str(path) for path in sarif_files],
        "sarif_file_count": len(sarif_files),
        "total_findings": total_results,
        "levels": dict(sorted(level_counts.items())),
        "cwes": dict(sorted(cwe_counts.items())),
        "top_rules": dict(rule_counts.most_common(20)),
    }


def render_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "",
        "### CodeQL finding count",
        "",
        "| Target | Repository | Ref | Language | SARIF files | Total findings | Elapsed seconds |",
        "| --- | --- | --- | --- | ---: | ---: | ---: |",
        (
            f"| {summary['target_id']} | `{summary['repository']}` | `{summary['ref']}` | "
            f"`{summary['language']}` | {summary['sarif_file_count']} | "
            f"{summary['total_findings']} | {summary['elapsed_seconds']} |"
        ),
        "",
        "#### Findings by level",
        "",
        "| Level | Count |",
        "| --- | ---: |",
    ]
    levels = summary.get("levels") or {"none": 0}
    lines.extend(f"| {level} | {count} |" for level, count in levels.items())

    lines.extend(["", "#### Findings by CWE", "", "| CWE | Count |", "| --- | ---: |"])
    cwes = summary.get("cwes") or {"unmapped": 0}
    lines.extend(f"| {cwe} | {count} |" for cwe, count in cwes.items())
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sarif-dir", required=True, type=Path)
    parser.add_argument("--target-id", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--ref", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--elapsed-seconds", required=True, type=int)
    parser.add_argument("--json-out", required=True, type=Path)
    parser.add_argument("--md-out", required=True, type=Path)
    args = parser.parse_args()

    summary = collect_counts(args.sarif_dir)
    summary.update(
        {
            "target_id": args.target_id,
            "repository": args.repository,
            "ref": args.ref,
            "language": args.language,
            "elapsed_seconds": args.elapsed_seconds,
        }
    )

    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.md_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.md_out.write_text(render_markdown(summary), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
