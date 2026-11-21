from __future__ import annotations

import json
import os
import time
import threading

import httpx
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.models import PipelineRun
from app.utils.filesystem import save_json


MAX_CALLBACK_LOG_LINES = 250
MAX_CALLBACK_FINDINGS = 120
MAX_CALLBACK_SNIPPET_CHARS = 1200
MAX_CALLBACK_FIELD_CHARS = 4000


# step_name -> step_type for the backend's step-progress tracking.
_STEP_TYPE_MAP = {
    "clone": "clone",
    "install": "install",
    "test": "test",
    "build": "build",
    "deploy": "deploy",
    "security_gate": "security-gate",
    "lightweight-security": "security-light",
    "deep-security": "security-deep",
    "env_check": "env",
    "resolve_workflow": "workflow",
}


def _step_type(step_name: str) -> str:
    name = (step_name or "").lower()
    if name in _STEP_TYPE_MAP:
        return _STEP_TYPE_MAP[name]
    if "security" in name:
        return "security"
    if "build" in name:
        return "build"
    if "test" in name:
        return "test"
    if "deploy" in name:
        return "deploy"
    if "install" in name:
        return "install"
    return "command"


def _duration_secs(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at or not finished_at:
        return None
    try:
        start = datetime.fromisoformat(started_at)
        end = datetime.fromisoformat(finished_at)
    except ValueError:
        return None
    return round((end - start).total_seconds(), 1)


def _serialize_step(
    step: Any,
    *,
    step_order: int | None = None,
    total_steps: int | None = None,
    logs: list[str] | None = None,
) -> dict[str, Any]:
    """Backend-facing step shape. Keeps legacy fields and adds the backend's
    documented fields (step_name, step_type, duration_secs, error_message, metadata)."""
    error_message = None
    if step.status == "failed":
        parts = [step.summary_message] if step.summary_message else []
        if step.exit_code is not None:
            parts.append(f"exit code: {step.exit_code}")
        tail = next((line.strip() for line in reversed(logs or []) if line.strip()), "")
        if tail and tail not in "\n".join(parts):
            parts.append(tail[-2000:])
        error_message = "\n".join(parts)[:4000] or "Step failed without a reported reason"
    serialized = {
        "name": step.step_name,
        "step_name": step.step_name,
        "step_type": _step_type(step.step_name),
        "status": step.status,
        "exit_code": step.exit_code,
        "summary": step.summary_message,
        "error_message": error_message,
        "started_at": step.started_at,
        "finished_at": step.finished_at,
        "ended_at": step.finished_at,
        "duration_secs": _duration_secs(step.started_at, step.finished_at),
        "log_file": step.log_file,
        "metadata": {},
    }
    if step_order is not None:
        serialized["step_order"] = step_order
    if total_steps is not None:
        serialized["total_steps"] = total_steps
    return serialized


def _truncate_text(value: Any, max_chars: int) -> Any:
    if not isinstance(value, str) or len(value) <= max_chars:
        return value
    return f"{value[:max_chars]}...[truncated]"


def compact_security_findings(
    findings: list[dict[str, Any]] | None,
    *,
    max_items: int = MAX_CALLBACK_FINDINGS,
    max_snippet_chars: int = MAX_CALLBACK_SNIPPET_CHARS,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Shrink callback-only findings while preserving full artifacts on disk."""
    source = findings or []
    compacted: list[dict[str, Any]] = []
    snippets_truncated = 0
    fields_truncated = 0

    for finding in source[:max_items]:
        if not isinstance(finding, dict):
            continue

        item = dict(finding)
        snippet = item.get("code_snippet")
        truncated_snippet = _truncate_text(snippet, max_snippet_chars)
        if truncated_snippet != snippet:
            snippets_truncated += 1
            item["code_snippet"] = truncated_snippet

        for key in ("message", "ai_recommendation"):
            before = item.get(key)
            after = _truncate_text(before, MAX_CALLBACK_FIELD_CHARS)
            if after != before:
                fields_truncated += 1
                item[key] = after

        compacted.append(item)

    return compacted, {
        "security_findings_original_count": len(source),
        "security_findings_sent_count": len(compacted),
        "security_findings_truncated": len(source) > len(compacted),
        "security_snippets_truncated_count": snippets_truncated,
        "security_text_fields_truncated_count": fields_truncated,
    }


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
    deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    compact_findings, compact_metadata = compact_security_findings(security_findings)
    log_metadata = {
        "logs_sent_count": len(logs),
        "logs_max_lines": MAX_CALLBACK_LOG_LINES,
    }
    return {
        "job_id": job_id,
        "status": _normalize_status(pipeline_run.status),
        "repo_url": repo_url,
        "branch": branch,
        "started_at": pipeline_run.started_at,
        "ended_at": pipeline_run.finished_at,
        "logs": logs,
        "steps": [
            _serialize_step(step, step_order=index, total_steps=len(pipeline_run.steps),
                logs=[line for line in logs if line.startswith(f"[{step.step_name}.log]")])
            for index, step in enumerate(pipeline_run.steps, start=1)
        ],
        "security": {
            "summaries": security_summaries or [],
            "findings": compact_findings,
            "verdict": security_verdict,
        },
        "deployment": deployment,
        "metadata": {
            "executor": "ubuntu-ci-engine", "resume_id":os.getenv("CICD_RESUME_ID") or None,
            "run_id": pipeline_run.run_id,
            "workflow_name": pipeline_run.workflow_name,
            "workflow_source": pipeline_run.workflow_source,
            "truncated": {
                **log_metadata,
                **compact_metadata,
            },
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
    started = time.monotonic()
    delays = [5, 15, 30] if retry_delays_sec is None else retry_delays_sec
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
                "elapsed_seconds": round(time.monotonic() - started, 3),
                "attempts": attempt,
                "error": None,
                "http_status": detail,
            }

        last_error = detail
        if attempt <= len(delays):
            time.sleep(delays[attempt - 1])

    return False, {
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "attempts": attempts,
        "error": last_error,
        "http_status": None,
    }


def save_callback_delivery_result(run_dir: Path, result: dict[str, Any]) -> Path:
    output_path = run_dir / "callback_delivery.json"
    save_json(output_path, result)
    return output_path


_callback_clients = threading.local()


def _callback_client() -> httpx.Client:
    # Log delivery and step persistence run on separate threads. Their pools
    # must not block one another while each reuses its own HTTP connections.
    client = getattr(_callback_clients, "client", None)
    if client is None:
        client = httpx.Client(
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=2, keepalive_expiry=4),
            follow_redirects=False,
        )
        _callback_clients.client = client
    return client


def _post_once(
    *,
    callback_url: str,
    callback_token: str,
    payload: dict[str, Any],
    timeout_sec: int,
) -> tuple[bool, str]:
    resume_id = os.getenv("CICD_RESUME_ID")
    if resume_id:
        payload = {**payload, "metadata":{**(payload.get("metadata") or {}), "resume_id":resume_id}}
    headers = {"Content-Type": "application/json"}
    if callback_token:
        headers["x-callback-token"] = callback_token
    try:
        response = _callback_client().post(
            callback_url, content=json.dumps(payload).encode("utf-8"),
            headers=headers, timeout=timeout_sec,
        )
        if 200 <= response.status_code < 300:
            return True, str(response.status_code)
        return False, f"http error {response.status_code}: {response.reason_phrase}"
    except httpx.HTTPError as exc:
        return False, f"callback transport error: {exc}"
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
    deployment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    total_steps = len(pipeline_run.steps)
    step_order = next(
        (
            index
            for index, candidate in enumerate(pipeline_run.steps, start=1)
            if candidate is step
        ),
        None,
    )
    if step_order is None:
        step_order = next(
            (
                index
                for index, candidate in enumerate(pipeline_run.steps, start=1)
                if candidate.step_name == step.step_name
            ),
            None,
        )
    delivery_key = f"{job_id}:{step.step_name}:{step.finished_at or step.started_at or ''}"
    delivery_id = sha256(delivery_key.encode("utf-8")).hexdigest()
    return {
        "job_id": job_id,
        "type": "step_started" if step.status == "running" else "step_complete",
        "pipeline_status": _normalize_status(pipeline_run.status),
        "started_at": pipeline_run.started_at,
        "repo_url": repo_url,
        "branch": branch,
        "step": {
            **_serialize_step(step, step_order=step_order, total_steps=total_steps, logs=step_log),
            "delivery_id": delivery_id,
            "logs": step_log,
            "security": {
                "summary": step_security_summary,
                "findings": step_security_findings or [],
            },
        },
        "deployment": deployment,
        "metadata": {
            "executor": "ubuntu-ci-engine", "resume_id":os.getenv("CICD_RESUME_ID") or None,
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
    retry_delays_sec: list[int] | None = None,
) -> tuple[bool, str]:
    ok, result = post_callback_with_retry(
        callback_url=callback_url,
        callback_token=callback_token,
        payload=payload,
        timeout_sec=timeout_sec,
        retry_delays_sec=[1, 3, 10] if retry_delays_sec is None else retry_delays_sec,
    )
    if ok:
        return True, f"http {result['http_status']} after {result['attempts']} attempt(s)"
    return False, f"{result['error']} after {result['attempts']} attempt(s)"


def _normalize_status(status: str) -> str:
    if status in {"success", "failed", "running"}:
        return status
    if status == "queued":
        return "running"
    return "failed"
