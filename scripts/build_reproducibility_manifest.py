#!/usr/bin/env python3
"""Freeze tool/rule identities and build the 16-item observed-rule catalogue."""

from __future__ import annotations

import csv
import hashlib
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.security_catalog import CATALOG
RUNS = (
    ("DT1", "run-20260723-002"), ("DT2", "run-20260723-004"),
    ("DT3", "run-20260723-003"), ("DT4", "run-20260723-005"),
    ("DT5", "run-20260723-014"), ("DT6", "run-20260723-013"),
    ("DT7", "run-20260723-006"), ("DT8", "run-20260723-007"),
    ("DT9", "run-20260723-008"), ("DT10", "run-20260723-011"),
    ("DT11", "run-20260723-012"), ("DT12", "run-20260723-015"),
    ("DT13", "run-20260723-009"), ("DT14", "run-20260723-010"),
)
REQUIRED = (
    "pipeline_result.json", "security_verdict.json", "security_findings.json",
    "semgrep_report.json", "gitleaks_report.json",
)
RULE_BUNDLE = ROOT / "analysis/reproducibility/semgrep-auto-rules-20260723.json"
GITLEAKS_CONFIG = ROOT / "analysis/reproducibility/gitleaks-default-v8.21.2.toml"
GITLEAKS_BINARY = ROOT / ".venv/bin/gitleaks"
SEMGREP_CORE = Path("/home/capstone/.local/share/pipx/venvs/semgrep/lib/python3.14/site-packages/semgrep/bin/semgrep-core")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def semgrep_revision(metadata: dict) -> tuple[object, object]:
    rule = metadata.get("semgrep.dev", {}).get("rule", {}) if isinstance(metadata, dict) else {}
    return rule.get("rv_id"), rule.get("version_id")


def main() -> None:
    bundle = json.loads(RULE_BUNDLE.read_text(encoding="utf-8"))
    frozen_rules = {rule["id"]: rule for rule in bundle["rules"]}
    output_hashes: list[dict[str, str]] = []
    rule_counts: dict[str, Counter[str]] = defaultdict(Counter)
    scanners_by_cwe: dict[str, set[str]] = defaultdict(set)
    frozen_checks = Counter()

    for label, run_id in RUNS:
        run = ROOT / "runs" / run_id
        verdict = json.loads((run / "security_verdict.json").read_text())
        for name in REQUIRED:
            path = run / name
            output_hashes.append({
                "repository_id": label,
                "run_id": run_id,
                "commit": verdict["scanned_commit_sha"],
                "file": name,
                "sha256": sha256(path),
            })
        report = json.loads((run / "semgrep_report.json").read_text())
        for result in report.get("results", []):
            rule_id = result["check_id"]
            if rule_id not in frozen_rules:
                frozen_checks["missing_rule_id"] += 1
                continue
            frozen_checks["rule_id_present"] += 1
            old_revision = semgrep_revision(result.get("extra", {}).get("metadata", {}))
            frozen_revision = semgrep_revision(frozen_rules[rule_id].get("metadata", {}))
            if old_revision == frozen_revision and old_revision != (None, None):
                frozen_checks["revision_equal"] += 1
            elif old_revision == (None, None):
                frozen_checks["result_revision_unavailable"] += 1
            else:
                frozen_checks["revision_mismatch"] += 1
        findings = json.loads((run / "security_findings.json").read_text())
        for finding in findings:
            if finding.get("file_path") == ".localci/workflow.yml" or finding.get("in_scope") is not True:
                continue
            cwe = str(finding.get("cwe"))
            scanner = str(finding.get("scanner_name"))
            rule_id = str(finding.get("rule_id"))
            rule_counts[cwe][f"{scanner}:{rule_id}"] += 1
            scanners_by_cwe[cwe].add(scanner)

    policy_rows: list[dict[str, str]] = []
    grade_basis = {
        "critical": "정책상 즉시 차단: 명령·코드·DB 실행 또는 자격증명 노출",
        "high": "정책상 승인 필요: 보호 경계·전송·권한 검증 약화",
        "medium": "정책상 경고: 피해자 동작 또는 추가 조건이 필요한 입력 처리",
        "low": "정책상 보완: 정보 노출·쿠키·비밀번호 정책 강화",
    }
    for item in CATALOG:
        observed = rule_counts[item.cwe]
        top_rules = "; ".join(
            f"{rule} ({count})" for rule, count in observed.most_common(4)
        ) or "본 DT 표본에서 탐지 없음"
        policy_rows.append({
            "policy_item": item.name,
            "policy_key": item.key,
            "cwe": item.cwe,
            "policy_severity": item.grade,
            "per_finding_deduction": str(item.deduction),
            "scanner_observed": "+".join(sorted(scanners_by_cwe[item.cwe])) or "Semgrep 대상",
            "top_observed_rule_ids_in_14_dt": top_rules,
            "severity_assignment_basis": grade_basis[item.grade],
        })

    catalogue = ROOT / "analysis/policy_catalog_with_observed_rules.csv"
    with catalogue.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(policy_rows[0]))
        writer.writeheader()
        writer.writerows(policy_rows)

    hashes = ROOT / "analysis/reproducibility/experiment_output_sha256.csv"
    with hashes.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(output_hashes[0]))
        writer.writeheader()
        writer.writerows(output_hashes)

    manifest = {
        "experiment_date": "2026-07-23",
        "operating_system": "Ubuntu 26.04 LTS",
        "cpu": "Intel N95, 4 cores, up to 3.4 GHz",
        "memory": "7 GiB RAM",
        "semgrep": {
            "version": "1.157.0",
            "experiment_command": "semgrep --config auto --json --output <report> .",
            "frozen_core_rule_bundle": str(RULE_BUNDLE.relative_to(ROOT)),
            "frozen_rule_count": len(frozen_rules),
            "bundle_sha256": sha256(RULE_BUNDLE),
            "semgrep_core_sha256": sha256(SEMGREP_CORE),
            "core_defaults_observed": {"timeout_seconds": 5, "timeout_threshold": 3, "max_memory": 0, "engine": "OSS"},
            "frozen_bundle_crosscheck": dict(frozen_checks),
            "frozen_bundle_validation": "Semgrep core reproduced DT1's two structural findings from the archived rule bundle.",
        },
        "gitleaks": {
            "version": "8.21.2",
            "experiment_command": "gitleaks detect --source . --report-format json --report-path <report>",
            "frozen_default_config": str(GITLEAKS_CONFIG.relative_to(ROOT)),
            "config_sha256": sha256(GITLEAKS_CONFIG),
            "binary_sha256": sha256(GITLEAKS_BINARY),
            "explicit_config_validation": "DT4 produced the same 9 (rule,file,line,commit) findings; structural SHA-256 9e7ac31454a160d9e71411dcc81a7715b31f8e554fdc371def5d073980e45313.",
        },
        "path_handling": {
            "scanner_default": "VCS-tracked files and repository ignore files",
            "explicit_exclude_patterns": [],
            "analysis_only_exclusion": [".localci/workflow.yml (engine-generated orchestration file)"],
            "generated_test_example_files": "included in the automatic scan; classified separately during manual validation",
        },
        "raw_output_hash_manifest": str(hashes.relative_to(ROOT)),
        "policy_rule_catalog": str(catalogue.relative_to(ROOT)),
    }
    manifest_path = ROOT / "analysis/reproducibility/experiment_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"manifest={manifest_path}")
    print(f"catalogue={catalogue}")
    print(f"hashes={hashes}")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
