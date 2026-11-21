from __future__ import annotations

import shutil
from pathlib import Path

from app.models import StepRunResult
from app.utils.shell import run_command


def run_clone(
    repo_url: str,
    branch: str | None,
    repo_dir: Path,
    log_file: Path,
    commit_sha: str | None = None,
    repo_token: str | None = None,
) -> StepRunResult:
    if repo_dir.exists():
        shutil.rmtree(repo_dir)

    branch_candidates = _build_branch_candidates(branch)
    result = None
    used_branch = "default"

    for idx, candidate_branch in enumerate(branch_candidates):
        current_result = _run_clone_command(
            repo_url=repo_url,
            branch=candidate_branch,
            repo_dir=repo_dir,
            log_file=log_file,
            repo_token=repo_token,
        )
        result = current_result

        if current_result.exit_code == 0:
            used_branch = candidate_branch if candidate_branch else "default"
            break

        is_last_try = idx == len(branch_candidates) - 1
        if not _is_missing_branch_error(current_result.output) or is_last_try:
            break

    assert result is not None

    if result.exit_code != 0:
        return StepRunResult(
            status="failed",
            exit_code=result.exit_code,
            summary_message="git clone failed. Check clone.log for details",
        )

    if commit_sha and not _checkout_commit(commit_sha, repo_dir, log_file, repo_token):
        shutil.rmtree(repo_dir)
        return StepRunResult(status="failed", exit_code=1, summary_message="Requested commit unavailable; refusing branch HEAD fallback")
    sanitized = run_command(["git", "remote", "set-url", "origin", repo_url], repo_dir, log_file)
    if sanitized.exit_code:
        shutil.rmtree(repo_dir)
        return StepRunResult(status="failed", exit_code=1, summary_message="Cannot sanitize repository credentials")
    commit_note = f", commit {commit_sha[:12]} checked out" if commit_sha else ""

    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message=f"Repository cloned and branch {used_branch} checked out{commit_note}",
    )


def _checkout_commit(
    commit_sha: str, repo_dir: Path, log_file: Path, repo_token: str | None = None
) -> bool:
    """Fetch + checkout an exact commit on top of a shallow clone.

    Returns True if the commit was checked out, False if it could not be
    fetched (e.g. removed by force-push/rebase) — caller stays on branch HEAD.
    """
    fetch = run_command(
        command=["git", "fetch", "--depth", "1", "origin", commit_sha],
        cwd=repo_dir,
        log_file=log_file,
        env=_clone_env(repo_token),
    )
    if fetch.exit_code != 0:
        return False
    checkout = run_command(
        command=["git", "checkout", commit_sha],
        cwd=repo_dir,
        log_file=log_file,
    )
    return checkout.exit_code == 0


def _run_clone_command(
    repo_url: str,
    branch: str | None,
    repo_dir: Path,
    log_file: Path,
    repo_token: str | None = None,
):
    clone_url = _inject_token(repo_url, repo_token)
    cmd = ["git", "clone", "--depth", "1"]
    if branch:
        cmd.extend(["--branch", branch])
    cmd.extend([clone_url, str(repo_dir)])
    return run_command(
        command=cmd,
        cwd=repo_dir.parent,
        log_file=log_file,
        env=_clone_env(repo_token),
    )


def _clone_env(repo_token: str | None) -> dict[str, str]:
    # GIT_TERMINAL_PROMPT=0: fail fast instead of hanging on a credential prompt
    # when a repo is private/missing and no usable token was supplied.
    # GIT_TOKEN: not read by git, but its presence makes run_command treat the
    # value as sensitive and mask it (incl. the token embedded in the clone URL).
    env = {"GIT_TERMINAL_PROMPT": "0"}
    if repo_token:
        env["GIT_TOKEN"] = repo_token
    return env


def _inject_token(repo_url: str, repo_token: str | None) -> str:
    """Embed an OAuth/PAT token into an https git URL for private-repo access.

    Returns the URL unchanged for non-https URLs, when no token is given, or
    when credentials are already present in the authority component.
    """
    if not repo_token:
        return repo_url
    prefix = "https://"
    if not repo_url.startswith(prefix):
        return repo_url
    rest = repo_url[len(prefix):]
    authority = rest.split("/", 1)[0]
    if "@" in authority:
        return repo_url
    return f"{prefix}x-access-token:{repo_token}@{rest}"


def _is_missing_branch_error(output: str) -> bool:
    lowered = output.lower()
    return "could not find remote branch" in lowered or "remote branch" in lowered and "not found" in lowered


def _build_branch_candidates(branch: str | None) -> list[str | None]:
    if not branch:
        return [None]

    normalized = branch.strip()
    candidates: list[str | None] = [normalized]

    if normalized == "main":
        candidates.append("master")
    elif normalized == "master":
        candidates.append("main")

    candidates.append(None)
    return candidates
