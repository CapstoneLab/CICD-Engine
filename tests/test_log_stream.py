from __future__ import annotations

from pathlib import Path

from app import log_stream
from app.log_stream import CallbackLogStreamer, LogEvent, build_log_batch_payload
from app.utils.logger import append_log


def _event(sequence: int, message: str = "line") -> LogEvent:
    return LogEvent(
        sequence=sequence,
        timestamp="2026-09-05T00:00:00+00:00",
        run_id="run-001",
        step_name="build",
        stream="stdout",
        message=message,
        log_file=Path("/tmp/run-001/logs/build.log"),
    )


def test_log_batch_contract_has_ordering_and_compatibility_lines() -> None:
    payload = build_log_batch_payload(
        job_id="job-001",
        repo_url="https://github.com/example/repo.git",
        branch="main",
        events=[_event(4, "first"), _event(5, "second")],
    )

    assert payload["type"] == "log_batch"
    assert payload["schema_version"] == 1
    assert payload["sequence_start"] == 4
    assert payload["sequence_end"] == 5
    assert payload["events"][0]["step_name"] == "build"
    assert payload["logs"] == [
        "[build.log] first",
        "[build.log] second",
    ]
    assert len(payload["event_id"]) == 64


def test_streamer_observes_append_log_and_flushes_on_close(monkeypatch, tmp_path: Path) -> None:
    delivered: list[dict] = []

    def fake_post(**kwargs):
        delivered.append(kwargs["payload"])
        return True, {"attempts": 1, "error": None, "http_status": "200"}

    monkeypatch.setattr(log_stream, "post_callback_with_retry", fake_post)
    log_file = tmp_path / "run-001" / "logs" / "test.log"

    with CallbackLogStreamer(
        callback_url="http://backend/get-results",
        callback_token="secret",
        job_id="job-001",
        repo_url="https://github.com/example/repo.git",
        branch="main",
        flush_interval_sec=60,
    ):
        append_log(log_file, "hello", echo=False)
        append_log(log_file, "world", echo=False)

    assert len(delivered) == 1
    assert delivered[0]["run_id"] == "run-001"
    assert [event["message"].split("] ", 1)[-1] for event in delivered[0]["events"]] == [
        "hello",
        "world",
    ]


def test_quiet_running_worker_sends_heartbeat_without_fabricated_logs(monkeypatch):
    import threading
    received = threading.Event()
    payloads = []
    def fake_post(**kwargs):
        payloads.append(kwargs['payload'])
        received.set()
        return True, {'http_status': '200'}
    monkeypatch.setattr(log_stream, 'post_callback_with_retry', fake_post)
    with CallbackLogStreamer(callback_url='http://backend/get-results', callback_token='test',
            job_id='job-quiet', repo_url='https://github.com/owner/repo', branch='main', heartbeat_interval_sec=0.05):
        assert received.wait(1)
    assert payloads[0]['type'] == 'heartbeat'
    assert payloads[0]['job_id'] == 'job-quiet'
    assert 'events' not in payloads[0]


def test_existing_backlog_is_coalesced_in_order_without_losing_shutdown_tail(monkeypatch):
    batches = []
    streamer = CallbackLogStreamer(callback_url='http://backend/get-results', callback_token='test',
        job_id='job', repo_url='https://github.com/a/b', branch='main')
    monkeypatch.setattr(streamer, '_deliver', lambda events: batches.append([e.sequence for e in events]))
    for i in range(1200):
        streamer._queue.put(_event(i+1))
    streamer._queue.put(streamer._STOP)
    streamer._run()
    assert [seq for batch in batches for seq in batch] == list(range(1,1201))
    assert [len(batch) for batch in batches] == [500,500,200]
