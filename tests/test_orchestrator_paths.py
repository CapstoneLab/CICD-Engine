from pathlib import Path

from app.models import PipelineRun, PipelineStep, StepRunResult
from app.orchestrator import LocalOrchestrator
from app.utils.filesystem import prepare_run_paths


def test_step_logs_use_configured_data_root(monkeypatch, tmp_path: Path) -> None:
    engine_dir = tmp_path / "engine"
    mounted_root = tmp_path / "mounted-data"
    engine_dir.mkdir()
    monkeypatch.setenv("CICD_ENGINE_DATA_DIR", str(mounted_root))

    run_id = "run-20260809-001"
    paths = prepare_run_paths(engine_dir, run_id)
    step = PipelineStep(step_name="clone")
    pipeline_run = PipelineRun(
        run_id=run_id,
        repo_url="https://github.com/example/repo.git",
        branch="main",
        steps=[step],
    )
    orchestrator = LocalOrchestrator(base_dir=engine_dir)
    monkeypatch.setattr(
        orchestrator,
        "_execute_step",
        lambda **_kwargs: StepRunResult(
            status="success",
            exit_code=0,
            summary_message="clone complete",
        ),
    )

    result = orchestrator._run_and_record_step(
        pipeline_run=pipeline_run,
        step=step,
        repo_url=pipeline_run.repo_url,
        branch=pipeline_run.branch,
        repo_dir=paths["repo_dir"],
        run_dir=paths["run_dir"],
        logs_dir=paths["logs_dir"],
        step_definition=None,
    )

    assert result.status == "success"
    assert step.log_file == f"runs/{run_id}/logs/clone.log"

    log_file = mounted_root / step.log_file
    assert log_file.is_file()
    log_text = log_file.read_text(encoding="utf-8")
    assert "[step_status] success" in log_text
    assert "[step_summary] clone complete" in log_text


def test_start_is_reported_before_execution_and_finish_after(monkeypatch, tmp_path):
    orchestrator = LocalOrchestrator(base_dir=tmp_path)
    paths = prepare_run_paths(tmp_path, "run-order")
    step = PipelineStep(step_name="test")
    pipeline = PipelineRun(run_id="run-order", repo_url="https://example.com/repo.git", branch="main", steps=[step])
    order = []
    def callback(run, run_dir, value, *args):
        order.append(value.status)
        assert value.started_at
    def execute(**kwargs):
        order.append("execute")
        return StepRunResult(status="success", exit_code=0, summary_message="ok")
    monkeypatch.setattr(orchestrator, "_send_step_callback", callback)
    monkeypatch.setattr(orchestrator, "_execute_step", execute)
    orchestrator._run_and_record_step(pipeline, step, pipeline.repo_url, "main", paths["repo_dir"], paths["run_dir"], paths["logs_dir"], None)
    assert order == ["running", "execute", "success"]


def test_skipped_steps_are_reported_without_fake_start(monkeypatch, tmp_path):
    orchestrator = LocalOrchestrator(base_dir=tmp_path)
    step = PipelineStep(step_name="deploy")
    pipeline = PipelineRun(run_id="run-skip", repo_url="https://example.com/repo.git", branch="main", steps=[step])
    callbacks = []
    monkeypatch.setattr(orchestrator, "_send_step_callback", lambda *args: callbacks.append(args[2].status))
    orchestrator._mark_remaining_steps_skipped(pipeline, [step], "previous failure", tmp_path, pipeline.repo_url, "main")
    assert step.started_at is None
    assert step.finished_at is not None
    assert callbacks == ["skipped"]
