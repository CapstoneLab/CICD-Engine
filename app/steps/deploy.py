from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path

from app.models import StepRunResult
from app.utils.java import is_java_project
from app.utils.logger import append_log
from app.utils.python import is_python_project


LOCAL_DOCKER_TARGETS = {"local", "docker", "local-docker", "ubuntu-docker"}


def run_deploy(
    repo_dir: Path,
    run_dir: Path,
    log_file: Path,
    repo_url: str,
    branch: str | None,
    runtime_type: str | None = None,
) -> StepRunResult:
    """Deploy artifacts to independent Docker services on this Ubuntu host."""

    target = os.environ.get("DEPLOY_TARGET", "local-docker").strip().lower()
    if target not in LOCAL_DOCKER_TARGETS:
        message = (
            f"Unsupported DEPLOY_TARGET: {target}. "
            "This engine is local-Docker-only; use DEPLOY_TARGET=local-docker."
        )
        append_log(log_file, message)
        return StepRunResult(status="failed", exit_code=2, summary_message=message)

    from app.steps.local_docker_deploy import run_local_docker_deploy

    return run_local_docker_deploy(
        repo_dir=repo_dir,
        run_dir=run_dir,
        log_file=log_file,
        repo_url=repo_url,
        branch=branch,
        runtime_type=runtime_type,
    )


def _load_python_entry_from_build_meta(artifacts_dir: Path) -> dict | None:
    """Read the ASGI entry point recorded by the build step."""

    meta_path = artifacts_dir / "build_meta.json"
    if not meta_path.exists():
        return None
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    entry = data.get("entry")
    if not isinstance(entry, dict):
        return None
    module = entry.get("module")
    attr = entry.get("attr")
    if not isinstance(module, str) or not module or not isinstance(attr, str) or not attr:
        return None
    return {
        "module": module,
        "attr": attr,
        "factory": bool(entry.get("factory")),
        "app_dir": str(entry.get("app_dir") or "."),
        "file_path": str(entry.get("file_path") or ""),
    }


def _parse_github_url(url: str) -> tuple[str, str]:
    """Extract an owner and repository name from an HTTPS or SSH GitHub URL."""

    patterns = (
        r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$",
        r"github\.com[:/]([^/]+)/([^/.]+?)/?$",
    )
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return "", ""


def _detect_runtime(repo_dir: Path) -> str:
    """Detect the runtime needed by the local Docker deployment builder."""

    package_json = repo_dir / "package.json"
    if package_json.exists():
        try:
            package = json.loads(package_json.read_text(encoding="utf-8"))
            dependencies = {
                **package.get("dependencies", {}),
                **package.get("devDependencies", {}),
            }
            scripts = package.get("scripts", {})

            if "next" in dependencies:
                return "nextjs"
            if "react-scripts" in dependencies or "react" in dependencies:
                for relative in ("server.js", "server.ts", "src/server.js", "src/server.ts"):
                    if (repo_dir / relative).exists():
                        return "node"
                return "react"
            if "@angular/core" in dependencies or "@angular/cli" in dependencies:
                return "angular"
            if "@vue/cli-service" in dependencies or "vue" in dependencies:
                return "vue"
            if "vite" in dependencies:
                return "react" if "react" in dependencies else "vue"
            for relative in ("server.js", "index.js", "app.js", "main.js", "src/server.js"):
                if (repo_dir / relative).exists():
                    return "node"
            if "start" in scripts:
                return "node"
        except (json.JSONDecodeError, KeyError, TypeError):
            return "node"
        return "node"

    if (repo_dir / "requirements.txt").exists() or (repo_dir / "pyproject.toml").exists():
        return "python"
    if (repo_dir / "pom.xml").exists() or (repo_dir / "build.gradle").exists():
        return "java"
    if is_python_project(repo_dir):
        return "python"
    if is_java_project(repo_dir):
        return "java"
    return "node"


def _compute_artifacts_hash(artifacts_dir: Path) -> str:
    """Compute a stable SHA-256 digest for every deployable artifact."""

    hasher = hashlib.sha256()
    for file_path in sorted(artifacts_dir.rglob("*")):
        if file_path.is_file():
            hasher.update(str(file_path.relative_to(artifacts_dir)).encode())
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()
