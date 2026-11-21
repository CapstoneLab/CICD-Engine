from __future__ import annotations

import os
import subprocess
import threading
from app.utils.sandbox import wrap_command, validate_repository, _repository
from dataclasses import dataclass
from pathlib import Path

from app.utils.logger import append_log
from app.utils.secrets import collect_sensitive_values, mask_line


@dataclass
class CommandResult:
    exit_code: int
    output: str


def _decode_chunk(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("cp949", errors="replace")


def run_command(
    command: list[str],
    cwd: Path,
    log_file: Path,
    env: dict[str, str] | None = None,
) -> CommandResult:
    process_env = os.environ.copy()
    if env:
        process_env.update(env)

    sensitive_values = collect_sensitive_values()
    if env:
        for key, value in env.items():
            if value and len(value) >= 4 and any(k in key.upper() for k in ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH")):
                sensitive_values.append(value)
        sensitive_values = sorted(set(sensitive_values), key=len, reverse=True)

    append_log(log_file, mask_line(f"$ {' '.join(command)}", sensitive_values))

    command, sandbox_name = wrap_command(command, cwd, env)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            shell=False,
            env=process_env,
        )
    except FileNotFoundError as exc:
        message = f"Command not found: {command[0]} ({exc})"
        append_log(log_file, mask_line(message, sensitive_values))
        append_log(log_file, "[exit_code] 127")
        return CommandResult(exit_code=127, output=mask_line(message, sensitive_values))

    timed_out = threading.Event()
    def stop_sandbox():
        timed_out.set()
        subprocess.run(["docker", "rm", "-f", sandbox_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=20)
        process.kill()
    timer = threading.Timer(1800, stop_sandbox) if sandbox_name else None
    if timer:
        timer.daemon = True
        timer.start()
    chunks: list[str] = []

    assert process.stdout is not None
    while True:
        raw = process.stdout.readline()
        if not raw and process.poll() is not None:
            break
        if not raw:
            continue

        decoded = _decode_chunk(raw).rstrip("\r\n")
        masked = mask_line(decoded, sensitive_values)
        chunks.append(masked)
        append_log(log_file, masked)

    exit_code = process.wait()
    if timer:
        timer.cancel()
    if timed_out.is_set():
        exit_code = 124
    if sandbox_name:
        validate_repository(_repository.get())
    append_log(log_file, f"[exit_code] {exit_code}")

    return CommandResult(exit_code=exit_code, output="\n".join(chunks))
