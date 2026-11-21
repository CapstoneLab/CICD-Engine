from __future__ import annotations

from pathlib import Path
import yaml
from app.security_catalog import ALL_CWES, normalize_selected_cwes, normalize_cwe

from app.models import StepRunResult
from app.scanners.ai_recommender import generate_recommendations
from app.scanners.code_snippet import enrich_with_code_snippets, format_snippet_for_log
from app.scanners.semgrep_parser import parse_semgrep_report
from app.utils.executable import resolve_executable
from app.utils.shell import run_command


CRITICAL_CVSS_THRESHOLD = 9.0


def run_deep_security_scan(
    repo_dir: Path,
    log_file: Path,
    report_file: Path,
    ai_recommendation: bool = True,
    selected_items: list[str] | None = None,
) -> StepRunResult:
    selected = normalize_selected_cwes(selected_items)
    if selected == {"CWE-798"}:
        return StepRunResult(status="skipped", exit_code=0, summary_message="선택한 Secret 항목은 Gitleaks에서 검사했습니다")
    semgrep_executable = resolve_executable("semgrep")
    if not semgrep_executable:
        return StepRunResult(
            status="failed",
            exit_code=127,
            summary_message=(
                "semgrep not found. Install semgrep and ensure it is available in PATH"
            ),
        )

    semgrep_home = Path("/tmp") / "cicd-engine-semgrep-home"
    semgrep_home.mkdir(parents=True, exist_ok=True)

    policy = Path(__file__).resolve().parents[1] / "policies" / "semgrep-security-audit.yml"
    if selected != set(ALL_CWES):
        document = yaml.safe_load(policy.read_text(encoding="utf-8"))
        rules = []
        for rule in document["rules"]:
            metadata = rule.get("metadata") or {}
            cwes = metadata.get("cwe") or metadata.get("cwe_id") or []
            if not isinstance(cwes, list):
                cwes = [cwes]
            if any(normalize_cwe(cwe) in selected for cwe in cwes):
                rules.append(rule)
        if not rules:
            return StepRunResult(status="failed", exit_code=2, summary_message="선택 항목에 대응하는 SAST 규칙이 없습니다. 검사 범위를 확인하세요")
        policy = report_file.with_suffix(".rules.yml")
        policy.write_text(yaml.safe_dump({"rules": rules}, sort_keys=False), encoding="utf-8")
    cmd = [semgrep_executable, "--config", str(policy), "--disable-nosem", "--no-git-ignore",
           "--x-ignore-semgrepignore-files", "--metrics=off",
           "--exclude=node_modules", "--exclude=.venv", "--exclude=.git",
           "--json", "--output", str(report_file), "."]
    report_file.unlink(missing_ok=True)  # Never accept a stale report.
    result = run_command(
        command=cmd,
        cwd=repo_dir,
        log_file=log_file,
        env={
            "HOME": str(semgrep_home),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
            "XDG_CONFIG_HOME": str(semgrep_home / ".config"),
        },
    )

    if result.exit_code not in (0, 1):
        if result.exit_code == 127:
            return StepRunResult(
                status="failed",
                exit_code=result.exit_code,
                summary_message=(
                    "semgrep not found. Install semgrep and ensure it is available in PATH"
                ),
            )

        if "UnicodeEncodeError" in result.output:
            return StepRunResult(
                status="failed",
                exit_code=result.exit_code,
                summary_message="semgrep failed due to Windows encoding issue (see deep_security_scan.log)",
            )

        return StepRunResult(
            status="failed",
            exit_code=result.exit_code,
            summary_message="semgrep execution failed",
        )

    if "Traceback (most recent call last)" in result.output or not report_file.exists():
        return StepRunResult(
            status="failed",
            exit_code=result.exit_code or 1,
            summary_message="semgrep execution failed before producing a valid report",
        )

    try:
        summary, findings = parse_semgrep_report(report_file, selected_cwes=selected if selected != set(ALL_CWES) else None)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return StepRunResult(status="failed", exit_code=2,
                             summary_message="semgrep report invalid or incomplete: " + type(exc).__name__)
    if result.exit_code == 1 and not findings:
        return StepRunResult(status="failed", exit_code=1,
                             summary_message="semgrep exited with findings/error code but report is empty")
    if selected != set(ALL_CWES):
        findings = [f for f in findings if f.cwe in selected]
        counts = {level: sum(f.severity == level for f in findings) for level in ("critical", "high", "medium", "low")}
        for level, count in counts.items():
            setattr(summary, level + "_count", count)
        summary.max_detected_severity = next((level for level, count in counts.items() if count), "none")
        summary.max_cvss_score = max((f.cvss_score for f in findings if f.cvss_score is not None), default=None)
    enrich_with_code_snippets(findings, repo_dir)

    if ai_recommendation and findings:
        generate_recommendations(findings)

    _log_semgrep_findings(log_file, findings, summary)

    max_cvss = summary.max_cvss_score
    cvss_text = f"max_cvss={max_cvss:.1f}" if max_cvss is not None else "max_cvss=unavailable"
    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message=(
            "semgrep scan complete (security_gate decides): "
            f"critical={summary.critical_count}, high={summary.high_count}, "
            f"medium={summary.medium_count}, low={summary.low_count}, {cvss_text}"
        ),
        security_summary=summary,
        security_findings=findings,
    )


def _log_semgrep_findings(log_file: Path, findings: list, summary) -> None:
    from app.utils.logger import append_log

    total = len(findings)
    append_log(
        log_file,
        f"[semgrep] {total} finding(s): "
        f"critical={summary.critical_count}, high={summary.high_count}, "
        f"medium={summary.medium_count}, low={summary.low_count}",
    )

    if not findings:
        return

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda f: severity_order.get(f.severity, 4))

    for i, f in enumerate(sorted_findings, 1):
        cvss_str = f" | cvss={f.cvss_score:.1f}" if f.cvss_score is not None else ""
        append_log(
            log_file,
            f"  [{i}] [{f.severity.upper()}]{cvss_str} {f.rule_id} | "
            f"{f.file_path}:{f.line_number} | {f.message}",
        )
        if f.ai_recommendation:
            append_log(log_file, f"      [AI-FIX] {f.ai_recommendation}")
        if f.code_snippet and f.code_snippet_start_line:
            append_log(
                log_file,
                f"      [CODE-SNIPPET] {format_snippet_for_log(f.code_snippet, f.code_snippet_start_line)}",
            )
