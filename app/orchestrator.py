from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from app.policy_environment import effective_environment
from contextlib import nullcontext
from app.utils.sandbox import sandbox_commands, validate_repository
import json
import subprocess
from pathlib import Path
from typing import Any

from app.callback import build_step_callback_payload, collect_logs, post_step_callback
from app.constants import RUNTIME_TYPE
from app.models import PipelineRun, PipelineStep, SecurityFinding, SecuritySummary, StepRunResult, now_iso
from app.security_policy import (
    SecurityVerdict,
    normalize_environment,
    evaluate as evaluate_security_policy,
    format_summary,
    is_blocking,
)
from app.utils.env_requirements import find_missing_env_keys, provide_public_env_defaults
from app.steps.build import run_build
from app.steps.clone import run_clone
from app.steps.deep_security import run_deep_security_scan
from app.steps.deploy import run_deploy
from app.steps.install import run_install
from app.steps.lightweight_security import run_lightweight_security_scan
from app.steps.test import run_test
from app.utils.filesystem import data_root, make_run_id, prepare_run_paths, save_json
from app.utils.logger import append_log
from app.utils.shell import run_command
from app.workflow import WorkflowStepDefinition, resolve_workflow_definition
from app.security_catalog import normalize_selected_cwes
from app.security_workflow import validate_security_workflow, SECURITY_SCANS


def _resolve_head_sha(repo_dir: Path) -> str | None:
    """Actual commit SHA scanned (HEAD after clone/checkout). None if unknown."""
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = proc.stdout.strip()
    return sha or None


