from __future__ import annotations

from pathlib import Path
from typing import Any

from app.callback import build_step_callback_payload, collect_logs, post_step_callback
from app.constants import RUNTIME_TYPE
from app.models import PipelineRun, PipelineStep, SecurityFinding, SecuritySummary, StepRunResult, now_iso
from app.security_policy import SecurityVerdict, evaluate as evaluate_security_policy, format_summary
from app.utils.env_requirements import find_missing_env_keys
from app.steps.build import run_build
from app.steps.clone import run_clone
from app.steps.deep_security import run_deep_security_scan
from app.steps.deploy import run_deploy
from app.steps.install import run_install
from app.steps.lightweight_security import run_lightweight_security_scan
from app.steps.test import run_test
from app.utils.filesystem import make_run_id, prepare_run_paths, save_json
from app.utils.logger import append_log
from app.utils.shell import run_command
from app.workflow import WorkflowStepDefinition, resolve_workflow_definition


class LocalOrchestrator:
    def __init__(
        self,
        base_dir: Path,
        callback_url: str = "",
        callback_token: str = "",
        job_id: str = "",
        source: str = "capstone",
        environment: str = "development",
    ) -> None:
        self.base_dir = base_dir
        self._current_runtime_type: str = RUNTIME_TYPE
        self._callback_url = callback_url
        self._callback_token = callback_token
        self._job_id = job_id
        self._source = source
        self._environment = environment
        self._security_verdict: SecurityVerdict | None = None

    def run(self, repo_url: str, branch: str | None, workflow_path: str | None = None) -> tuple[PipelineRun, Path]:
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
            env_step.log_file = str((logs_dir / "env_check.log").relative_to(self.base_dir))
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
                if not step.continue_on_failure:
                    self._mark_remaining_steps_skipped(
                        pipeline_run=pipeline_run,
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
                    has_failure = True
                    self._mark_remaining_steps_skipped(
                        pipeline_run=pipeline_run,
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
        step.log_file = str((logs_dir / f"{step.step_name}.log").relative_to(self.base_dir))
        self._write_pipeline_result(run_dir, pipeline_run)

        try:
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
            step_log_path = self.base_dir / step.log_file
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
        if not self._callback_url or not self._callback_token:
            return

        step_log: list[str] = []
        if step.log_file:
            log_path = self.base_dir / step.log_file
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
        )

        ok, detail = post_step_callback(
            callback_url=self._callback_url,
            callback_token=self._callback_token,
            payload=payload,
        )
        if ok:
            print(f"  -> step callback sent: {step.step_name}")
        else:
            print(f"  -> step callback failed: {step.step_name} ({detail})")

    @staticmethod
    def _mark_remaining_steps_skipped(
        pipeline_run: PipelineRun,
        remaining_steps: list[PipelineStep],
        reason: str,
    ) -> None:
        for step in remaining_steps:
            if step.status != "pending":
                continue
            step.status = "skipped"
            step.started_at = step.started_at or now_iso()
            step.finished_at = now_iso()
            step.exit_code = 0
            step.summary_message = reason

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
            return run_clone(repo_url=repo_url, branch=branch, repo_dir=repo_dir, log_file=log_file)

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

        if uses_name == "install":
            return run_install(repo_dir=repo_dir, log_file=log_file, runtime_type=runtime_type)

        if uses_name == "lightweight_security_scan":
            report_name = _safe_report_file_name(step_definition.args.get("report_file"), "gitleaks_report.json")
            return run_lightweight_security_scan(
                repo_dir=repo_dir,
                log_file=log_file,
                report_file=run_dir / report_name,
            )

        if uses_name == "test":
            return run_test(repo_dir=repo_dir, log_file=log_file, runtime_type=runtime_type)

        if uses_name == "deep_security_scan":
            report_name = _safe_report_file_name(step_definition.args.get("report_file"), "semgrep_report.json")
            return run_deep_security_scan(
                repo_dir=repo_dir,
                log_file=log_file,
                report_file=run_dir / report_name,
                ai_recommendation=True,
            )

        if uses_name == "build":
            return run_build(
                repo_dir=repo_dir,
                log_file=log_file,
                artifacts_dir=run_dir / "artifacts",
                runtime_type=runtime_type,
            )

        if uses_name == "deploy":
            return run_deploy(
                repo_dir=repo_dir,
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
        verdict = evaluate_security_policy(findings, environment=self._environment)
        self._security_verdict = verdict

        gate_step = PipelineStep(step_name="security_gate")
        pipeline_run.steps.append(gate_step)
        gate_step.log_file = str((logs_dir / "security_gate.log").relative_to(self.base_dir))
        gate_step.started_at = now_iso()
        log_path = self.base_dir / gate_step.log_file
        append_log(log_path, f"$ security_gate (environment={verdict.environment})")
        append_log(log_path, f"[counts] {verdict.counts}")
        append_log(log_path, f"[score] {verdict.score}")
        append_log(log_path, f"[thresholds] {verdict.thresholds}")
        for reason in verdict.block_reasons:
            append_log(log_path, f"[BLOCK] {reason}")
        for reason in verdict.warn_reasons:
            append_log(log_path, f"[WARN] {reason}")
        append_log(log_path, f"[verdict] {verdict.verdict.upper()}")

        if verdict.verdict == "block":
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
        if self._source != "mirae":
            return False
        if step_definition.kind != "builtin":
            return False
        return step_definition.uses == "lightweight_security_scan"

    def _check_required_env(self, repo_dir: Path, logs_dir: Path) -> StepRunResult | None:
        missing, source_files = find_missing_env_keys(repo_dir)
        if not source_files:
            return None
        log_file = logs_dir / "env_check.log"
        rel_sources = [str(p.relative_to(repo_dir)) for p in source_files]
        append_log(log_file, f"$ env_check (sources: {', '.join(rel_sources)})")
        if not missing:
            append_log(log_file, "[env_check] all required env keys provided")
            append_log(log_file, "[exit_code] 0")
            return StepRunResult(
                status="success",
                exit_code=0,
                summary_message=f"Required env keys satisfied (from {', '.join(rel_sources)})",
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
