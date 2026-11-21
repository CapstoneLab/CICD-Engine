from __future__ import annotations

import json
import os
import queue
import threading
import time
from uuid import uuid4
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from app.callback import post_callback_with_retry
from app.utils.logger import listen_to_logs


@dataclass(frozen=True)
class LogEvent:
    sequence: int
    timestamp: str
    run_id: str
    step_name: str
    stream: str
    message: str
    log_file: Path


class CallbackLogStreamer:
    """Batch local pipeline log lines into authenticated backend callbacks.

    The worker keeps network latency away from build commands. Failed batches
    are recorded next to the run artifacts; step/pipeline completion callbacks
    remain the authoritative reconciliation path.
    """

    _STOP = object()

    def __init__(
        self,
        *,
        callback_url: str,
        callback_token: str,
        job_id: str,
        repo_url: str,
        branch: str,
        batch_size: int = 50,
        flush_interval_sec: float = 0.25,
        timeout_sec: int = 5,
        heartbeat_interval_sec: float = 10,
    ) -> None:
        self.callback_url = callback_url.strip()
        self.callback_token = callback_token.strip()
        self.job_id = job_id.strip()
        self.repo_url = repo_url
        self.branch = branch
        self.batch_size = max(1, batch_size)
        self.flush_interval_sec = max(0.01, flush_interval_sec)
        self.timeout_sec = max(1, timeout_sec)
        self.heartbeat_interval_sec = max(0.05, heartbeat_interval_sec)
        self._queue: queue.Queue[LogEvent | object] = queue.Queue()
        self._sequence = 0
        self._sequence_lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._listener_context: Any = None
        self._delivery_disabled_until = 0.0

    def __enter__(self) -> CallbackLogStreamer:
        if not self.callback_url:
            return self
        self._thread = threading.Thread(
            target=self._run,
            name=f"log-stream-{self.job_id or 'local'}",
            daemon=True,
        )
        self._thread.start()
        self._listener_context = listen_to_logs(self.emit)
        self._listener_context.__enter__()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._listener_context is not None:
            self._listener_context.__exit__(exc_type, exc, traceback)
            self._listener_context = None
        if self._thread is not None:
            self._queue.put(self._STOP)
            self._thread.join()
            self._thread = None

    def emit(self, log_file: Path, line: str) -> None:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        self._queue.put(
            LogEvent(
                sequence=sequence,
                timestamp=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                run_id=_run_id_from_log_file(log_file),
                step_name=log_file.stem,
                stream="stdout",
                message=line,
                log_file=log_file,
            )
        )

    def _run(self) -> None:
        batch: list[LogEvent] = []
        stopping = False
        deadline: float | None = None
        heartbeat_due = time.monotonic() + self.heartbeat_interval_sec
        while not stopping:
            timeout = max(0.0, min(deadline or heartbeat_due, heartbeat_due) - time.monotonic())
            try:
                item = self._queue.get(timeout=timeout)
            except queue.Empty:
                item = None

            if item is self._STOP:
                stopping = True
            elif isinstance(item, LogEvent):
                batch.append(item)
                if deadline is None:
                    deadline = time.monotonic() + self.flush_interval_sec

            if batch and (
                stopping
                or item is None
                or len(batch) >= self.batch_size
            ):
                # Coalesce an existing backlog without waiting for new logs.
                # Normal idle flush stays 250ms; shutdown needs fewer round trips.
                while not stopping and len(batch) < max(self.batch_size, 500):
                    try:
                        queued = self._queue.get_nowait()
                    except queue.Empty:
                        break
                    if queued is self._STOP:
                        stopping = True
                    elif isinstance(queued, LogEvent):
                        batch.append(queued)
                self._deliver(batch)
                batch = []
                deadline = None
            if not stopping and time.monotonic() >= heartbeat_due:
                self._heartbeat()
                heartbeat_due = time.monotonic() + self.heartbeat_interval_sec

    def _heartbeat(self) -> None:
        if not self.job_id:
            return
        post_callback_with_retry(callback_url=self.callback_url, callback_token=self.callback_token,
            payload={"type": "heartbeat", "event_id": str(uuid4()), "job_id": self.job_id,
                "repo_url": self.repo_url, "branch": self.branch},
            retry_delays_sec=[], timeout_sec=self.timeout_sec)

    def _deliver(self, events: list[LogEvent]) -> None:
        payload = build_log_batch_payload(
            job_id=self.job_id or events[0].run_id,
            repo_url=self.repo_url,
            branch=self.branch,
            events=events,
        )
        if time.monotonic() < self._delivery_disabled_until:
            delivered = False
            detail = {"attempts": 0, "error": "delivery paused after previous failure", "http_status": None}
        else:
            delivered, detail = post_callback_with_retry(
                callback_url=self.callback_url,
                callback_token=self.callback_token,
                payload=payload,
                retry_delays_sec=[],
                timeout_sec=self.timeout_sec,
            )
        if not delivered:
            self._delivery_disabled_until = time.monotonic() + 5
            _record_failed_delivery(events[0].log_file, payload, detail)


def build_log_batch_payload(
    *,
    job_id: str,
    repo_url: str,
    branch: str,
    events: list[LogEvent],
) -> dict[str, Any]:
    if not events:
        raise ValueError("at least one log event is required")

    first = events[0]
    last = events[-1]
    event_key = f"{job_id}:{first.run_id}:{os.getenv('CICD_RESUME_ID','')}:{first.sequence}:{last.sequence}"
    event_id = sha256(event_key.encode("utf-8")).hexdigest()
    serialized_events = [
        {
            "sequence": event.sequence,
            "timestamp": event.timestamp,
            "step_name": event.step_name,
            "stream": event.stream,
            "message": event.message,
        }
        for event in events
    ]
    return {
        "schema_version": 1,
        "type": "log_batch",
        "event_id": event_id,
        "job_id": job_id,
        "run_id": first.run_id,
        "repo_url": repo_url,
        "branch": branch,
        "pipeline_status": "running",
        "sequence_start": first.sequence,
        "sequence_end": last.sequence,
        "events": serialized_events,
        # Compatibility field for backends that already aggregate plain logs.
        "logs": [f"[{event.step_name}.log] {event.message}" for event in events],
        "metadata": {
            "executor": "ubuntu-ci-engine",
            "run_id": first.run_id,
        },
    }


def _run_id_from_log_file(log_file: Path) -> str:
    if log_file.parent.name == "logs":
        return log_file.parent.parent.name
    return ""


def _record_failed_delivery(
    log_file: Path,
    payload: dict[str, Any],
    detail: dict[str, Any],
) -> None:
    run_dir = log_file.parent.parent if log_file.parent.name == "logs" else log_file.parent
    failure_file = run_dir / "log_stream_failures.jsonl"
    record = {
        "recorded_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "event_id": payload["event_id"],
        "sequence_start": payload["sequence_start"],
        "sequence_end": payload["sequence_end"],
        "delivery": detail,
    }
    try:
        with failure_file.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        pass
