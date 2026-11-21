from __future__ import annotations

from pathlib import Path

from app.models import StepRunResult
from app.scanners.code_snippet import enrich_with_code_snippets, format_snippet_for_log
from app.scanners.gitleaks_parser import parse_gitleaks_report
from app.utils.executable import resolve_executable
from app.utils.shell import run_command


def run_lightweight_security_scan(repo_dir: Path, log_file: Path, report_file: Path) -> StepRunResult:
    gitleaks_executable = resolve_executable("gitleaks")
    if not gitleaks_executable:
        return StepRunResult(
            status="failed",
            exit_code=127,
            summary_message=(
                "gitleaks not found. Install gitleaks and ensure it is available in PATH"
            ),
        )

    policy = Path(__file__).resolve().parents[1] / "policies"
    cmd = [
        gitleaks_executable,
        "detect",
        "--config", str(policy / "gitleaks.toml"),
        "--gitleaks-ignore-path", str(policy / "gitleaks.ignore"),
        "--ignore-gitleaks-allow",
        "--source",
        ".",
        "--report-format",
        "json",
        "--report-path",
        str(report_file),
    ]
    report_file.unlink(missing_ok=True)  # Never accept a stale report.
    result = run_command(command=cmd, cwd=repo_dir, log_file=log_file,
                         env={"GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "safe.directory",
                              "GIT_CONFIG_VALUE_0": str(repo_dir.resolve())})

    if result.exit_code not in (0, 1):
        if result.exit_code == 127:
            return StepRunResult(
                status="failed",
                exit_code=result.exit_code,
                summary_message=(
                    "gitleaks not found. Install gitleaks and ensure it is available in PATH"
                ),
            )

        return StepRunResult(
            status="failed",
            exit_code=result.exit_code,
            summary_message="gitleaks execution failed",
        )

    try:
        summary, findings = parse_gitleaks_report(report_file)
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as exc:
        return StepRunResult(status="failed", exit_code=2,
                             summary_message="gitleaks report invalid or incomplete: " + type(exc).__name__)
    if result.exit_code == 1 and not findings:
        return StepRunResult(status="failed", exit_code=1,
                             summary_message="gitleaks exited with findings/error code but report is empty")
    enrich_with_code_snippets(findings, repo_dir, gitleaks_report=report_file)
    found_count = len(findings)

    _log_gitleaks_findings(log_file, findings)

    if found_count > 0:
        return StepRunResult(
            status="success",
            exit_code=0,
            summary_message=(
                f"gitleaks found {found_count} secret(s) — auto-classified as Critical (security_gate decides)"
            ),
            security_summary=summary,
            security_findings=findings,
        )

    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message="gitleaks passed with 0 findings",
        security_summary=summary,
        security_findings=findings,
    )


def _log_gitleaks_findings(log_file: Path, findings: list) -> None:
    from app.utils.logger import append_log

    if not findings:
        append_log(log_file, "[gitleaks] No secrets detected.")
        return

    append_log(log_file, f"[gitleaks] {len(findings)} secret(s) found:")
    for i, f in enumerate(findings, 1):
        append_log(log_file, f"  [{i}] rule={f.rule_id} | {f.file_path}:{f.line_number} | {f.title}")
        if f.code_snippet and f.code_snippet_start_line:
            append_log(
                log_file,
                f"      [CODE-SNIPPET] {format_snippet_for_log(f.code_snippet, f.code_snippet_start_line)}",
            )
