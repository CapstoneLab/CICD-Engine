from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _reexec_in_venv_if_needed() -> None:
    base_dir = Path(__file__).resolve().parent
    venv_python = base_dir / ".venv" / "bin" / "python"
    if not venv_python.exists():
        return
    if os.environ.get("LOCAL_CI_VENV_REEXEC") == "1":
        return
    venv_site = base_dir / ".venv" / "lib"
    already_in_venv = any(str(venv_site) in p for p in sys.path)
    if already_in_venv:
        return
    os.environ["LOCAL_CI_VENV_REEXEC"] = "1"
    os.execv(str(venv_python), [str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]])


_reexec_in_venv_if_needed()

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env")

from app.callback import (
    build_callback_payload,
    collect_logs,
    post_callback_with_retry,
    save_callback_delivery_result,
    save_callback_payload,
)
from app.orchestrator import LocalOrchestrator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local CI engine MVP")
    parser.add_argument("--job-id", default="", help="External job id from caller")
    parser.add_argument("--repo", required=True, help="Git repository URL")
    parser.add_argument("--branch", default="main", help="Branch name (default: main)")
    parser.add_argument(
        "--workflow",
        default="",
        help=(
            "Path to workflow YAML. Relative paths are resolved against cloned repository first, "
            "then engine root"
        ),
    )
    parser.add_argument("--callback-url", default="", help="Windows callback API URL")
    parser.add_argument("--callback-token", default="", help="Shared callback auth token")
    parser.add_argument(
        "--source",
        default="capstone",
        choices=["capstone", "mirae"],
        help=(
            "Request source. capstone: run both gitleaks + semgrep. "
            "mirae: skip gitleaks, run semgrep only"
        ),
    )
    parser.add_argument(
        "--environment",
        default="development",
        choices=["production", "staging", "development", "feature"],
        help=(
            "Deployment environment for security gate thresholds. "
            "production=85, staging=75, development=60, feature=50 minimum score"
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_dir = Path(__file__).resolve().parent
    branch = args.branch or "main"

    callback_url = args.callback_url.strip()
    callback_token = args.callback_token.strip()
    job_id = args.job_id.strip()

    orchestrator = LocalOrchestrator(
        base_dir=base_dir,
        callback_url=callback_url,
        callback_token=callback_token,
        job_id=job_id,
        source=args.source,
        environment=args.environment,
    )
    pipeline_run, run_dir = orchestrator.run(
        repo_url=args.repo,
        branch=branch,
        workflow_path=args.workflow or None,
    )

    security_summaries_data = _load_json_list(run_dir / "security_summary.json")
    security_findings_data = _load_json_list(run_dir / "security_findings.json")
    security_verdict_data = _load_json_object(run_dir / "security_verdict.json")

    deploy_endpoint = _load_json_object(run_dir / "deploy_endpoint.json")

    if callback_url:
        final_job_id = job_id or pipeline_run.run_id
        logs = collect_logs(run_dir, pipeline_run=pipeline_run)
        payload = build_callback_payload(
            job_id=final_job_id,
            repo_url=args.repo,
            branch=branch,
            pipeline_run=pipeline_run,
            logs=logs,
            security_summaries=security_summaries_data,
            security_findings=security_findings_data,
            security_verdict=security_verdict_data,
        )
        payload["type"] = "pipeline_complete"
        if deploy_endpoint:
            payload.setdefault("metadata", {})
            payload["metadata"]["service"] = deploy_endpoint

        callback_result_path = save_callback_payload(run_dir, payload)

        if callback_token:
            delivered, detail = post_callback_with_retry(
                callback_url=callback_url,
                callback_token=callback_token,
                payload=payload,
            )
            save_callback_delivery_result(
                run_dir,
                {
                    "delivered": delivered,
                    "callback_url": callback_url,
                    **detail,
                },
            )

            if delivered:
                print(f"callback delivered to {callback_url}")
            else:
                print("callback delivery failed after retries")
                print(f"local callback payload: {callback_result_path}")
        else:
            save_callback_delivery_result(
                run_dir,
                {
                    "delivered": False,
                    "callback_url": callback_url,
                    "attempts": 0,
                    "error": "missing callback token",
                    "http_status": None,
                },
            )
            print("callback skipped: callback token is missing")
            print(f"local callback payload: {callback_result_path}")

    print("\n=== Pipeline Result ===")
    result_file = run_dir / "pipeline_result.json"
    output_run_id = pipeline_run.run_id
    output_status = pipeline_run.status
    output_steps: list[dict[str, str]] = []

    try:
        payload = json.loads(result_file.read_text(encoding="utf-8"))
        if isinstance(payload, dict):
            output_run_id = str(payload.get("run_id") or output_run_id)
            output_status = str(payload.get("status") or output_status)

        steps = payload.get("steps", [])
        if isinstance(steps, list):
            for step in steps:
                if not isinstance(step, dict):
                    continue
                output_steps.append(
                    {
                        "step_name": str(step.get("step_name") or "unknown"),
                        "status": str(step.get("status") or "unknown"),
                        "summary": str(step.get("summary_message") or "no message"),
                    }
                )
    except Exception:
        output_steps = []

    print(f"run_id: {output_run_id}")
    print(f"status: {output_status}")
    print(f"result file: {result_file}")

    if output_steps:
        for step in output_steps:
            print(f"- {step['step_name']}: {step['status']} ({step['summary']})")
    else:
        for step in pipeline_run.steps:
            print(f"- {step.step_name}: {step.status} ({step.summary_message or 'no message'})")

    _print_security_verdict(security_verdict_data)
    _print_security_findings(security_findings_data)

    return 0 if pipeline_run.status == "success" else 1


def _load_json_list(file_path: Path) -> list[dict]:
    if not file_path.exists():
        return []
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def _load_json_object(file_path: Path) -> dict | None:
    if not file_path.exists():
        return None
    try:
        data = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _print_security_verdict(verdict: dict | None) -> None:
    if not verdict:
        return
    v = str(verdict.get("verdict", "")).upper()
    score = verdict.get("score", 0)
    env = verdict.get("environment", "?")
    counts = verdict.get("counts", {})
    print(f"\n=== Security Gate ===")
    print(f"verdict: {v} | score: {score} | environment: {env}")
    print(
        f"counts: critical={counts.get('critical',0)} high={counts.get('high',0)} "
        f"medium={counts.get('medium',0)} low={counts.get('low',0)}"
    )
    block_reasons = verdict.get("block_reasons") or []
    warn_reasons = verdict.get("warn_reasons") or []
    if block_reasons:
        print("BLOCK reasons:")
        for r in block_reasons:
            print(f"  - {r}")
    if warn_reasons:
        print("WARN reasons:")
        for r in warn_reasons:
            print(f"  - {r}")


def _print_security_findings(findings: list[dict]) -> None:
    if not findings:
        return

    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_findings = sorted(findings, key=lambda f: severity_order.get(str(f.get("severity", "")).lower(), 4))

    print(f"\n=== Security Findings ({len(sorted_findings)}) ===")
    for i, f in enumerate(sorted_findings, 1):
        severity = str(f.get("severity", "unknown")).upper()
        scanner = f.get("scanner_name", "unknown")
        rule_id = f.get("rule_id", "unknown")
        file_path = f.get("file_path", "")
        line_number = f.get("line_number", 0)
        message = f.get("message", "")
        cvss = f.get("cvss_score")
        ai_rec = f.get("ai_recommendation")

        header_bits = [f"[{severity}]"]
        if cvss is not None:
            header_bits.append(f"cvss={cvss:.1f}")
        header_bits.append(f"{scanner}:{rule_id}")
        print(f"\n[{i}] {' '.join(header_bits)}")
        print(f"    location: {file_path}:{line_number}")
        print(f"    issue: {message}")
        if ai_rec:
            print(f"    ai-fix: {ai_rec}")
        else:
            print("    ai-fix: (not generated — check ANTHROPIC_API_KEY or semgrep findings count)")


if __name__ == "__main__":
    sys.exit(main())
