#!/usr/bin/env python3
"""Build a redacted supplementary archive for the web-DT KCI manuscript.

Raw scanner outputs are represented by the frozen SHA-256 manifest. Normalized
findings are included only after code snippets and AI text are removed. This
avoids redistributing candidate secret values while preserving the fields used
for the paper's aggregate analyses.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "웹기반DT_KCI_재현성자료.zip"
HASH_MANIFEST = ROOT / "analysis/reproducibility/experiment_output_sha256.csv"
BENCHMARK_RUN = "run-20260624-017"

STATIC_FILES = (
    "analysis/reproducibility/experiment_manifest.json",
    "analysis/reproducibility/experiment_output_sha256.csv",
    "analysis/reproducibility/gitleaks-default-v8.21.2.toml",
    "analysis/reproducibility/semgrep-auto-rules-20260723.json",
    "analysis/policy_catalog_with_observed_rules.csv",
    "analysis/benchmark_rule_error_analysis.csv",
    "analysis/dt_manual_validation_summary.json",
    "analysis/dt_revision_experiments.json",
    "analysis/dt_cluster_profile_sensitivity.json",
    "analysis/dt_repository_metadata.json",
    "analysis/dt_repository_metadata.csv",
    "scripts/analyze_kci_paper_results.py",
    "scripts/analyze_benchmark_rule_errors.py",
    "scripts/analyze_dt_revision_experiments.py",
    "scripts/analyze_dt_cluster_sensitivity.py",
    "scripts/finalize_dt_manual_validation.py",
    "scripts/build_reproducibility_manifest.py",
)

SENSITIVE_PATTERNS = (
    re.compile(rb"glpat-[A-Za-z0-9_-]{16,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"xox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def json_bytes(value: object) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def sanitize_findings(path: Path) -> bytes:
    findings = json.loads(path.read_text(encoding="utf-8"))
    for finding in findings:
        if "code_snippet" in finding:
            finding["code_snippet"] = "[REMOVED FROM SUPPLEMENT]"
        if "ai_recommendation" in finding:
            finding["ai_recommendation"] = None
        metadata = finding.get("metadata")
        if isinstance(metadata, dict):
            for key in list(metadata):
                if key.lower() in {
                    "secret",
                    "match",
                    "raw",
                    "snippet",
                    "lines",
                }:
                    metadata[key] = "[REMOVED FROM SUPPLEMENT]"
    return json_bytes(findings)


def sanitize_manual_csv(path: Path) -> bytes:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
        fieldnames = list(rows[0]) if rows else []
    for row in rows:
        if "code_context" in row:
            row["code_context"] = "[REMOVED FROM SUPPLEMENT]"
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + output.getvalue()).encode("utf-8")


def representative_runs() -> list[str]:
    with HASH_MANIFEST.open(encoding="utf-8-sig", newline="") as handle:
        return sorted({row["run_id"] for row in csv.DictReader(handle)})


def ensure_no_candidate_secrets(files: dict[str, bytes]) -> None:
    for name, data in files.items():
        if name in {
            "analysis/reproducibility/semgrep-auto-rules-20260723.json",
            "analysis/reproducibility/gitleaks-default-v8.21.2.toml",
        }:
            # Scanner definitions intentionally contain credential/key patterns.
            continue
        for pattern in SENSITIVE_PATTERNS:
            if pattern.search(data):
                raise AssertionError(f"candidate secret pattern remains in {name}")
        if name.endswith(".json"):
            text = data.decode("utf-8", errors="ignore")
            if re.search(r'"(?:Secret|Match)"\s*:', text):
                raise AssertionError(f"raw Gitleaks field remains in {name}")


def readme() -> bytes:
    return """# 웹 기반 DT KCI 논문 보조자료 S1

이 압축파일은 논문의 집계값과 재현성 정보를 검토하기 위한 제출용 보조자료이다.

포함 범위:
- 14개 공개 DT의 `pipeline_result.json`, `security_verdict.json`
- 코드 스니펫과 AI 권고문을 제거한 `security_findings.redacted.json`
- OWASP Benchmark v1.2 정답표와 비식별 정규화 탐지 결과
- 수동 판독 결과(코드 문맥 제거), 요약, 구성요소 제거·민감도·계보 분석 결과
- 고정 Semgrep 룰 번들, Gitleaks 설정, 정책 카탈로그
- 원시 산출물 SHA-256 목록과 분석 스크립트

보안상 원시 `gitleaks_report.json`과 코드 스니펫은 포함하지 않는다. 원시 결과의
동일성은 `analysis/reproducibility/experiment_output_sha256.csv`로 확인한다.
룰별 진단 수치는 `analysis/benchmark_rule_error_analysis.csv`에 보존되어 있다.

연구 코드 저장소: https://github.com/CapstoneLab/CICD-Engine
최종 게재본에는 원고 버전과 대응하는 릴리스 태그 또는 영구 보관 DOI를 추가해야 한다.
""".encode("utf-8")


def build() -> None:
    files: dict[str, bytes] = {"README.md": readme()}

    for relative in STATIC_FILES:
        path = ROOT / relative
        if not path.exists():
            raise FileNotFoundError(path)
        files[relative] = path.read_bytes()

    for relative in (
        "analysis/dt_manual_validation_candidates.csv",
        "analysis/dt_manual_validation_results.csv",
    ):
        files[relative] = sanitize_manual_csv(ROOT / relative)

    for run_id in representative_runs():
        run_dir = ROOT / "runs" / run_id
        for name in ("pipeline_result.json", "security_verdict.json"):
            path = run_dir / name
            if not path.exists():
                raise FileNotFoundError(path)
            files[f"runs/{run_id}/{name}"] = path.read_bytes()
        findings = run_dir / "security_findings.json"
        files[
            f"runs/{run_id}/security_findings.redacted.json"
        ] = sanitize_findings(findings)

    benchmark_truth = (
        ROOT
        / f"workspace/{BENCHMARK_RUN}/repo/expectedresults-1.2.csv"
    )
    benchmark_findings = ROOT / f"runs/{BENCHMARK_RUN}/security_findings.json"
    files[
        "benchmark/expectedresults-1.2.csv"
    ] = benchmark_truth.read_bytes()
    files[
        "benchmark/security_findings.redacted.json"
    ] = sanitize_findings(benchmark_findings)

    ensure_no_candidate_secrets(files)

    manifest = io.StringIO(newline="")
    writer = csv.writer(manifest)
    writer.writerow(["file", "sha256"])
    for name in sorted(files):
        writer.writerow([name, sha256_bytes(files[name])])
    files["SUPPLEMENT_SHA256.csv"] = (
        "\ufeff" + manifest.getvalue()
    ).encode("utf-8")

    with tempfile.NamedTemporaryFile(
        dir=OUTPUT.parent,
        prefix=OUTPUT.name + ".",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(
            temp_path,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name in sorted(files):
                info = zipfile.ZipInfo(name)
                info.date_time = (2026, 7, 25, 0, 0, 0)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, files[name])
        temp_path.replace(OUTPUT)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    with zipfile.ZipFile(OUTPUT) as archive:
        if bad_member := archive.testzip():
            raise AssertionError(f"corrupt supplementary member: {bad_member}")
        if len(archive.namelist()) != len(files):
            raise AssertionError("supplement file count mismatch")

    print(f"output={OUTPUT}")
    print(f"sha256={sha256_bytes(OUTPUT.read_bytes())}")
    print(f"files={len(files)} runs={len(representative_runs())}")
    print("redaction_check=passed")


if __name__ == "__main__":
    build()
