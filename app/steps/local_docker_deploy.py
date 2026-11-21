from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import shutil
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from http.client import HTTPConnection, HTTPException
from pathlib import Path
from typing import Iterator
from urllib.parse import urlsplit, urljoin
from urllib.request import urlopen
from urllib.error import URLError

import yaml

from app.models import StepRunResult
from app.utils.java import is_java_project
from app.utils.logger import append_log
from app.utils.python import is_python_project
from app.utils.shell import CommandResult, run_command


MANAGED_LABEL = "com.capstonelab.cicd.managed"
SERVICE_LABEL = "com.capstonelab.cicd.service-key"
PORT_LABEL = "com.capstonelab.cicd.host-port"
# Server runtimes whose "/" may legitimately have no handler. Python gets a
# /docs redirect instead and static frontends always serve index.html.
ROOT_FALLBACK_RUNTIMES = frozenset({"java", "node", "nextjs"})


@dataclass(frozen=True)
class RuntimeSpec:
    runtime: str
    container_port: int
    context_dir: Path


def run_local_docker_deploy(
    repo_dir: Path,
    run_dir: Path,
    log_file: Path,
    repo_url: str,
    branch: str | None,
    runtime_type: str | None = None,
) -> StepRunResult:
    from app.steps.deploy import (
        _compute_artifacts_hash,
        _detect_runtime,
        _load_python_entry_from_build_meta,
        _parse_github_url,
    )

    owner, repo_name = _parse_github_url(repo_url)
    if not owner or not repo_name:
        message = f"Cannot parse owner/repo from URL: {repo_url}"
        append_log(log_file, message)
        return _failed(message)

    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.exists() or not any(artifacts_dir.iterdir()):
        message = "No build artifacts found. Build step must run before deploy."
        append_log(log_file, message)
        return _failed(message)

    runtime = _resolve_runtime(repo_dir, runtime_type, _detect_runtime)
    service_key = f"{owner}/{repo_name}".lower()
    artifact_hash = _compute_artifacts_hash(artifacts_dir)
    image_name = _image_name(owner, repo_name, artifact_hash)
    container_name = _container_name(owner, repo_name, service_key)
    public_host = os.environ.get("DEPLOY_PUBLIC_HOST", "127.0.0.1").strip()
    bind_address = os.environ.get("DEPLOY_BIND_ADDRESS", "127.0.0.1").strip() or "127.0.0.1"
    network = os.environ.get("DEPLOY_DOCKER_NETWORK", "capstone-internal").strip()
    public_base_url = os.environ.get("DEPLOY_PUBLIC_BASE_URL", "").strip().rstrip("/")
    public_path = _service_public_path(public_base_url, owner, repo_name)

    append_log(log_file, f"Deploy target: local Docker on {public_host}")
    append_log(log_file, f"Service key: {service_key}")
    append_log(log_file, f"Detected runtime: {runtime}")
    append_log(log_file, f"Artifact hash: {artifact_hash}")

    try:
        spec = _prepare_runtime_context(
            repo_dir=repo_dir,
            artifacts_dir=artifacts_dir,
            context_dir=run_dir / "local-docker-context",
            runtime=runtime,
            python_entry=_load_python_entry_from_build_meta(artifacts_dir),
            public_path=public_path,
        )
    except (OSError, ValueError) as exc:
        message = f"Cannot prepare local Docker image: {exc}"
        append_log(log_file, message)
        return _failed(message)

    build = _docker(
        ["build", "-t", image_name, str(spec.context_dir)],
        cwd=run_dir,
        log_file=log_file,
    )
    if build.exit_code != 0:
        return _failed("Local Docker image build failed", build.exit_code)

    try:
        port_start, port_end = _port_range_from_env()
        with _deployment_lock(run_dir):
            current_container = _find_service_container(service_key, run_dir, log_file)
            used_ports = _docker_used_ports(run_dir, log_file)
            host_port = _reserve_service_port(
                run_dir=run_dir,
                service_key=service_key,
                port_start=port_start,
                port_end=port_end,
                used_ports=used_ports,
                current_container=current_container,
                log_file=log_file,
            )
            deployed = _compose_replace_service(
                current_container=current_container,
                container_name=container_name,
                image_name=image_name,
                service_key=service_key,
                owner=owner,
                repo_name=repo_name,
                runtime=runtime,
                artifact_hash=artifact_hash,
                bind_address=bind_address,
                host_port=host_port,
                container_port=spec.container_port,
                network=network,
                public_path=public_path,
                cwd=run_dir,
                log_file=log_file,
            )
    except (OSError, ValueError) as exc:
        message = f"Local Docker deployment failed: {exc}"
        append_log(log_file, message)
        return _failed(message)

    if not deployed:
        return _failed(f"Container failed to start on port {host_port}")

    scheme = os.environ.get("DEPLOY_SCHEME", "http").strip() or "http"
    direct_host = public_host if bind_address in {"0.0.0.0", "::"} else bind_address
    direct_service_url = f"{scheme}://{direct_host}:{host_port}"
    service_url = f"{public_base_url}/{owner}/{repo_name}" if public_base_url else direct_service_url
    root_status = _probe_root_status(
        *_compose_probe_address(container_name, spec.container_port, host_port), log_file
    )
    root_fallback = runtime in ROOT_FALLBACK_RUNTIMES and root_status == 404
    if root_fallback:
        append_log(
            log_file,
            "The app serves nothing at its root path; the deployment URL shows "
            "a landing page there. API paths are unaffected.",
        )
    endpoint = {
        "schema_version": 1,
        "status": "success",
        "url": service_url,
        "public_url": service_url,
        "direct_url": direct_service_url,
        "urls": list(dict.fromkeys([service_url, direct_service_url])),
        "domain": urlsplit(service_url).hostname,
        "target": "local-docker",
        "owner": owner,
        "repo": repo_name,
        "branch": branch or "main",
        "runtime": runtime,
        "artifact_hash": artifact_hash,
        "host": public_host,
        "bind_address": bind_address,
        "port": host_port,
        "container_port": spec.container_port,
        "container_name": container_name,
        "image": image_name,
        "compose_project": "capstone-deployments",
        "public_path": public_path,
        # Status of the app's own "/"; root_fallback means the router answers
        # browsers there with the landing page because the app returned 404.
        "root_status": root_status,
        "root_fallback": root_fallback,
        "direct_service_url": direct_service_url,
        "service_url": service_url,
        "service_urls": list(dict.fromkeys([service_url, direct_service_url])),
        "deployed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    }
    (run_dir / "deploy_endpoint.json").write_text(
        json.dumps(endpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "deploy_manifest.json").write_text(
        json.dumps(endpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "deployment_result.json").write_text(
        json.dumps(endpoint, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    message = (
        f"Deployed {owner}/{repo_name} ({runtime}) to local Docker "
        f"| port={host_port} | hash={artifact_hash[:12]} | url={service_url}"
    )
    append_log(log_file, message)
    return StepRunResult(status="success", exit_code=0, summary_message=message)


def _failed(message: str, exit_code: int = 1) -> StepRunResult:
    return StepRunResult(status="failed", exit_code=exit_code, summary_message=message)


def _resolve_runtime(repo_dir: Path, runtime_type: str | None, detect_runtime) -> str:
    if runtime_type == "python" or (runtime_type is None and is_python_project(repo_dir)):
        return "python"
    if runtime_type == "java" or (runtime_type is None and is_java_project(repo_dir)):
        return "java"
    if runtime_type and runtime_type != "node":
        return runtime_type
    return detect_runtime(repo_dir)


def _slug(value: str, fallback: str) -> str:
    result = re.sub(r"[^a-z0-9_.-]+", "-", value.lower()).strip("-._")
    return result or fallback


def _container_name(owner: str, repo_name: str, service_key: str) -> str:
    digest = hashlib.sha256(service_key.encode()).hexdigest()[:8]
    base = f"cicd-app-{_slug(owner, 'owner')}-{_slug(repo_name, 'service')}"
    return f"{base[:52].rstrip('-')}-{digest}"


def _image_name(owner: str, repo_name: str, artifact_hash: str) -> str:
    return f"cicd-managed/{_slug(owner, 'owner')}-{_slug(repo_name, 'service')}:{artifact_hash[:12]}"


def _prepare_runtime_context(
    *,
    repo_dir: Path,
    artifacts_dir: Path,
    context_dir: Path,
    runtime: str,
    python_entry: dict | None,
    public_path: str,
) -> RuntimeSpec:
    if context_dir.exists():
        shutil.rmtree(context_dir)
    app_dir = context_dir / "app"
    app_dir.mkdir(parents=True)
    (context_dir / ".dockerignore").write_text(
        ".git\nnode_modules\n**/.env\n**/.env.*\n**/__pycache__\n", encoding="utf-8"
    )

    if runtime in {"react", "vue", "angular"}:
        static_root = _find_static_root(artifacts_dir)
        if static_root is None:
            raise ValueError("frontend build artifacts do not contain index.html")
        _copy_tree(static_root, app_dir)
        _rewrite_static_paths(app_dir, public_path)
        escaped_path = re.escape(public_path)
        (context_dir / "default.conf").write_text(
            "server {\n"
            "  listen 80;\n"
            "  server_name _;\n"
            "  root /usr/share/nginx/html;\n"
            "  index index.html;\n"
            f"  location ~ ^{escaped_path}/(.*)$ {{ try_files /$1 /index.html =404; }}\n"
            "  location / { try_files $uri /index.html; }\n"
            "}\n",
            encoding="utf-8",
        )
        dockerfile = (
            "FROM nginx:1.27-alpine\n"
            "COPY app/ /usr/share/nginx/html/\n"
            "COPY default.conf /etc/nginx/conf.d/default.conf\n"
            "EXPOSE 80\n"
        )
        port = 80
    elif runtime == "python":
        source = _artifact_fallback_dir(artifacts_dir, "dist-python")
        _copy_tree(source, app_dir)
        entry = python_entry or _guess_python_entry(app_dir)
        if not entry:
            raise ValueError("Python ASGI entry point was not found")
        app_path = f"{entry['module']}:{entry['attr']}"
        entry_app_dir = _safe_relative(str(entry.get("app_dir") or "."))
        command = ["uvicorn", app_path, "--host", "0.0.0.0", "--port", "8000"]
        if entry.get("factory"):
            command.append("--factory")
        if entry_app_dir != ".":
            command.extend(["--app-dir", entry_app_dir])
        dockerfile = (
            "FROM python:3.11-slim-bookworm\n"
            "ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1\n"
            "WORKDIR /app\n"
            "COPY app/ /app/\n"
            "RUN python -m pip install --no-cache-dir uvicorn "
            "&& if [ -f requirements.txt ]; then python -m pip install --no-cache-dir -r requirements.txt; "
            "elif [ -f pyproject.toml ]; then python -m pip install --no-cache-dir .; fi\n"
            f"CMD {json.dumps(command)}\n"
            "EXPOSE 8000\n"
        )
        port = 8000
    elif runtime == "java":
        artifact = _find_java_artifact(artifacts_dir)
        shutil.copy2(artifact, app_dir / "app.jar")
        dockerfile = (
            "FROM eclipse-temurin:17-jre-jammy\n"
            "WORKDIR /app\n"
            "COPY app/app.jar /app/app.jar\n"
            'ENTRYPOINT ["java", "-Dserver.address=0.0.0.0", "-Dserver.port=8080", "-jar", "/app/app.jar"]\n'
            "EXPOSE 8080\n"
        )
        port = 8080
    else:
        fallback = artifacts_dir / "dist-server"
        if fallback.is_dir():
            _copy_tree(fallback, app_dir)
        else:
            _copy_tree(repo_dir, app_dir)
            _overlay_node_artifacts(artifacts_dir, app_dir)
        if not (app_dir / "package.json").is_file():
            raise ValueError("Node deployment requires package.json")
        start_command = ["npm", "start"]
        if runtime == "nextjs":
            start_command.extend(["--", "--hostname", "0.0.0.0", "--port", "3000"])
        dockerfile = (
            "FROM node:20-bookworm-slim\n"
            "ENV NODE_ENV=production PORT=3000 HOST=0.0.0.0 HOSTNAME=0.0.0.0\n"
            "WORKDIR /app\n"
            "COPY app/ /app/\n"
            "RUN if [ -f package-lock.json ]; then npm ci --omit=dev; "
            "elif [ -f pnpm-lock.yaml ]; then corepack enable && pnpm install --prod --frozen-lockfile; "
            "elif [ -f yarn.lock ]; then corepack enable && yarn install --production --frozen-lockfile; "
            "else npm install --omit=dev; fi\n"
            f"CMD {json.dumps(start_command)}\n"
            "EXPOSE 3000\n"
        )
        port = 3000

    (context_dir / "Dockerfile").write_text(dockerfile, encoding="utf-8")
    return RuntimeSpec(runtime=runtime, container_port=port, context_dir=context_dir)


def _service_public_path(public_base_url: str, owner: str, repo_name: str) -> str:
    base_path = urlsplit(public_base_url).path.rstrip("/") if public_base_url else "/services"
    if not base_path.startswith("/"):
        base_path = f"/{base_path}"
    return f"{base_path}/{owner}/{repo_name}"


def _rewrite_static_paths(app_dir: Path, public_path: str) -> None:
    # Rewrite only references to actual build files, including custom public
    # directories and backtick strings. Do not rewrite client router patterns.
    files = {"/" + file.relative_to(app_dir).as_posix() for file in app_dir.rglob("*") if file.is_file()}
    pattern = re.compile(r"(?P<quote>[\"'`])(?P<url>/[^/\"'`][^\"'`]*)(?P=quote)")
    def replace(match):
        value = match.group("url")
        if urlsplit(value).path not in files:
            return match.group(0)
        quote = match.group("quote")
        return quote + public_path + value + quote
    for file in app_dir.rglob("*"):
        if file.suffix not in {".html", ".js", ".css"}:
            continue
        content = file.read_text(encoding="utf-8", errors="replace")
        rewritten = pattern.sub(replace, content)
        # CSS permits unquoted url(/images/...).
        if file.suffix == ".css":
            rewritten = re.sub(r"url\((/[^)\s]+)\)",
                lambda m: "url(" + public_path + m[1] + ")" if urlsplit(m[1]).path in files else m[0], rewritten)
        if rewritten != content:
            file.write_text(rewritten, encoding="utf-8")


def _wait_for_static_http(url: str, log_file: Path, timeout: int) -> bool:
    """Verify routed HTML and its JS/CSS, not only an open TCP socket."""
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=3) as response:
                if response.status != 200 or "text/html" not in response.headers.get("Content-Type", ""):
                    raise ValueError("entry page did not return HTML 200")
                html = response.read(2_000_000).decode("utf-8", errors="replace")
            resources = re.findall(r'<(?:script|link)\b[^>]*?(?:src|href)=[\"\']([^\"\']+)', html, re.I)
            for resource in resources:
                target = urljoin(url, resource)
                suffix = urlsplit(target).path.lower()
                if not suffix.endswith((".js", ".css")) or urlsplit(target).netloc != urlsplit(url).netloc:
                    continue
                with urlopen(target, timeout=3) as response:
                    content_type = response.headers.get("Content-Type", "").lower()
                    expected = "css" if suffix.endswith(".css") else "javascript"
                    if response.status != 200 or expected not in content_type:
                        raise ValueError(f"asset {resource} did not return {expected}")
            append_log(log_file, "Routed HTTP readiness passed: HTML and JS/CSS")
            return True
        except (OSError, URLError, ValueError) as exc:
            last_error = str(exc)
            time.sleep(0.5)
    append_log(log_file, f"Routed HTTP readiness failed: {last_error}")
    return False


def _copy_tree(source: Path, destination: Path) -> None:
    if not source.is_dir():
        raise ValueError(f"artifact directory not found: {source}")
    excluded_dirs = {".git", "node_modules", ".venv", "venv", "__pycache__"}
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        if path.is_symlink() or any(part in excluded_dirs for part in relative.parts):
            continue
        if path.name == ".env" or path.name.startswith(".env."):
            continue
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def _artifact_fallback_dir(artifacts_dir: Path, default: str) -> Path:
    meta_path = artifacts_dir / "build_meta.json"
    if meta_path.is_file():
        try:
            value = json.loads(meta_path.read_text(encoding="utf-8")).get("fallback_directory")
            if isinstance(value, str):
                candidate = artifacts_dir / _safe_relative(value)
                if candidate.is_dir():
                    return candidate
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    candidate = artifacts_dir / default
    if candidate.is_dir():
        return candidate
    raise ValueError(f"deployable source artifact not found: {default}")


def _safe_relative(value: str) -> str:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError(f"unsafe relative path in build metadata: {value}")
    return path.as_posix() or "."


def _find_static_root(artifacts_dir: Path) -> Path | None:
    for relative in ("dist", "build", "out", "public/build"):
        candidate = artifacts_dir / relative
        if (candidate / "index.html").is_file():
            return candidate
    index_files = sorted(artifacts_dir.rglob("index.html"))
    return index_files[0].parent if index_files else None


def _overlay_node_artifacts(artifacts_dir: Path, app_dir: Path) -> None:
    for child in artifacts_dir.iterdir():
        if child.name in {"build_meta.json", "dist-server"}:
            continue
        destination = app_dir / child.name
        if destination.exists():
            if destination.is_dir():
                shutil.rmtree(destination)
            else:
                destination.unlink()
        if child.is_dir():
            destination.mkdir(parents=True)
            _copy_tree(child, destination)
        elif child.is_file():
            shutil.copy2(child, destination)


def _guess_python_entry(app_dir: Path) -> dict | None:
    for relative, module in (
        ("app/main.py", "app.main"),
        ("main.py", "main"),
        ("app.py", "app"),
        ("src/main.py", "main"),
    ):
        if (app_dir / relative).is_file():
            return {
                "module": module,
                "attr": "app",
                "factory": False,
                "app_dir": "src" if relative.startswith("src/") else ".",
            }
    return None


def _find_java_artifact(artifacts_dir: Path) -> Path:
    candidates = [
        path
        for pattern in ("*.jar", "*.war")
        for path in sorted(artifacts_dir.glob(pattern))
        if not any(marker in path.name.lower() for marker in ("sources", "javadoc", "plain"))
    ]
    if not candidates:
        raise ValueError("Java deployment requires an executable JAR or WAR artifact")
    return candidates[0]


def _docker(args: list[str], *, cwd: Path, log_file: Path) -> CommandResult:
    return run_command(command=["docker", *args], cwd=cwd, log_file=log_file)


def _port_range_from_env() -> tuple[int, int]:
    try:
        start = int(os.environ.get("DEPLOY_PORT_START", "10000"))
        end = int(os.environ.get("DEPLOY_PORT_END", "19999"))
    except ValueError as exc:
        raise ValueError("DEPLOY_PORT_START and DEPLOY_PORT_END must be integers") from exc
    if start < 1024 or end > 65535 or start > end:
        raise ValueError("deployment port range must satisfy 1024 <= start <= end <= 65535")
    return start, end


def _state_dir(run_dir: Path) -> Path:
    if run_dir.parent.name == "runs":
        return run_dir.parent.parent / "deployments"
    return run_dir / "deployments"


@contextmanager
def _deployment_lock(run_dir: Path) -> Iterator[None]:
    state_dir = _state_dir(run_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "local-docker.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _find_service_container(service_key: str, cwd: Path, log_file: Path) -> str:
    result = _docker(
        ["ps", "-a", "--filter", f"label={SERVICE_LABEL}={service_key}", "--format", "{{.Names}}"],
        cwd=cwd,
        log_file=log_file,
    )
    if result.exit_code != 0:
        raise OSError("cannot query Docker containers")
    return next((line.strip() for line in result.output.splitlines() if line.strip()), "")


def _docker_used_ports(cwd: Path, log_file: Path) -> set[int]:
    result = _docker(["ps", "-a", "--format", "{{.Ports}}"], cwd=cwd, log_file=log_file)
    if result.exit_code != 0:
        raise OSError("cannot query Docker port bindings")
    return {int(port) for port in re.findall(r":(\d+)->", result.output)}


def _container_labeled_port(container: str, cwd: Path, log_file: Path) -> int | None:
    if not container:
        return None
    result = _docker(
        ["inspect", "-f", f'{{{{ index .Config.Labels "{PORT_LABEL}" }}}}', container],
        cwd=cwd,
        log_file=log_file,
    )
    if result.exit_code != 0:
        return None
    try:
        return int(result.output.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return None


def _reserve_service_port(
    *,
    run_dir: Path,
    service_key: str,
    port_start: int,
    port_end: int,
    used_ports: set[int],
    current_container: str,
    log_file: Path,
) -> int:
    registry_path = _state_dir(run_dir) / "ports.json"
    registry = _read_registry(registry_path)
    current_port = _container_labeled_port(current_container, run_dir, log_file)
    registered_port = registry.get(service_key)

    if current_port is not None and port_start <= current_port <= port_end:
        selected = current_port
    elif (
        registered_port is not None
        and port_start <= registered_port <= port_end
        and registered_port not in used_ports
    ):
        selected = registered_port
    else:
        reserved = set(registry.values()) | used_ports
        selected = _select_port(service_key, port_start, port_end, reserved)

    registry[service_key] = selected
    temp_path = registry_path.with_suffix(".tmp")
    temp_path.write_text(json.dumps(registry, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(registry_path)
    append_log(log_file, f"Allocated service port: {selected} ({port_start}-{port_end})")
    return selected


def _read_registry(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    result: dict[str, int] = {}
    for key, value in raw.items():
        try:
            result[str(key)] = int(value)
        except (TypeError, ValueError):
            continue
    return result


def _select_port(service_key: str, start: int, end: int, reserved: set[int]) -> int:
    size = end - start + 1
    offset = int(hashlib.sha256(service_key.encode()).hexdigest()[:16], 16) % size
    for index in range(size):
        candidate = start + ((offset + index) % size)
        if candidate not in reserved:
            return candidate
    raise ValueError(f"no free deployment ports in {start}-{end}")


def _compose_replace_service(
    *,
    current_container: str,
    container_name: str,
    image_name: str,
    service_key: str,
    owner: str,
    repo_name: str,
    runtime: str,
    artifact_hash: str,
    bind_address: str,
    host_port: int,
    container_port: int,
    network: str,
    public_path: str,
    cwd: Path,
    log_file: Path,
) -> bool:
    compose_check = _docker(["compose", "version"], cwd=cwd, log_file=log_file)
    if compose_check.exit_code != 0:
        raise OSError("Docker Compose plugin is unavailable; install it in the CI engine image")
    state_dir = _state_dir(cwd)
    routes_dir = state_dir / "router" / "routes"
    routes_dir.mkdir(parents=True, exist_ok=True)
    _preserve_router_routes(routes_dir, cwd=cwd, log_file=log_file)
    default_config = state_dir / "router" / "default.conf"
    default_config.write_text(_router_default_config(), encoding="utf-8")
    route_path = routes_dir / f"{container_name}.conf"
    previous_route = route_path.read_text(encoding="utf-8") if route_path.is_file() else None
    route_path.write_text(
        _router_service_config(
            public_path, container_name, container_port, service_key, runtime=runtime
        ),
        encoding="utf-8",
    )

    compose_path = state_dir / "compose.yaml"
    previous_compose = compose_path.read_text(encoding="utf-8") if compose_path.is_file() else None
    compose_data = _read_compose(compose_path)
    services = compose_data.setdefault("services", {})
    if not isinstance(services, dict):
        raise ValueError("generated deployment Compose services must be a mapping")

    effective_network = network or "capstone-internal"
    compose_data["name"] = "capstone-deployments"
    compose_data["networks"] = {
        "internal": {"external": True, "name": effective_network},
    }
    services["router"] = _router_compose_service(state_dir)
    service_name = container_name
    services[service_name] = _app_compose_service(
        container_name=container_name,
        image_name=image_name,
        service_key=service_key,
        owner=owner,
        repo_name=repo_name,
        runtime=runtime,
        artifact_hash=artifact_hash,
        bind_address=bind_address,
        host_port=host_port,
        container_port=container_port,
    )

    legacy_image = ""
    legacy_container = bool(current_container) and not _is_compose_container(
        current_container, cwd, log_file
    )
    if legacy_container:
        legacy_image = _container_image_id(current_container, cwd, log_file)
        removed = _docker(["rm", "-f", current_container], cwd=cwd, log_file=log_file)
        if removed.exit_code != 0:
            raise OSError(f"cannot migrate legacy managed container {current_container} to Compose")

    _write_compose(compose_path, compose_data)
    result = _compose(
        compose_path,
        ["up", "-d", "--no-deps", "router", service_name],
        cwd=cwd,
        log_file=log_file,
    )
    probe_host, probe_port = _compose_probe_address(container_name, container_port, host_port)
    healthy = result.exit_code == 0 and _wait_for_tcp(
        probe_host, probe_port, log_file, _startup_timeout()
    )
    if healthy:
        config_test = _docker(
            ["exec", "capstone-deploy-router", "nginx", "-t"], cwd=cwd, log_file=log_file
        )
        if config_test.exit_code == 0:
            reload_result = _docker(
                ["exec", "capstone-deploy-router", "nginx", "-s", "reload"],
                cwd=cwd,
                log_file=log_file,
            )
            healthy = reload_result.exit_code == 0
        else:
            healthy = False
    if healthy and runtime in {"react", "vue", "angular"}:
        router_host, router_port = _compose_probe_address(
            "capstone-deploy-router", 80, int(os.environ.get("DEPLOY_ROUTER_PORT", "19080")))
        healthy = _wait_for_static_http(f"http://{router_host}:{router_port}{public_path}/", log_file, _startup_timeout())
    if healthy:
        append_log(log_file, f"Compose service is active: {service_name}")
        return True

    _compose(compose_path, ["logs", "--tail", "120", service_name], cwd=cwd, log_file=log_file)
    _restore_compose_deployment(
        compose_path=compose_path,
        previous_compose=previous_compose,
        route_path=route_path,
        previous_route=previous_route,
        legacy_image=legacy_image,
        failed_compose=compose_data,
        service_name=service_name,
        cwd=cwd,
        log_file=log_file,
    )
    return False


def _preserve_router_routes(routes_dir: Path, *, cwd: Path, log_file: Path) -> None:
    """Carry all active routes over when moving the shared router's state root."""
    result = _docker(
        ["inspect", "-f", '{{range .Mounts}}{{if eq .Destination "/etc/nginx/routes"}}{{.Source}}{{end}}{{end}}',
         "capstone-deploy-router"], cwd=cwd, log_file=log_file,
    )
    if result.exit_code != 0:
        if "no such" in result.output.lower():
            return  # First deployment: there is no shared router to preserve.
        raise OSError("Cannot inspect existing shared router; refusing to replace its routes")
    if result.output.strip() == str(routes_dir):
        return
    copied = _docker(["cp", "capstone-deploy-router:/etc/nginx/routes/.", str(routes_dir)],
                     cwd=cwd, log_file=log_file)
    if copied.exit_code != 0:
        raise OSError("Cannot preserve existing shared router routes")


def _compose_probe_address(container_name: str, container_port: int, host_port: int) -> tuple[str, int]:
    # The engine is a sibling container: localhost is not the Docker host.
    if Path("/.dockerenv").exists():
        return container_name, container_port
    return "127.0.0.1", host_port


def _read_compose(path: Path) -> dict:
    if not path.is_file():
        return {"name": "capstone-deployments", "services": {}}
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot read generated Compose file: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("generated deployment Compose file must contain a mapping")
    return payload


def _write_compose(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".tmp")
    temp_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    temp_path.replace(path)


def _router_compose_service(state_dir: Path) -> dict:
    try:
        router_port = int(os.environ.get("DEPLOY_ROUTER_PORT", "19080"))
    except ValueError as exc:
        raise ValueError("DEPLOY_ROUTER_PORT must be an integer") from exc
    if not 1024 <= router_port <= 65535:
        raise ValueError("DEPLOY_ROUTER_PORT must be between 1024 and 65535")
    router_bind = os.environ.get("DEPLOY_ROUTER_BIND_ADDRESS", "127.0.0.1").strip()
    return {
        "image": "nginx:1.27-alpine",
        "container_name": "capstone-deploy-router",
        "restart": "unless-stopped",
        "ports": [f"{router_bind}:{router_port}:80"],
        "volumes": [
            {
                "type": "bind",
                "source": str(state_dir / "router" / "default.conf"),
                "target": "/etc/nginx/conf.d/default.conf",
                "read_only": True,
            },
            {
                "type": "bind",
                "source": str(state_dir / "router" / "routes"),
                "target": "/etc/nginx/routes",
                "read_only": True,
            },
        ],
        "networks": ["internal"],
    }


def _app_compose_service(
    *,
    container_name: str,
    image_name: str,
    service_key: str,
    owner: str,
    repo_name: str,
    runtime: str,
    artifact_hash: str,
    bind_address: str,
    host_port: int,
    container_port: int,
) -> dict:
    return {
        "image": image_name,
        "container_name": container_name,
        "restart": "unless-stopped",
        "environment": {
            "PORT": str(container_port),
            "HOST": "0.0.0.0",
            "HOSTNAME": "0.0.0.0",
        },
        "ports": [f"{bind_address}:{host_port}:{container_port}"],
        "labels": {
            MANAGED_LABEL: "true",
            SERVICE_LABEL: service_key,
            PORT_LABEL: str(host_port),
            "com.capstonelab.cicd.owner": owner,
            "com.capstonelab.cicd.repo": repo_name,
            "com.capstonelab.cicd.runtime": runtime,
            "com.capstonelab.cicd.artifact-hash": artifact_hash,
        },
        "networks": ["internal"],
    }


def _router_default_config() -> str:
    return (
        "map $http_upgrade $cicd_connection_upgrade { default upgrade; '' close; }\n"
        "map $http_x_real_ip $cicd_real_ip { default $http_x_real_ip; '' $remote_addr; }\n"
        "map $http_x_forwarded_host $cicd_forwarded_host { default $http_x_forwarded_host; '' $http_host; }\n"
        "map $http_x_forwarded_proto $cicd_forwarded_proto { default $http_x_forwarded_proto; '' $scheme; }\n"
        "map $http_x_forwarded_port $cicd_forwarded_port { default $http_x_forwarded_port; '' $server_port; }\n"
        "server {\n"
        "  listen 80 default_server;\n"
        "  server_name _;\n"
        "  absolute_redirect off;\n"
        "  resolver 127.0.0.11 ipv6=off valid=10s;\n"
        "  client_max_body_size 50m;\n"
        "  location = /_cicd/health { default_type application/json; return 200 '{\"status\":\"ok\"}'; }\n"
        "  include /etc/nginx/routes/*.conf;\n"
        "  location / { return 404; }\n"
        "}\n"
    )


def _router_service_config(
    public_path: str,
    container_name: str,
    container_port: int,
    service_key: str,
    *,
    runtime: str | None = None,
) -> str:
    escaped_path = re.escape(public_path)
    proxy = (
        f"  set $cicd_upstream {container_name}:{container_port};\n"
        "{rewrite}"
        "  proxy_pass http://$cicd_upstream;\n"
        "  proxy_http_version 1.1;\n"
        "  proxy_set_header Upgrade $http_upgrade;\n"
        "  proxy_set_header Connection $cicd_connection_upgrade;\n"
        "  proxy_set_header Host $http_host;\n"
        "  proxy_set_header X-Real-IP $cicd_real_ip;\n"
        "  proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n"
        "  proxy_set_header X-Forwarded-Host $cicd_forwarded_host;\n"
        "  proxy_set_header X-Forwarded-Proto $cicd_forwarded_proto;\n"
        "  proxy_set_header X-Forwarded-Port $cicd_forwarded_port;\n"
        f"  proxy_set_header X-Forwarded-Prefix {public_path};\n"
        f"  add_header X-CICD-Service {service_key} always;\n"
    )
    if runtime == "python":
        root = f"location = {public_path}/ {{ return 302 {public_path}/docs; }}\n"
    elif runtime in ROOT_FALLBACK_RUNTIMES:
        # API-only apps often map nothing at "/". Browsers opening the
        # deployment URL then get the framework's bare 404, which reads as a
        # failed deployment. Only that one case is replaced by a landing page;
        # every other path, method and status still comes from the app.
        fallback = "@cicd_root_" + re.sub(r"[^A-Za-z0-9_]", "_", container_name)
        root = (
            f"location = {public_path}/ {{\n"
            + proxy.replace("{rewrite}", "  rewrite ^ / break;\n")
            + "  proxy_intercept_errors on;\n"
            f"  error_page 404 = {fallback};\n"
            "}\n"
            f"location {fallback} {{\n"
            '  set $cicd_root_client "$request_method:$http_accept";\n'
            '  if ($cicd_root_client !~* "^(GET|HEAD):.*text/html") { return 404; }\n'
            "  default_type text/html;\n"
            "  charset utf-8;\n"
            f"  add_header X-CICD-Service {service_key} always;\n"
            "  add_header X-CICD-Root-Fallback 1 always;\n"
            "  add_header Cache-Control no-store always;\n"
            f"  return 200 '{_root_fallback_page(public_path)}';\n"
            "}\n"
        )
    else:
        root = ""
    return (
        f"location = {public_path} {{ return 301 {public_path}/; }}\n"
        f"{root}"
        f"location ^~ {public_path}/ {{\n"
        + proxy.replace("{rewrite}", f"  rewrite ^{escaped_path}/(.*)$ /$1 break;\n")
        + "}\n"
    )


def _root_fallback_page(public_path: str) -> str:
    """Landing page for a running service with no handler at "/".

    The result is embedded in a single-quoted nginx string, so it must not
    contain a quote, a backslash or "$" (nginx would expand it as a variable).
    """
    safe_path = re.sub(r"[^A-Za-z0-9._/-]", "", public_path)
    service = "/".join(safe_path.rsplit("/", 2)[-2:])
    return (
        '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{service} · 실행 중</title>"
        "<style>"
        ":root{color-scheme:light dark}"
        "body{margin:0;min-height:100vh;display:grid;place-items:center;"
        "font-family:system-ui,sans-serif;background:Canvas;color:CanvasText}"
        "main{max-width:34rem;padding:2rem 1.25rem;line-height:1.6}"
        "h1{font-size:1.4rem;margin:.6rem 0 1rem;word-break:break-all}"
        ".ok{display:inline-block;padding:.15rem .6rem;border-radius:999px;"
        "background:#16a34a;color:#fff;font-size:.8rem;font-weight:600}"
        "</style></head><body><main>"
        '<span class="ok">실행 중 · Running</span>'
        f"<h1>{service}</h1>"
        "<p>서비스는 정상적으로 배포되어 실행 중입니다.</p>"
        "</main></body></html>"
    )


def _probe_root_status(host: str, port: int, log_file: Path, attempts: int = 3) -> int | None:
    """HTTP status of the app's own "/" (redirects not followed), or None."""
    last_error = ""
    for attempt in range(attempts):
        connection = HTTPConnection(host, port, timeout=5)
        try:
            connection.request("GET", "/", headers={"Accept": "text/html,*/*"})
            status = connection.getresponse().status
            append_log(log_file, f"Service root path responded with HTTP {status}")
            return status
        except (OSError, HTTPException) as exc:
            last_error = str(exc)
            if attempt + 1 < attempts:
                time.sleep(1)
        finally:
            connection.close()
    append_log(log_file, f"Service root path could not be probed: {last_error}")
    return None


def _compose(
    compose_path: Path, args: list[str], *, cwd: Path, log_file: Path
) -> CommandResult:
    return _docker(
        ["compose", "-p", "capstone-deployments", "-f", str(compose_path), *args],
        cwd=cwd,
        log_file=log_file,
    )


def _is_compose_container(container: str, cwd: Path, log_file: Path) -> bool:
    result = _docker(
        ["inspect", "-f", '{{ index .Config.Labels "com.docker.compose.project" }}', container],
        cwd=cwd,
        log_file=log_file,
    )
    return result.exit_code == 0 and result.output.strip().splitlines()[-1:] == [
        "capstone-deployments"
    ]


def _container_image_id(container: str, cwd: Path, log_file: Path) -> str:
    result = _docker(["inspect", "-f", "{{.Image}}", container], cwd=cwd, log_file=log_file)
    if result.exit_code != 0:
        return ""
    return result.output.strip().splitlines()[-1] if result.output.strip() else ""


def _restore_compose_deployment(
    *,
    compose_path: Path,
    previous_compose: str | None,
    route_path: Path,
    previous_route: str | None,
    legacy_image: str,
    failed_compose: dict,
    service_name: str,
    cwd: Path,
    log_file: Path,
) -> None:
    if previous_route is None:
        route_path.unlink(missing_ok=True)
    else:
        route_path.write_text(previous_route, encoding="utf-8")

    if previous_compose is not None:
        compose_path.write_text(previous_compose, encoding="utf-8")
        previous_data = _read_compose(compose_path)
        previous_services = previous_data.get("services", {})
        if isinstance(previous_services, dict) and service_name in previous_services:
            _compose(compose_path, ["up", "-d", "--no-deps", "router", service_name], cwd=cwd, log_file=log_file)
            append_log(log_file, f"Rolled back Compose service: {service_name}")
            return

    if legacy_image:
        services = failed_compose.get("services", {})
        if isinstance(services, dict) and isinstance(services.get(service_name), dict):
            services[service_name]["image"] = legacy_image
            _write_compose(compose_path, failed_compose)
            _compose(compose_path, ["up", "-d", "--no-deps", "router", service_name], cwd=cwd, log_file=log_file)
            append_log(log_file, f"Rolled back migrated service image: {service_name}")
            return

    _compose(compose_path, ["rm", "-s", "-f", service_name], cwd=cwd, log_file=log_file)
    services = failed_compose.get("services", {})
    if isinstance(services, dict):
        services.pop(service_name, None)
    _write_compose(compose_path, failed_compose)


def _replace_container(
    *,
    current_container: str,
    container_name: str,
    image_name: str,
    service_key: str,
    owner: str,
    repo_name: str,
    runtime: str,
    artifact_hash: str,
    bind_address: str,
    host_port: int,
    container_port: int,
    network: str,
    health_host: str,
    cwd: Path,
    log_file: Path,
) -> bool:
    backup = ""
    if current_container:
        backup = f"{container_name}-rollback-{int(time.time())}"
        stopped = _docker(["stop", "--timeout", "20", current_container], cwd=cwd, log_file=log_file)
        if stopped.exit_code != 0:
            raise OSError(f"cannot stop existing container {current_container}")
        renamed = _docker(["rename", current_container, backup], cwd=cwd, log_file=log_file)
        if renamed.exit_code != 0:
            _docker(["start", current_container], cwd=cwd, log_file=log_file)
            raise OSError(f"cannot preserve existing container {current_container} for rollback")

    args = [
        "run",
        "-d",
        "--name",
        container_name,
        "--restart",
        "unless-stopped",
        "--label",
        f"{MANAGED_LABEL}=true",
        "--label",
        f"{SERVICE_LABEL}={service_key}",
        "--label",
        f"{PORT_LABEL}={host_port}",
        "--label",
        f"com.capstonelab.cicd.owner={owner}",
        "--label",
        f"com.capstonelab.cicd.repo={repo_name}",
        "--label",
        f"com.capstonelab.cicd.runtime={runtime}",
        "--label",
        f"com.capstonelab.cicd.artifact-hash={artifact_hash}",
        "-p",
        f"{bind_address}:{host_port}:{container_port}",
    ]
    if network:
        args.extend(["--network", network])
    args.extend(["-e", f"PORT={container_port}", "-e", "HOST=0.0.0.0", image_name])

    started = _docker(args, cwd=cwd, log_file=log_file)
    healthy = started.exit_code == 0 and _wait_for_tcp(
        health_host, host_port, log_file, _startup_timeout()
    )
    if healthy:
        if backup:
            _docker(["rm", backup], cwd=cwd, log_file=log_file)
        return True

    # A failed `docker run` can mean the desired name belongs to an unrelated
    # container. Only inspect/remove the new container when Docker confirmed
    # that this invocation actually created it.
    if started.exit_code == 0:
        _docker(["logs", "--tail", "120", container_name], cwd=cwd, log_file=log_file)
        _docker(["rm", "-f", container_name], cwd=cwd, log_file=log_file)
    if backup:
        _docker(["rename", backup, current_container], cwd=cwd, log_file=log_file)
        _docker(["start", current_container], cwd=cwd, log_file=log_file)
        append_log(log_file, f"Rolled back to previous container: {current_container}")
    return False


def _startup_timeout() -> int:
    try:
        return max(5, int(os.environ.get("DEPLOY_STARTUP_TIMEOUT_SEC", "90")))
    except ValueError:
        return 90


def _wait_for_tcp(host: str, port: int, log_file: Path, timeout: int) -> bool:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=2):
                append_log(log_file, f"Container is reachable at {host}:{port}")
                return True
        except OSError as exc:
            last_error = str(exc)
            time.sleep(1)
    append_log(log_file, f"Container startup timed out at {host}:{port}: {last_error}")
    return False
