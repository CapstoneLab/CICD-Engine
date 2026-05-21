from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from urllib import error, request

from app.models import PipelineRun
from app.utils.filesystem import save_json


def build_callback_payload(
    *,
    job_id: str,
    repo_url: str,
    branch: str,
    pipeline_run: PipelineRun,
    logs: list[str],
    security_summaries: list[dict[str, Any]] | None = None,
    security_findings: list[dict[str, Any]] | None = None,
    security_verdict: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "status": _normalize_status(pipeline_run.status),
        "repo_url": repo_url,
        "branch": branch,
        "started_at": pipeline_run.started_at,
        "ended_at": pipeline_run.finished_at,
        "logs": logs,
        "steps": [
            {
                "name": step.step_name,
                "status": step.status,
                "exit_code": step.exit_code,
                "summary": step.summary_message,
                "started_at": step.started_at,
                "finished_at": step.finished_at,
                "log_file": step.log_file,
            }
            for step in pipeline_run.steps
        ],
        "security": {
            "summaries": security_summaries or [],
            "findings": security_findings or [],
            "verdict": security_verdict,
        },
        "metadata": {
            "executor": "ubuntu-ci-engine",
            "run_id": pipeline_run.run_id,
            "workflow_name": pipeline_run.workflow_name,
            "workflow_source": pipeline_run.workflow_source,
        },
    }


def collect_logs(
    run_dir: Path,
    pipeline_run: PipelineRun | None = None,
    max_lines: int | None = None,
) -> list[str]:
    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        return []

    collected: list[str] = []

    ordered_log_files: list[Path] = []
    seen_names: set[str] = set()

    if pipeline_run:
        for step in pipeline_run.steps:
            if not step.log_file:
                continue

            file_name = Path(step.log_file).name
            candidate = logs_dir / file_name
            if not candidate.exists() or file_name in seen_names:
                continue

            ordered_log_files.append(candidate)
            seen_names.add(file_name)

    for log_file in sorted(logs_dir.glob("*.log")):
        if log_file.name in seen_names:
            continue
        ordered_log_files.append(log_file)
        seen_names.add(log_file.name)

    for log_file in ordered_log_files:
        try:
            lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        file_name = log_file.name
        for line in lines:
            collected.append(f"[{file_name}] {line}")

    if max_lines is None:
        return collected

    if len(collected) <= max_lines:
        return collected

    return collected[-max_lines:]


def save_callback_payload(run_dir: Path, payload: dict[str, Any]) -> Path:
    output_path = run_dir / "callback_result.json"
    save_json(output_path, payload)
    return output_path


def post_callback_with_retry(
    *,
    callback_url: str,
    callback_token: str,
    payload: dict[str, Any],
    retry_delays_sec: list[int] | None = None,
    timeout_sec: int = 10,
) -> tuple[bool, dict[str, Any]]:
    delays = retry_delays_sec or [5, 15, 30]
    attempts = 1 + len(delays)

    last_error = ""
    for attempt in range(1, attempts + 1):
        ok, detail = _post_once(
            callback_url=callback_url,
            callback_token=callback_token,
            payload=payload,
            timeout_sec=timeout_sec,
        )
        if ok:
            return True, {
                "attempts": attempt,
                "error": None,
                "http_status": detail,
            }

        last_error = detail
        if attempt <= len(delays):
            time.sleep(delays[attempt - 1])

    return False, {
        "attempts": attempts,
        "error": last_error,
        "http_status": None,
    }


def save_callback_delivery_result(run_dir: Path, result: dict[str, Any]) -> Path:
    output_path = run_dir / "callback_delivery.json"
    save_json(output_path, result)
    return output_path


def _post_once(
    *,
    callback_url: str,
    callback_token: str,
    payload: dict[str, Any],
    timeout_sec: int,
) -> tuple[bool, str]:
    body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        callback_url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "x-callback-token": callback_token,
        },
    )

    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            status_code = getattr(resp, "status", None)
            if status_code and 200 <= status_code < 300:
                return True, str(status_code)
            return False, f"non-2xx status: {status_code}"
    except error.HTTPError as exc:
        return False, f"http error {exc.code}: {exc.reason}"
    except error.URLError as exc:
        return False, f"url error: {exc.reason}"
    except Exception as exc:  # noqa: BLE001
        return False, f"unexpected error: {exc}"


def build_step_callback_payload(
    *,
    job_id: str,
    repo_url: str,
    branch: str,
    pipeline_run: PipelineRun,
    step: Any,
    step_log: list[str],
    step_security_summary: dict[str, Any] | None = None,
    step_security_findings: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "job_id": job_id,
        "type": "step_complete",
        "pipeline_status": _normalize_status(pipeline_run.status),
        "repo_url": repo_url,
        "branch": branch,
        "step": {
            "name": step.step_name,
            "status": step.status,
            "exit_code": step.exit_code,
            "summary": step.summary_message,
            "started_at": step.started_at,
            "finished_at": step.finished_at,
            "log_file": step.log_file,
            "logs": step_log,
            "security": {
                "summary": step_security_summary,
                "findings": step_security_findings or [],
            },
        },
        "metadata": {
            "executor": "ubuntu-ci-engine",
            "run_id": pipeline_run.run_id,
            "workflow_name": pipeline_run.workflow_name,
            "workflow_source": pipeline_run.workflow_source,
        },
    }


def post_step_callback(
    *,
    callback_url: str,
    callback_token: str,
    payload: dict[str, Any],
    timeout_sec: int = 10,
) -> tuple[bool, str]:
    return _post_once(
        callback_url=callback_url,
        callback_token=callback_token,
        payload=payload,
        timeout_sec=timeout_sec,
    )


def _normalize_status(status: str) -> str:
    if status in {"success", "failed", "running"}:
        return status
    if status == "queued":
        return "running"
    return "failed"
