"""Repository commands run in disposable containers, never in the controller."""
from contextlib import contextmanager
from contextvars import ContextVar
import os
from pathlib import Path
import re
import stat
import uuid

_repository = ContextVar("sandbox_repository", default=None)


def validate_repository(root: Path):
    root = root.resolve()
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs + files:
            path = Path(directory) / name
            mode = path.lstat().st_mode
            if stat.S_ISLNK(mode):
                if not path.resolve().is_relative_to(root):
                    raise ValueError("Repository symlink escapes workspace: " + str(path.relative_to(root)))
            elif not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
                raise ValueError("Repository contains a special device or socket")
            elif stat.S_ISREG(mode) and path.stat().st_nlink > 1:
                raise ValueError("Repository hard links are not allowed")


@contextmanager
def sandbox_commands(root: Path):
    validate_repository(root)
    token = _repository.set(root.resolve())
    try:
        yield
    finally:
        _repository.reset(token)
        validate_repository(root)


def wrap_command(command, cwd, env):
    root = _repository.get()
    if root is None:
        return command, None
    image = os.environ.get("CICD_SANDBOX_IMAGE", "")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}|[^\s]+@sha256:[0-9a-f]{64}", image):
        raise ValueError("CICD_SANDBOX_IMAGE must be an administrator-pinned image digest")
    if not cwd.resolve().is_relative_to(root):
        raise ValueError("Sandbox cwd escapes repository")
    validate_repository(root)
    # No processes from earlier commands survive: each container is removed.
    for directory, dirs, files in os.walk(root, followlinks=False):
        os.chown(directory, 10001, 10001, follow_symlinks=False)
        for name in dirs + files:
            os.chown(Path(directory) / name, 10001, 10001, follow_symlinks=False)
    name = "cicd-sandbox-" + uuid.uuid4().hex
    args = ["docker", "run", "--rm", "--init", "--name", name,
            "--label", f"capstone.sandbox.owner={os.getenv('HOSTNAME', 'local')}:{os.getpid()}",
            "--user", "10001:10001", "--read-only", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges", "--pids-limit", "256",
            "--memory", "2g", "--cpus", "2", "--network", "bridge",
            "--tmpfs", "/tmp:rw,nosuid,nodev,size=512m,mode=1777",
            "--tmpfs", "/app:rw,nosuid,nodev,noexec,size=1m,mode=755",
            "--mount", f"type=bind,src={root},dst={root}",
            "--workdir", str(cwd), "--entrypoint", "/usr/bin/env"]
    # env -i discards even image defaults. No controller environment is inherited.
    safe = {"PATH":"/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/gradle/bin", "HOME":"/tmp", "CI":"true", "LANG":"C.UTF-8"}
    safe.update(env or {})
    return [*args, image, "-i", *(f"{k}={v}" for k,v in safe.items()), "/usr/bin/timeout", "--kill-after=5s", "1800", *command], name
