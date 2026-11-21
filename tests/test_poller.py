from pathlib import Path
from unittest.mock import Mock

from app import poller


def test_docker_only_mode_skips_host_poller(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ENGINE_DOCKER_ONLY", "true")
    monkeypatch.setattr(poller, "CONTAINER_MARKER", tmp_path / "missing-dockerenv")

    assert poller.main() == 0


def test_report_failure_posts_engine_failure_payload(monkeypatch) -> None:
    calls = []

    def fake_http_json(method, url, *, token, engine_id, payload=None, timeout_sec=10):
        calls.append((method, url, token, engine_id, payload, timeout_sec))
        return 200, {"status": "failed"}, ""

    monkeypatch.setattr(poller, "_http_json", fake_http_json)

    poller._report_failure(
        "http://backend:8000",
        "job-1",
        "shared",
        "engine-1",
        reason="engine_start_failed",
        detail="spawn failed",
    )

    assert calls == [
        (
            "POST",
            "http://backend:8000/api/jobs/job-1/fail",
            "shared",
            "engine-1",
            {"reason": "engine_start_failed", "detail": "spawn failed"},
            10,
        )
    ]


def test_normalize_selected_items_accepts_backend_payload_shapes() -> None:
    assert poller._normalize_selected_items("CWE-89, sql-injection") == [
        "CWE-89",
        "sql-injection",
    ]
    assert poller._normalize_selected_items(
        [{"cwe": "CWE-79"}, {"key": "broken-access-control"}, "CWE-89"]
    ) == ["CWE-79", "broken-access-control", "CWE-89"]


def test_spawn_pipeline_forwards_job_contract_without_logging_token(
    monkeypatch, tmp_path: Path
) -> None:
    engine_dir = tmp_path / "engine"
    data_dir = tmp_path / "data"
    engine_dir.mkdir()
    (engine_dir / "main.py").touch()
    monkeypatch.setattr(poller, "BASE_DIR", engine_dir)
    monkeypatch.setenv("CICD_ENGINE_DATA_DIR", str(data_dir))

    process = Mock(pid=1234)
    popen = Mock(return_value=process)
    monkeypatch.setattr(poller.subprocess, "Popen", popen)

    token = "github-secret-token"
    result = poller._spawn_pipeline(
        {
            "job_id": "job-1",
            "repo_url": "https://github.com/example/private.git",
            "branch": "main",
            "repo_token": token,
            "selected_items": ["CWE-89"],
            "approved_cwes": ["CWE-79"],
            "commit_sha": "abc123",
        },
        "http://backend:8000/get-results",
        "engine-shared-secret",
    )

    assert result is process
    command = popen.call_args.args[0]
    assert command[command.index("--repo-token") + 1] == token
    assert command[command.index("--callback-url") + 1] == "http://backend:8000/get-results"
    assert command[command.index("--callback-token") + 1] == "engine-shared-secret"
    assert command[command.index("--selected-items") + 1] == "CWE-89"
    assert command[command.index("--approved-cwes") + 1] == "CWE-79"
    assert command[command.index("--commit") + 1] == "abc123"

    spawn_log = data_dir / "runs" / "job-job-1.log"
    assert token not in spawn_log.read_text(encoding="utf-8")
    assert "engine-shared-secret" not in spawn_log.read_text(encoding="utf-8")
    assert "****" in spawn_log.read_text(encoding="utf-8")


def test_termination_stops_runner_and_child_processes(tmp_path):
    import subprocess
    import sys
    import time
    marker = tmp_path / "ready"
    script = "import subprocess,time,pathlib; subprocess.Popen(['sleep','60']); pathlib.Path(%r).touch(); time.sleep(60)" % str(marker)
    proc = subprocess.Popen([sys.executable, "-c", script], start_new_session=True)
    try:
        deadline = time.monotonic() + 3
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists()
        assert poller._group_alive(proc.pid)
        assert poller._terminate_pipeline(proc)
        assert proc.poll() is not None
        assert not poller._group_alive(proc.pid)
    finally:
        poller._terminate_pipeline(proc)
        proc.wait()


def test_cancel_does_not_ack_unverified_process(monkeypatch):
    calls = []
    def http(method, url, **kwargs):
        calls.append(method)
        return 200, {"job_ids": ["job-1"]}, ""
    monkeypatch.setattr(poller, "_http_json", http)
    monkeypatch.setattr(poller, "_terminate_pipeline", lambda proc: False)
    running = {"job-1": Mock()}
    assert poller._process_cancellations(running, "http://backend", "token", "worker") == {"job-1"}
    assert calls == ["GET"]
    assert "job-1" in running


def test_cancel_racing_verified_process_exit_is_acknowledged(monkeypatch):
    process = Mock()
    process.termination_verified = True
    monkeypatch.setattr(poller, "_finished_processes", {"job-done": process})
    calls = []
    def http(method, url, **kwargs):
        calls.append(method)
        return 200, {"job_ids": ["job-done"]}, ""
    monkeypatch.setattr(poller, "_http_json", http)
    monkeypatch.setattr(poller, "_terminate_pipeline", lambda proc: (_ for _ in ()).throw(AssertionError("must not signal a reaped PID")))
    poller._process_cancellations({}, "http://backend", "token", "worker")
    assert calls == ["GET", "POST"]
    assert not poller._finished_processes


def test_claim_next_uses_atomic_endpoint_with_batch_timeout(monkeypatch):
    calls=[]
    def http(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return 200, {"jobs":[{"job_id":"fresh","approved_cwes":[]}]}, ""
    monkeypatch.setattr(poller,"_http_json",http)
    assert poller._claim_next("http://backend","token","engine",5)==[{"job_id":"fresh","approved_cwes":[]}]
    assert calls[0][0:2]==("POST","http://backend/api/jobs/claim-next?limit=5")
    assert calls[0][2]["timeout_sec"]==60
