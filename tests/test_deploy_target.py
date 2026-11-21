from pathlib import Path

from app.steps.deploy import run_deploy


def test_aws_deploy_target_is_rejected(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DEPLOY_TARGET", "aws")

    result = run_deploy(
        repo_dir=tmp_path / "repo",
        run_dir=tmp_path / "run",
        log_file=tmp_path / "deploy.log",
        repo_url="https://github.com/example/repository",
        branch="main",
    )

    assert result.status == "failed"
    assert result.exit_code == 2
    assert "local-Docker-only" in result.summary_message