class LocalOrchestrator:
    def __init__(
        self,
        base_dir: Path,
        callback_url: str = "",
        callback_token: str = "",
        job_id: str = "",
        source: str = "capstone",
        environment: str = "development",
        selected_items: list[str] | None = None,
        commit_sha: str | None = None,
        approved_cwes: list[str] | None = None,
        repo_token: str | None = None,
        resume_run_id: str | None = None,
        approval_note: str | None = None,
    ) -> None:
        self._resume_run_id = resume_run_id
        self._approval_note = approval_note
        self.base_dir = base_dir
        self._current_runtime_type: str = RUNTIME_TYPE
        self._callback_url = callback_url
        self._callback_token = callback_token
        self._job_id = job_id
        self._source = source
        self._environment = effective_environment(environment)
        # selected_items from the caller (backend job payload / CLI). Takes
        # precedence over any selected_items declared in the workflow yml.
        self._selected_items_override = selected_items
        self._effective_selected_items: list[str] | None = selected_items
        # requested commit to scan; actual scanned commit captured after clone
        self._commit_sha = (commit_sha or "").strip() or None
        self._scanned_commit_sha: str | None = None
        # High CWEs accepted via backend approval -> waived at the gate
        self._approved_cwes = approved_cwes or []
        # OAuth/PAT token for cloning private repos; masked in logs by run_command
        self._repo_token = (repo_token or "").strip() or None
        self._security_verdict: SecurityVerdict | None = None
        self._gate_findings: list[dict[str, Any]] = []
        self._callback_executor = None
        self._callback_futures = []

    def _store_log_file(self, log_file: Path) -> str:
        """Return a portable log reference relative to the persistent data root."""
        return str(log_file.relative_to(data_root(self.base_dir)))

    def _resolve_log_file(self, log_file: str) -> Path:
        """Resolve current data-root references while accepting legacy absolute paths."""
        path = Path(log_file)
        if path.is_absolute():
            return path
        return data_root(self.base_dir) / path

    def _flush_callbacks(self):
        for future in self._callback_futures:
            future.result()
        self._callback_futures.clear()

    def run(self, repo_url: str, branch: str | None, workflow_path: str | None = None) -> tuple[PipelineRun, Path]:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="stage-report") as executor:
            self._callback_executor = executor
            try:
                result = self._run(repo_url, branch, workflow_path)
                self._flush_callbacks()
                return result
            finally:
                self._callback_executor = None

    def _run(self, repo_url: str, branch: str | None, workflow_path: str | None = None) -> tuple[PipelineRun, Path]:
        if self._resume_run_id:
            from app.resume import resume_run
            return resume_run(self, repo_url, branch, workflow_path)
        run_id = make_run_id(self.base_dir)
        paths = prepare_run_paths(base_dir=self.base_dir, run_id=run_id)
        run_dir = paths["run_dir"]
        logs_dir = paths["logs_dir"]
        repo_dir = paths["repo_dir"]

        pipeline_run = PipelineRun(
            run_id=run_id,
            repo_url=repo_url,
            branch=branch,
            runtime_type=RUNTIME_TYPE,
            steps=[PipelineStep(step_name="clone")],
        )

        security_summaries: list[SecuritySummary] = []
        security_findings: list[SecurityFinding] = []
        has_failure = False

        self._write_pipeline_result(run_dir, pipeline_run)

        pipeline_run.status = "running"
        pipeline_run.started_at = now_iso()
        self._write_pipeline_result(run_dir, pipeline_run)

        clone_step = pipeline_run.steps[0]
        clone_result = self._run_and_record_step(
            pipeline_run=pipeline_run,
            step=clone_step,
            repo_url=repo_url,
            branch=branch,
            repo_dir=repo_dir,
            run_dir=run_dir,
            logs_dir=logs_dir,
            step_definition=None,
        )

        if clone_result.status == "failed":
            pipeline_run.status = "failed"
            pipeline_run.finished_at = now_iso()
            pipeline_run.current_step = clone_step.step_name
            self._write_security_results(run_dir, security_summaries, security_findings)
            self._write_pipeline_result(run_dir, pipeline_run)
            return pipeline_run, run_dir

        env_check_result = self._check_required_env(repo_dir, logs_dir)
        if env_check_result is not None:
            env_step = PipelineStep(step_name="env_check")
            pipeline_run.steps.append(env_step)
            env_step.log_file = self._store_log_file(logs_dir / "env_check.log")
            env_step.started_at = now_iso()
            self._record_step_result(
                pipeline_run=pipeline_run,
                run_dir=run_dir,
                step=env_step,
                result=env_check_result,
                repo_url=repo_url,
                branch=branch,
            )
            if env_check_result.status == "failed":
                pipeline_run.status = "failed"
                pipeline_run.finished_at = now_iso()
                pipeline_run.current_step = env_step.step_name
                self._write_security_results(run_dir, security_summaries, security_findings)
                self._write_pipeline_result(run_dir, pipeline_run)
                return pipeline_run, run_dir

        try:
            workflow = resolve_workflow_definition(
                repo_dir=repo_dir,
                base_dir=self.base_dir,
                workflow_path=workflow_path,
            )
            validate_security_workflow(workflow.steps)
        except Exception as exc:  # noqa: BLE001
            resolve_step = PipelineStep(step_name="resolve_workflow")
            pipeline_run.steps.append(resolve_step)
            self._record_step_result(
                pipeline_run=pipeline_run,
                run_dir=run_dir,
                step=resolve_step,
                result=StepRunResult(
                    status="failed",
                    exit_code=1,
                    summary_message=f"Workflow resolution failed: {exc}",
                ),
                repo_url=repo_url,
                branch=branch,
            )
            pipeline_run.status = "failed"
            pipeline_run.finished_at = now_iso()
            pipeline_run.current_step = resolve_step.step_name
            self._write_security_results(run_dir, security_summaries, security_findings)
            self._write_pipeline_result(run_dir, pipeline_run)
            return pipeline_run, run_dir

        pipeline_run.runtime_type = workflow.runtime_type
        pipeline_run.workflow_name = workflow.name
        pipeline_run.workflow_source = workflow.source
        self._current_runtime_type = workflow.runtime_type

        # selected items precedence: caller override (payload/CLI) > workflow yml > all 16
        self._effective_selected_items = (
            self._selected_items_override
            if self._selected_items_override is not None
            else workflow.selected_items
        )

        active_step_definitions = [
            sd for sd in workflow.steps if not self._should_skip_step_for_source(sd)
        ]

        workflow_steps = [
            PipelineStep(
                step_name=step_definition.name,
                continue_on_failure=step_definition.continue_on_failure,
            )
            for step_definition in active_step_definitions
        ]
        pipeline_run.steps.extend(workflow_steps)
        self._write_pipeline_result(run_dir, pipeline_run)

        for step, step_definition in zip(workflow_steps, active_step_definitions):
            result = self._run_and_record_step(
                pipeline_run=pipeline_run,
                step=step,
                repo_url=repo_url,
                branch=branch,
                repo_dir=repo_dir,
                run_dir=run_dir,
                logs_dir=logs_dir,
                step_definition=step_definition,
            )

            if result.security_summary:
                security_summaries.append(result.security_summary)
            if result.security_findings:
                security_findings.extend(result.security_findings)

            if result.status == "failed":
                has_failure = True
                if not step.continue_on_failure or step_definition.uses in SECURITY_SCANS:
                    self._mark_remaining_steps_skipped(
                        pipeline_run=pipeline_run,
                        run_dir=run_dir, repo_url=repo_url, branch=branch,
                        remaining_steps=workflow_steps[workflow_steps.index(step) + 1 :],
                        reason=f"Skipped because previous step failed: {step.step_name}",
                    )
                    pipeline_run.status = "failed"
                    pipeline_run.finished_at = now_iso()
                    pipeline_run.current_step = step.step_name
                    self._write_security_results(run_dir, security_summaries, security_findings)
                    self._write_pipeline_result(run_dir, pipeline_run)
                    return pipeline_run, run_dir

            if step_definition.kind == "builtin" and step_definition.uses == "deep_security_scan":
                gate_result = self._run_security_gate(
                    pipeline_run=pipeline_run,
                    findings=security_findings,
                    logs_dir=logs_dir,
                    run_dir=run_dir,
                    repo_url=repo_url,
                    branch=branch,
                )
                if gate_result.status == "failed":
                    if self._security_verdict.requires_approval:
                        from app.resume import save_checkpoint
                        save_checkpoint(self, run_dir, repo_dir, workflow)
                    has_failure = True
                    self._mark_remaining_steps_skipped(
                        pipeline_run=pipeline_run,
                        run_dir=run_dir, repo_url=repo_url, branch=branch,
                        remaining_steps=workflow_steps[workflow_steps.index(step) + 1 :],
                        reason="Skipped because security_gate blocked the pipeline",
                    )
                    pipeline_run.status = "failed"
                    pipeline_run.finished_at = now_iso()
                    pipeline_run.current_step = "security_gate"
                    self._write_security_results(run_dir, security_summaries, security_findings)
                    self._write_pipeline_result(run_dir, pipeline_run)
                    return pipeline_run, run_dir

        pipeline_run.status = "failed" if has_failure else "success"
        pipeline_run.finished_at = now_iso()
        pipeline_run.current_step = None
        self._write_security_results(run_dir, security_summaries, security_findings)
        self._write_pipeline_result(run_dir, pipeline_run)
        return pipeline_run, run_dir

    def _run_and_record_step(
        self,
        pipeline_run: PipelineRun,
        step: PipelineStep,
        repo_url: str,
        branch: str | None,
        repo_dir: Path,
        run_dir: Path,
        logs_dir: Path,
        step_definition: WorkflowStepDefinition | None,
    ) -> StepRunResult:
        pipeline_run.current_step = step.step_name
        step.status = "running"
        step.started_at = now_iso()
        step.log_file = self._store_log_file(logs_dir / f"{step.step_name}.log")
        self._write_pipeline_result(run_dir, pipeline_run)

        self._send_step_callback(pipeline_run, run_dir, step, repo_url, branch)

        try:
            untrusted = step_definition and (step_definition.kind == "command" or step_definition.uses in {"install", "test", "build"})
            with sandbox_commands(repo_dir) if untrusted else nullcontext():
                result = self._execute_step(
                    step_name=step.step_name,
                    repo_url=repo_url,
                    branch=branch,
                    repo_dir=repo_dir,
                    run_dir=run_dir,
                    logs_dir=logs_dir,
                    step_definition=step_definition,
                )
        except Exception as exc:  # noqa: BLE001
            result = StepRunResult(
                status="failed",
                exit_code=1,
                summary_message=f"Unhandled exception: {exc}",
            )

        self._record_step_result(
            pipeline_run=pipeline_run,
            run_dir=run_dir,
            step=step,
            result=result,
            repo_url=repo_url,
            branch=branch,
        )
        return result

    def _record_step_result(
        self,
        pipeline_run: PipelineRun,
        run_dir: Path,
        step: PipelineStep,
        result: StepRunResult,
        repo_url: str = "",
        branch: str | None = None,
    ) -> None:
        step.finished_at = now_iso()
        step.status = result.status
        step.exit_code = result.exit_code
        step.summary_message = result.summary_message

        if step.log_file:
            step_log_path = self._resolve_log_file(step.log_file)
            append_log(step_log_path, f"[step_status] {step.status}")
            append_log(step_log_path, f"[step_summary] {step.summary_message or 'no message'}")
            append_log(step_log_path, f"[step_exit_code] {step.exit_code if step.exit_code is not None else 'null'}")

        self._write_pipeline_result(run_dir, pipeline_run)
        self._send_step_callback(pipeline_run, run_dir, step, repo_url, branch, result)

    def _send_step_callback(
        self,
        pipeline_run: PipelineRun,
        run_dir: Path,
        step: PipelineStep,
        repo_url: str,
        branch: str | None,
        result: StepRunResult | None = None,
    ) -> None:
        if not self._callback_url:
            return

        step_log: list[str] = []
        if step.log_file:
            log_path = self._resolve_log_file(step.log_file)
            if log_path.exists():
                try:
                    step_log = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    pass

        step_security_summary = None
        step_security_findings: list[dict[str, Any]] = []
        if result is not None:
            if result.security_summary:
                step_security_summary = result.security_summary.to_dict()
            if result.security_findings:
                step_security_findings = [item.to_dict() for item in result.security_findings]

        job_id = self._job_id or pipeline_run.run_id
        payload = build_step_callback_payload(
            job_id=job_id,
            repo_url=repo_url,
            branch=branch or "main",
            pipeline_run=pipeline_run,
            step=step,
            step_log=step_log,
            step_security_summary=step_security_summary,
            step_security_findings=step_security_findings,
            deployment=self._load_deployment_result(run_dir) if step.step_name == "deploy" else None,
        )

        if self._scanned_commit_sha:
            payload["step"]["metadata"]["commit_sha"] = self._scanned_commit_sha
        if step.step_name == "security_gate" and self._security_verdict is not None:
            payload["step"]["metadata"]["security_gate"] = {
                "verdict": self._security_verdict.verdict,
                "requires_approval": self._security_verdict.requires_approval,
                "scanned_commit_sha": self._scanned_commit_sha,
                "policy_version": self._security_verdict.policy_version,
                "findings": self._gate_findings,
            }

        # Build the immutable payload before returning to the execution thread.
        # Report in order, while independent execution proceeds without network waits.
        if self._callback_executor is not None and step.step_name != "deploy":
            for future in self._callback_futures:
                if future.done():
                    future.result()
            self._callback_futures.append(self._callback_executor.submit(
                self._deliver_step_callback, payload, run_dir))
        else:
            # Deployment must wait for persisted scan evidence and server approval.
            self._flush_callbacks()
            self._deliver_step_callback(payload, run_dir)

    def _deliver_step_callback(self, payload, run_dir):
        callback_started = time.monotonic()
        ok, detail = post_step_callback(
            callback_url=self._callback_url, callback_token=self._callback_token, payload=payload)
        step = payload["step"]
        with (run_dir / "callback_timings.jsonl").open("a", encoding="utf-8") as timing_file:
            timing_file.write(json.dumps({"step": step["step_name"], "status": step["status"],
                "elapsed_seconds": round(time.monotonic() - callback_started, 3), "ok": ok,
                "detail": detail}) + "\n")
        if not ok:
            raise RuntimeError(f"Step report could not be persisted: {step['step_name']} ({detail})")

    @staticmethod
    def _load_deployment_result(run_dir: Path) -> dict[str, Any] | None:
        for name in ("deployment_result.json", "deploy_endpoint.json"):
            path = run_dir / name
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(data, dict):
                return data
        return None

    def _mark_remaining_steps_skipped(
        self,
        pipeline_run: PipelineRun,
        remaining_steps: list[PipelineStep],
        reason: str,
        run_dir: Path,
        repo_url: str,
        branch: str | None,
    ) -> None:
        for step in remaining_steps:
            if step.status != "pending":
                continue
            step.status = "skipped"
            step.finished_at = now_iso()
            step.exit_code = 0
            step.summary_message = reason
            self._send_step_callback(pipeline_run, run_dir, step, repo_url, branch)

    def _execute_step(
        self,
        step_name: str,
        repo_url: str,
        branch: str | None,
        repo_dir: Path,
        run_dir: Path,
        logs_dir: Path,
        step_definition: WorkflowStepDefinition | None,
    ) -> StepRunResult:
        log_file = logs_dir / f"{step_name}.log"

        if step_name == "clone":
            clone_result = run_clone(
                repo_url=repo_url,
                branch=branch,
                repo_dir=repo_dir,
                log_file=log_file,
                commit_sha=self._commit_sha,
                repo_token=self._repo_token,
            )
            if clone_result.status == "success":
                validate_repository(repo_dir)
                self._scanned_commit_sha = _resolve_head_sha(repo_dir)
            return clone_result

        if not step_definition:
            return StepRunResult(
                status="failed",
                exit_code=1,
                summary_message=f"Unknown step: {step_name}",
            )

        if step_definition.kind == "builtin":
            return self._execute_builtin_step(
                step_definition=step_definition,
                repo_dir=repo_dir,
                run_dir=run_dir,
                log_file=log_file,
                repo_url=repo_url,
                branch=branch,
                runtime_type=self._current_runtime_type,
            )

        if step_definition.kind == "command":
            return self._execute_command_step(
                step_definition=step_definition,
                repo_dir=repo_dir,
                log_file=log_file,
            )

        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message=f"Unsupported step kind: {step_definition.kind}",
        )

    def _resolve_project_dir(
        self,
        repo_dir: Path,
        step_definition: WorkflowStepDefinition,
    ) -> tuple[Path, StepRunResult | None]:
        """Resolve the project directory for a lifecycle builtin from step.cwd.

        Defaults to the repo root. Validates the resolved path stays inside the
        repo and exists. Returns (project_dir, error_result|None)."""
        cwd = (step_definition.cwd or ".").strip() or "."
        if cwd != ".":
            # Explicit cwd from the workflow: validate and respect it as-is.
            repo_root = repo_dir.resolve()
            project_dir = (repo_dir / cwd).resolve()
            if not project_dir.is_relative_to(repo_root):
                return repo_dir, StepRunResult(
                    status="failed",
                    exit_code=1,
                    summary_message=f"Step '{step_definition.name}' cwd escapes repository root: {cwd}",
                )
            if not project_dir.is_dir():
                return repo_dir, StepRunResult(
                    status="failed",
                    exit_code=1,
                    summary_message=f"Step '{step_definition.name}' cwd not found: {cwd}",
                )
            return project_dir, None

        # No explicit cwd: auto-descend for monorepos when the root has no
        # project for this runtime (e.g. package.json lives in web-server/).
        detected, ambiguous = self._autodetect_project_subdir(repo_dir, self._current_runtime_type)
        if ambiguous:
            return repo_dir, StepRunResult(
                status="failed",
                exit_code=1,
                summary_message=(
                    f"Step '{step_definition.name}': monorepo with multiple candidate "
                    f"projects ({', '.join(ambiguous)}). Set 'cwd' in the workflow to pick one."
                ),
            )
        return detected, None

    def _autodetect_project_subdir(
        self,
        repo_dir: Path,
        runtime_type: str,
    ) -> tuple[Path, list[str] | None]:
        """Return (project_dir, ambiguous_candidates).

        If the repo root already has a project marker for the runtime, returns
        the root. Otherwise scans immediate subdirectories: exactly one match →
        that dir; multiple → prefer a backend-like node app (has a server entry,
        not a frontend), else report the candidates as ambiguous.
        """
        markers = {
            "node": ["package.json"],
            "python": ["requirements.txt", "pyproject.toml", "setup.py"],
            "java": ["pom.xml", "build.gradle", "build.gradle.kts"],
        }.get(runtime_type, ["package.json"])

        def has_marker(d: Path) -> bool:
            return any((d / m).exists() for m in markers)

        if has_marker(repo_dir):
            return repo_dir, None

        skip = {"node_modules", ".git", "dist", "build", "out", "target", ".venv", "__pycache__"}
        candidates = [
            d for d in sorted(repo_dir.iterdir())
            if d.is_dir() and not d.name.startswith(".") and d.name not in skip and has_marker(d)
        ]
        if not candidates:
            return repo_dir, None
        if len(candidates) == 1:
            return candidates[0], None

        # Multiple candidates: prefer a node backend (has a server entry file
        # and is not a frontend SPA). Disambiguates frontend/ vs web-server/.
        if runtime_type == "node":
            backend_like = [d for d in candidates if self._looks_like_node_backend(d)]
            if len(backend_like) == 1:
                return backend_like[0], None

        return repo_dir, [d.name for d in candidates]

    @staticmethod
    def _looks_like_node_backend(d: Path) -> bool:
        server_entries = ("server.js", "app.js", "index.js", "main.js", "server.ts", "app.ts")
        has_server = any((d / f).exists() for f in server_entries)
        frontend_markers = ("vite.config.js", "vite.config.ts", "angular.json", "index.html")
        is_frontend = any((d / f).exists() for f in frontend_markers)
        return has_server and not is_frontend

    def _execute_builtin_step(
        self,
        step_definition: WorkflowStepDefinition,
        repo_dir: Path,
        run_dir: Path,
        log_file: Path,
        repo_url: str = "",
        branch: str | None = None,
        runtime_type: str = RUNTIME_TYPE,
    ) -> StepRunResult:
        uses_name = step_definition.uses

        # Project-lifecycle builtins (install/test/build/deploy) honor the
        # step's `cwd`, and auto-descend into a monorepo subdirectory when the
        # root has no project for this runtime. Security scans keep scanning
        # the whole repo, so they never trigger cwd resolution.
        project_dir = repo_dir
        if uses_name in {"install", "test", "build", "deploy"}:
            project_dir, cwd_error = self._resolve_project_dir(repo_dir, step_definition)
            if cwd_error is not None:
                return cwd_error

        if uses_name == "install":
            return run_install(repo_dir=project_dir, log_file=log_file, runtime_type=runtime_type)

        if uses_name == "lightweight_security_scan":
            if "CWE-798" not in normalize_selected_cwes(self._effective_selected_items):
                return StepRunResult(status="skipped", exit_code=0, summary_message="Secret 검사는 이번 실행의 선택 항목에 포함되지 않았습니다")
            report_name = _safe_report_file_name(step_definition.args.get("report_file"), "gitleaks_report.json")
            return run_lightweight_security_scan(
                repo_dir=repo_dir,
                log_file=log_file,
                report_file=run_dir / report_name,
            )

        if uses_name == "test":
            return run_test(repo_dir=project_dir, log_file=log_file, runtime_type=runtime_type)

        if uses_name == "deep_security_scan":
            report_name = _safe_report_file_name(step_definition.args.get("report_file"), "semgrep_report.json")
            ai_recommendation = bool(step_definition.args.get("ai_recommendation", False))
            return run_deep_security_scan(
                repo_dir=repo_dir,
                log_file=log_file,
                report_file=run_dir / report_name,
                ai_recommendation=ai_recommendation,
                selected_items=self._effective_selected_items,
            )

        if uses_name == "build":
            return run_build(
                repo_dir=project_dir,
                log_file=log_file,
                artifacts_dir=run_dir / "artifacts",
                runtime_type=runtime_type,
            )

        if uses_name == "deploy":
            if self._security_verdict is None or is_blocking(self._security_verdict):
                return StepRunResult(status="failed", exit_code=1,
                                     summary_message="Deployment requires a successful security gate")
            return run_deploy(
                repo_dir=project_dir,
                run_dir=run_dir,
                log_file=log_file,
                repo_url=repo_url,
                branch=branch,
                runtime_type=runtime_type,
            )

        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message=f"Unknown built-in step: {uses_name}",
        )

    def _execute_command_step(
        self,
        step_definition: WorkflowStepDefinition,
        repo_dir: Path,
        log_file: Path,
    ) -> StepRunResult:
        try:
            working_dir = (repo_dir / step_definition.cwd).resolve()
            repo_root = repo_dir.resolve()
            if not working_dir.is_relative_to(repo_root):
                return StepRunResult(
                    status="failed",
                    exit_code=1,
                    summary_message=(
                        f"Step '{step_definition.name}' cwd escapes repository root: {step_definition.cwd}"
                    ),
                )

            if not working_dir.exists() or not working_dir.is_dir():
                return StepRunResult(
                    status="failed",
                    exit_code=1,
                    summary_message=f"Step '{step_definition.name}' cwd not found: {step_definition.cwd}",
                )

            command_result = run_command(
                command=step_definition.command,
                cwd=working_dir,
                log_file=log_file,
                env=step_definition.env or None,
            )
        except Exception as exc:  # noqa: BLE001
            return StepRunResult(
                status="failed",
                exit_code=1,
                summary_message=f"Command step '{step_definition.name}' failed before execution: {exc}",
            )

        if command_result.exit_code == 0:
            return StepRunResult(
                status="success",
                exit_code=0,
                summary_message=f"Command step succeeded: {' '.join(step_definition.command)}",
            )

        return StepRunResult(
            status="failed",
            exit_code=command_result.exit_code,
            summary_message=f"Command step failed: {' '.join(step_definition.command)}",
        )

    def _run_security_gate(
        self,
        pipeline_run: PipelineRun,
        findings: list[SecurityFinding],
        logs_dir: Path,
        run_dir: Path,
        repo_url: str,
        branch: str | None,
    ) -> StepRunResult:
        gate_step = PipelineStep(step_name="security_gate")
        pipeline_run.steps.append(gate_step)
        gate_step.log_file = self._store_log_file(logs_dir / "security_gate.log")
        gate_step.started_at = now_iso()
        gate_step.status = "running"
        self._send_step_callback(pipeline_run, run_dir, gate_step, repo_url, branch)
        verdict = evaluate_security_policy(
            findings,
            selected_items=self._effective_selected_items,
            environment=self._environment,
            approved_cwes=self._approved_cwes,
            scanned_commit_sha=self._scanned_commit_sha,
        )
        self._security_verdict = verdict
        self._gate_findings = [{"severity": f.severity, "cwe": f.cwe, "scanner_name": f.scanner_name.lower(),
            "in_scope": f.in_scope} for f in findings]

        log_path = self._resolve_log_file(gate_step.log_file)
        append_log(log_path, f"$ security_gate (environment={verdict.environment})")
        if verdict.scanned_commit_sha:
            append_log(log_path, f"[commit] scanned {verdict.scanned_commit_sha}")
        if verdict.acknowledged_cwes:
            append_log(log_path, f"[acknowledged] {', '.join(verdict.acknowledged_cwes)}")
        append_log(log_path, f"[scope] {verdict.score_label}")
        append_log(log_path, f"[counts] {verdict.counts} out_of_scope={verdict.out_of_scope_count}")
        append_log(log_path, f"[score] {verdict.score} ({verdict.gauge_color})")
        append_log(log_path, f"[breakdown] {verdict.score_breakdown}")
        if verdict.requires_approval:
            append_log(log_path, "[approval] High/Medium 개수 기준 — 승인 예외 절차 필요")
        for reason in verdict.block_reasons:
            append_log(log_path, f"[BLOCK] {reason}")
        for reason in verdict.warn_reasons:
            append_log(log_path, f"[WARN] {reason}")
        append_log(log_path, f"[verdict] {verdict.verdict.upper()}")

        if is_blocking(verdict):
            result = StepRunResult(
                status="failed",
                exit_code=1,
                summary_message=format_summary(verdict),
            )
        else:
            result = StepRunResult(
                status="success",
                exit_code=0,
                summary_message=format_summary(verdict),
            )

        self._record_step_result(
            pipeline_run=pipeline_run,
            run_dir=run_dir,
            step=gate_step,
            result=result,
            repo_url=repo_url,
            branch=branch,
        )
        return result

    def _should_skip_step_for_source(self, step_definition: WorkflowStepDefinition) -> bool:
        # No source may bypass mandatory secret scanning.
        return False

    def _check_required_env(self, repo_dir: Path, logs_dir: Path) -> StepRunResult | None:
        missing, source_files = find_missing_env_keys(repo_dir)
        if not source_files:
            return None
        log_file = logs_dir / "env_check.log"
        rel_sources = [str(p.relative_to(repo_dir)) for p in source_files]
        append_log(log_file, f"$ env_check (sources: {', '.join(rel_sources)})")

        auto_provided = provide_public_env_defaults(missing)
        if auto_provided:
            append_log(
                log_file,
                (
                    "[env_check] auto-provided public frontend env defaults: "
                    f"{', '.join(auto_provided)}"
                ),
            )
            auto_provided_set = set(auto_provided)
            missing = [key for key in missing if key not in auto_provided_set]

        if not missing:
            append_log(log_file, "[env_check] all required env keys provided")
            append_log(log_file, "[exit_code] 0")
            detail = f"Required env keys satisfied (from {', '.join(rel_sources)})"
            if auto_provided:
                detail += f"; public defaults injected for {', '.join(auto_provided)}"
            return StepRunResult(
                status="success",
                exit_code=0,
                summary_message=detail,
            )
        append_log(log_file, f"[env_check] MISSING env keys: {', '.join(missing)}")
        append_log(log_file, "[env_check] Provide these via the backend env input prompt and re-run.")
        append_log(log_file, "[exit_code] 1")
        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message=(
                f"Missing required env keys: {', '.join(missing)} "
                f"(declared in {', '.join(rel_sources)})"
            ),
        )

    @staticmethod
    def _write_pipeline_result(run_dir: Path, pipeline_run: PipelineRun) -> None:
        save_json(run_dir / "pipeline_result.json", pipeline_run.to_dict())

    def _write_security_results(
        self,
        run_dir: Path,
        summaries: list[SecuritySummary],
        findings: list[SecurityFinding],
    ) -> None:
        save_json(run_dir / "security_summary.json", [item.to_dict() for item in summaries])
        save_json(run_dir / "security_findings.json", [item.to_dict() for item in findings])
        if self._security_verdict is not None:
            save_json(run_dir / "security_verdict.json", self._security_verdict.to_dict())


def _safe_report_file_name(raw_value: object, default_name: str) -> str:
    if raw_value is None:
        return default_name

    candidate_name = Path(str(raw_value)).name.strip()
    if not candidate_name:
        return default_name

    return candidate_name
