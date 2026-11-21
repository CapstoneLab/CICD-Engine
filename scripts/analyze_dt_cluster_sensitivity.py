#!/usr/bin/env python3
"""Collapse related DT repositories by code lineage for Fisher sensitivity."""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.analyze_kci_paper_results import (
    ENGINE_GENERATED_PATHS,
    POLICY_CWES,
    REPRESENTATIVE_RUNS,
    extract_cwe,
    fisher_exact_two_sided,
    read_json,
)


def main() -> None:
    metadata = json.loads((ROOT / "analysis/dt_repository_metadata.json").read_text())
    cluster_by_label = {row["repository_id"]: row["code_lineage_cluster"] for row in metadata}
    web_sets: list[set[int]] = []
    cluster_sets: dict[str, set[int]] = defaultdict(set)
    cluster_counts: dict[str, Counter[int]] = defaultdict(Counter)
    for group, label, run_id in REPRESENTATIVE_RUNS:
        if group not in {"A", "B"}:
            continue
        values: list[int] = []
        for finding in read_json(ROOT / "runs" / run_id / "security_findings.json"):
            if finding.get("in_scope") is not True:
                continue
            if str(finding.get("file_path", "")).removeprefix("./") in ENGINE_GENERATED_PATHS:
                continue
            cwe = extract_cwe(finding.get("cwe"))
            if cwe in POLICY_CWES:
                values.append(cwe)
        if group == "A":
            web_sets.append(set(values))
        else:
            cluster = cluster_by_label[label]
            cluster_sets[cluster].update(values)
            cluster_counts[cluster].update(values)

    targets = {
        "CWE-319": {319}, "CWE-79": {79}, "CWE-89": {89}, "CWE-798": {798},
        "Other policy CWEs": set(POLICY_CWES) - {319, 79, 89, 798},
    }
    result = {}
    dt_sets = list(cluster_sets.values())
    for label, target in targets.items():
        web = sum(bool(items & target) for items in web_sets)
        dt = sum(bool(items & target) for items in dt_sets)
        stats = fisher_exact_two_sided(dt, len(dt_sets) - dt, web, len(web_sets) - web)
        stats.update({"web_repositories": f"{web}/{len(web_sets)}", "dt_lineage_clusters": f"{dt}/{len(dt_sets)}"})
        result[label] = stats
    payload = {
        "dt_repository_count": 14,
        "dt_lineage_cluster_count": len(dt_sets),
        "clusters": {key: sorted(value) for key, value in sorted(cluster_sets.items())},
        "comparisons": result,
    }
    output = ROOT / "analysis/dt_cluster_profile_sensitivity.json"
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    print(f"output={output}")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
