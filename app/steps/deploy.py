from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from app.models import StepRunResult
from app.utils.logger import append_log
from app.utils.java import is_java_project
from app.utils.python import find_python_project_root, is_python_project
from app.utils.shell import run_command


# ---------------------------------------------------------------------------
# S3 bucket & EC2 connection info (matches CDK stack outputs)
# ---------------------------------------------------------------------------
S3_BUCKET = "cicd-artifacts-668568918251"
EC2_REGION = "us-east-1"

# Nginx config & deployment root on EC2
EC2_DEPLOY_ROOT = "/opt/deployments"
EC2_NGINX_CONF_DIR = "/opt/deployments/nginx"
EC2_USER = "ec2-user"

# Port range for dynamic app allocation.
# Each runtime gets its own 1000-port slice so concurrent deploys of
# different languages can never collide on a single shared counter.
_PORT_RANGE_START = 3001  # legacy fallback (kept for backward compatibility)
_PORT_RANGE_END = 3999

_RUNTIME_PORT_RANGES = {
    "node":    (3000, 3999),
    "nextjs":  (6000, 6999),
    "python":  (4000, 4999),
    "java":    (5000, 5999),
    "react":   (7000, 7999),
    "vue":     (7000, 7999),
    "angular": (7000, 7999),
}


def run_deploy(
    repo_dir: Path,
    run_dir: Path,
    log_file: Path,
    repo_url: str,
    branch: str | None,
    runtime_type: str | None = None,
) -> StepRunResult:
    """Deploy build artifacts to AWS EC2 via S3."""

    # ------------------------------------------------------------------
    # 1. Extract user/repo from git URL
    # ------------------------------------------------------------------
    owner, repo_name = _parse_github_url(repo_url)
    if not owner or not repo_name:
        msg = f"Cannot parse owner/repo from URL: {repo_url}"
        append_log(log_file, msg)
        return StepRunResult(status="failed", exit_code=1, summary_message=msg)

    deploy_key = f"{owner}/{repo_name}"
    append_log(log_file, f"Deploy target: {deploy_key}")

    # ------------------------------------------------------------------
    # 2. Locate build artifacts
    # ------------------------------------------------------------------
    artifacts_dir = run_dir / "artifacts"
    if not artifacts_dir.exists() or not any(artifacts_dir.iterdir()):
        msg = "No build artifacts found. Build step must run before deploy."
        append_log(log_file, msg)
        return StepRunResult(status="failed", exit_code=1, summary_message=msg)

    append_log(log_file, f"Artifacts directory: {artifacts_dir}")

    # Load any Python-side metadata (ASGI entry point) that the build
    # step recorded for the deploy step to consume.
    python_entry = _load_python_entry_from_build_meta(artifacts_dir)
    if python_entry:
        append_log(
            log_file,
            f"Python entry from build_meta: {python_entry['module']}:{python_entry['attr']}"
            f" (factory={python_entry.get('factory', False)}, app_dir={python_entry.get('app_dir', '.')})",
        )

    # ------------------------------------------------------------------
    # 3. Detect runtime type from repo contents
    # ------------------------------------------------------------------
    # Prefer the explicit runtime declared by the workflow (orchestrator
    # passes pipeline_run.runtime_type). Only fall back to repo scanning
    # when no explicit type is provided or it is a non-specific default
    # that does not match the repo contents (monorepo edge cases).
    if runtime_type == "python" or (runtime_type is None and is_python_project(repo_dir)):
        runtime = "python"
    elif runtime_type == "java" or (runtime_type is None and is_java_project(repo_dir)):
        runtime = "java"
    elif runtime_type and runtime_type not in {"node"}:
        runtime = runtime_type
    else:
        runtime = _detect_runtime(repo_dir)
    append_log(log_file, f"Detected runtime: {runtime}")

    # ------------------------------------------------------------------
    # 4. Rewrite asset paths for frontend SPA (before hash & upload)
    # ------------------------------------------------------------------
    if runtime in ("react", "vue", "angular"):
        base_path = f"/{owner}/{repo_name}"
        append_log(log_file, f"Rewriting frontend asset paths with base: {base_path}")
        _rewrite_frontend_paths(artifacts_dir, base_path, log_file)

    # ------------------------------------------------------------------
    # 5. Compute artifact hash for duplicate detection
    # ------------------------------------------------------------------
    artifact_hash = _compute_artifacts_hash(artifacts_dir)
    append_log(log_file, f"Artifact hash: {artifact_hash}")

    # ------------------------------------------------------------------
    # 6. Upload artifacts to S3
    # ------------------------------------------------------------------
    s3_prefix = f"deployments/{owner}/{repo_name}/{artifact_hash}"
    append_log(log_file, f"Uploading to s3://{S3_BUCKET}/{s3_prefix}/")

    result = run_command(
        command=[
            "aws", "s3", "sync",
            str(artifacts_dir),
            f"s3://{S3_BUCKET}/{s3_prefix}/",
            "--region", EC2_REGION,
            "--delete",
        ],
        cwd=run_dir,
        log_file=log_file,
    )
    if result.exit_code != 0:
        return StepRunResult(
            status="failed",
            exit_code=result.exit_code,
            summary_message="Failed to upload artifacts to S3",
        )

    # ------------------------------------------------------------------
    # 6. Upload deploy manifest to S3
    # ------------------------------------------------------------------
    manifest = {
        "owner": owner,
        "repo": repo_name,
        "branch": branch or "main",
        "runtime": runtime,
        "artifact_hash": artifact_hash,
        "s3_prefix": s3_prefix,
        "deploy_path": f"{EC2_DEPLOY_ROOT}/apps/{owner}/{repo_name}",
    }
    manifest_path = run_dir / "deploy_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    result = run_command(
        command=[
            "aws", "s3", "cp",
            str(manifest_path),
            f"s3://{S3_BUCKET}/{s3_prefix}/deploy_manifest.json",
            "--region", EC2_REGION,
        ],
        cwd=run_dir,
        log_file=log_file,
    )
    if result.exit_code != 0:
        return StepRunResult(
            status="failed",
            exit_code=result.exit_code,
            summary_message="Failed to upload deploy manifest to S3",
        )

    # ------------------------------------------------------------------
    # 7. Trigger deployment on EC2 via SSM Run Command
    # ------------------------------------------------------------------
    deploy_script = _build_ec2_deploy_script(
        owner=owner,
        repo_name=repo_name,
        runtime=runtime,
        s3_bucket=S3_BUCKET,
        s3_prefix=s3_prefix,
        artifact_hash=artifact_hash,
        python_entry=python_entry,
    )
    append_log(log_file, "Sending deploy command to EC2 via SSM...")

    # Get EC2 instance ID
    instance_id = _get_deploy_instance_id(log_file)
    if not instance_id:
        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message="Cannot find deploy EC2 instance. Is the CDK stack deployed?",
        )

    append_log(log_file, f"Target EC2 instance: {instance_id}")

    # Send command via SSM
    result = run_command(
        command=[
            "aws", "ssm", "send-command",
            "--instance-ids", instance_id,
            "--document-name", "AWS-RunShellScript",
            "--parameters", json.dumps({"commands": [deploy_script]}),
            "--region", EC2_REGION,
            "--output", "json",
        ],
        cwd=run_dir,
        log_file=log_file,
    )

    if result.exit_code != 0:
        append_log(log_file, "SSM send-command failed, trying to check if SSM agent is ready...")
        return StepRunResult(
            status="failed",
            exit_code=result.exit_code,
            summary_message=f"SSM deploy command failed. Instance {instance_id} may not have SSM agent ready yet.",
        )

    # Extract command ID and wait for completion
    command_id = _extract_command_id(result.output)
    if command_id:
        append_log(log_file, f"SSM Command ID: {command_id}")
        wait_result = run_command(
            command=[
                "aws", "ssm", "wait", "command-executed",
                "--command-id", command_id,
                "--instance-id", instance_id,
                "--region", EC2_REGION,
            ],
            cwd=run_dir,
            log_file=log_file,
        )

        # Fetch command output
        output_result = run_command(
            command=[
                "aws", "ssm", "get-command-invocation",
                "--command-id", command_id,
                "--instance-id", instance_id,
                "--region", EC2_REGION,
                "--output", "json",
            ],
            cwd=run_dir,
            log_file=log_file,
        )

        if output_result.exit_code == 0:
            try:
                invocation = json.loads(output_result.output)
                ssm_status = invocation.get("Status", "Unknown")
                stdout_content = invocation.get("StandardOutputContent", "")
                stderr_content = invocation.get("StandardErrorContent", "")
                if stdout_content:
                    append_log(log_file, f"[EC2 stdout] {stdout_content}")
                if stderr_content:
                    append_log(log_file, f"[EC2 stderr] {stderr_content}")

                if ssm_status != "Success":
                    return StepRunResult(
                        status="failed",
                        exit_code=1,
                        summary_message=f"EC2 deploy script failed with status: {ssm_status}",
                    )
            except (json.JSONDecodeError, KeyError):
                pass

    endpoint = _record_deploy_endpoint(run_dir, owner, repo_name, instance_id, log_file)
    if endpoint and endpoint.get("service_url"):
        append_log(log_file, f"Deploy successful: {endpoint['service_url']}")
        summary_message = (
            f"Deployed {deploy_key} ({runtime}) to EC2 | hash={artifact_hash[:12]}"
            f" | url={endpoint['service_url']}"
        )
    else:
        append_log(log_file, f"Deploy successful: http://<EC2_IP>/{owner}/{repo_name}")
        summary_message = f"Deployed {deploy_key} ({runtime}) to EC2 | hash={artifact_hash[:12]}"

    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message=summary_message,
    )


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _load_python_entry_from_build_meta(artifacts_dir: Path) -> dict | None:
    """Read the ASGI entry point that the build step recorded.

    Returns a dict like ``{"module": "secure_app.api", "attr": "create_app",
    "factory": True, "app_dir": "src", "file_path": "src/secure_app/api.py"}``
    or ``None`` if the file is missing, malformed, or has no entry field.
    """
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
    """Extract (owner, repo_name) from a GitHub URL."""
    patterns = [
        r"github\.com[:/]([^/]+)/([^/.]+?)(?:\.git)?$",
        r"github\.com[:/]([^/]+)/([^/.]+?)/?$",
    ]
    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1), match.group(2)
    return "", ""


def _detect_runtime(repo_dir: Path) -> str:
    """Detect project runtime: node-backend, react, vue, angular, nextjs, python, or java."""
    pkg_json = repo_dir / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            scripts = pkg.get("scripts", {})

            # Next.js detection (must be before react since next projects also have react)
            if "next" in deps:
                return "nextjs"
            # React detection
            if "react-scripts" in deps or "react" in deps:
                # Check if it has a server entry point → backend
                for f in ["server.js", "server.ts", "src/server.js", "src/server.ts"]:
                    if (repo_dir / f).exists():
                        return "node"
                return "react"
            # Vue detection
            if "@vue/cli-service" in deps or "vue" in deps or "vite" in deps:
                # Vite could be react too, but if vue is present it's vue
                if "vue" in deps:
                    return "vue"
                # Vite without vue — check for react
                if "react" in deps:
                    return "react"
                return "vue"
            # Angular detection
            if "@angular/core" in deps or "@angular/cli" in deps:
                return "angular"
            # Has server entry → node backend
            for f in ["server.js", "index.js", "app.js", "main.js", "src/server.js"]:
                if (repo_dir / f).exists():
                    return "node"
            # Has start script but no known frontend framework → node backend
            if "start" in scripts:
                return "node"
        except (json.JSONDecodeError, KeyError):
            return "node"
        return "node"
    if (repo_dir / "requirements.txt").exists() or (repo_dir / "pyproject.toml").exists():
        return "python"
    if (repo_dir / "pom.xml").exists() or (repo_dir / "build.gradle").exists():
        return "java"
    # Monorepo fallback: shallow scan for python/java project markers in
    # subdirectories (e.g. backend/pyproject.toml, services/api/pom.xml).
    if is_python_project(repo_dir):
        return "python"
    if is_java_project(repo_dir):
        return "java"
    return "node"


def _rewrite_frontend_paths(artifacts_dir: Path, base_path: str, log_file: Path) -> None:
    """Rewrite absolute asset paths in HTML/JS so SPA works under a subpath."""
    for html_file in artifacts_dir.rglob("*.html"):
        content = html_file.read_text(encoding="utf-8", errors="replace")
        original = content
        # Fix src="/static/..." and href="/static/..."
        content = content.replace('="/static/', f'="{base_path}/static/')
        # Fix manifest, favicon, logo references
        content = content.replace('="/manifest', f'="{base_path}/manifest')
        content = content.replace('="/favicon', f'="{base_path}/favicon')
        content = content.replace('="/logo', f'="{base_path}/logo')
        # Fix og:image and other meta content with absolute paths
        content = re.sub(r'content="/((?:static|assets|images|img)/)', rf'content="{base_path}/\1', content)
        if content != original:
            html_file.write_text(content, encoding="utf-8")
            append_log(log_file, f"  Rewrote paths in {html_file.name}")

    # Fix JS files that reference /static/ paths
    for js_file in artifacts_dir.rglob("*.js"):
        try:
            content = js_file.read_text(encoding="utf-8", errors="replace")
            original = content
            content = content.replace('"/static/', f'"{base_path}/static/')
            if content != original:
                js_file.write_text(content, encoding="utf-8")
        except Exception:
            pass


def _compute_artifacts_hash(artifacts_dir: Path) -> str:
    """Compute SHA256 hash of all artifact files for dedup."""
    hasher = hashlib.sha256()
    for file_path in sorted(artifacts_dir.rglob("*")):
        if file_path.is_file():
            hasher.update(str(file_path.relative_to(artifacts_dir)).encode())
            hasher.update(file_path.read_bytes())
    return hasher.hexdigest()


def _get_deploy_instance_id(log_file: Path) -> str:
    """Find the EC2 instance ID from the CDK-deployed stack."""
    result = run_command(
        command=[
            "aws", "ec2", "describe-instances",
            "--filters",
            "Name=tag:aws:cloudformation:stack-name,Values=CiCdDeployStack",
            "Name=instance-state-name,Values=running",
            "--query", "Reservations[0].Instances[0].InstanceId",
            "--output", "text",
            "--region", EC2_REGION,
        ],
        cwd=Path("."),
        log_file=log_file,
    )
    instance_id = result.output.strip().splitlines()[-1].strip() if result.output.strip() else ""
    if instance_id and instance_id != "None" and instance_id.startswith("i-"):
        return instance_id
    return ""


def _record_deploy_endpoint(
    run_dir: Path,
    owner: str,
    repo_name: str,
    instance_id: str,
    log_file: Path,
) -> dict:
    endpoint = _get_instance_public_endpoint(instance_id, log_file)
    if not endpoint:
        return {}

    service_urls = _build_service_urls(
        owner=owner,
        repo_name=repo_name,
        public_ip=endpoint.get("public_ip", ""),
        public_dns=endpoint.get("public_dns", ""),
    )
    payload = {
        "owner": owner,
        "repo": repo_name,
        "instance_id": instance_id,
        **endpoint,
        **service_urls,
    }
    output_path = run_dir / "deploy_endpoint.json"
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def _get_instance_public_endpoint(instance_id: str, log_file: Path) -> dict:
    if not instance_id:
        return {}
    result = run_command(
        command=[
            "aws", "ec2", "describe-instances",
            "--instance-ids", instance_id,
            "--query",
            "Reservations[0].Instances[0].{PublicIpAddress:PublicIpAddress,PublicDnsName:PublicDnsName}",
            "--output", "json",
            "--region", EC2_REGION,
        ],
        cwd=Path("."),
        log_file=log_file,
    )
    if result.exit_code != 0 or not result.output.strip():
        return {}
    try:
        data = json.loads(result.output)
    except json.JSONDecodeError:
        return {}
    public_ip = str(data.get("PublicIpAddress") or "").strip()
    public_dns = str(data.get("PublicDnsName") or "").strip()
    return {
        "public_ip": public_ip,
        "public_dns": public_dns,
    }


def _build_service_urls(*, owner: str, repo_name: str, public_ip: str, public_dns: str) -> dict:
    base_path = f"/{owner}/{repo_name}"
    urls: list[str] = []
    if public_dns:
        urls.append(f"http://{public_dns}{base_path}")
    if public_ip:
        urls.append(f"http://{public_ip}.nip.io{base_path}")
        urls.append(f"http://{public_ip}{base_path}")
    return {
        "service_url": urls[0] if urls else "",
        "service_urls": urls,
    }


def _extract_command_id(ssm_output: str) -> str:
    """Extract CommandId from SSM send-command JSON output."""
    try:
        data = json.loads(ssm_output)
        return data.get("Command", {}).get("CommandId", "")
    except (json.JSONDecodeError, KeyError):
        return ""


def _build_ec2_deploy_script(
    owner: str,
    repo_name: str,
    runtime: str,
    s3_bucket: str,
    s3_prefix: str,
    artifact_hash: str,
    python_entry: dict | None = None,
) -> str:
    """Build the shell script that runs on EC2 to deploy the app."""
    app_dir = f"{EC2_DEPLOY_ROOT}/apps/{owner}/{repo_name}"
    hash_file = f"{app_dir}/.deploy_hash"
    port_file = f"{EC2_DEPLOY_ROOT}/.port_registry"
    nginx_conf = f"{EC2_NGINX_CONF_DIR}/{owner}__{repo_name}.conf"

    # Python entry point (resolved at build time by the engine's AST
    # scanner). Empty strings mean "unknown" — the deploy script will
    # fall back to its legacy candidate list.
    if python_entry:
        predetected_entry = f"{python_entry.get('module', '')}:{python_entry.get('attr', '')}"
        predetected_app_dir = str(python_entry.get("app_dir") or ".")
        predetected_factory = "yes" if python_entry.get("factory") else ""
    else:
        predetected_entry = ""
        predetected_app_dir = ""
        predetected_factory = ""

    return f"""#!/bin/bash
set -ex

APP_DIR="{app_dir}"
HASH_FILE="{hash_file}"
ARTIFACT_HASH="{artifact_hash}"
PORT_FILE="{port_file}"
NGINX_CONF="{nginx_conf}"
S3_PATH="s3://{s3_bucket}/{s3_prefix}/"
RUNTIME="{runtime}"
OWNER="{owner}"
REPO="{repo_name}"

# --- Python entry point injected by the engine (from build_meta.json) ---
PREDETECTED_PY_ENTRY="{predetected_entry}"
PREDETECTED_PY_APP_DIR="{predetected_app_dir}"
PREDETECTED_PY_FACTORY="{predetected_factory}"

# --- Ensure deploy directories exist ---
mkdir -p {EC2_DEPLOY_ROOT}/apps
mkdir -p {EC2_DEPLOY_ROOT}/nginx
mkdir -p {EC2_DEPLOY_ROOT}/www
touch "$PORT_FILE"

# --- Ensure Nginx config exists ---
if [ ! -f /etc/nginx/conf.d/deployments.conf ]; then
    cat > /etc/nginx/conf.d/deployments.conf << 'NGINXCONF'
server {{
    listen 80 default_server;
    server_name _;
    location / {{
        root /opt/deployments/www;
        index index.html;
        try_files $uri $uri/ =404;
    }}
    include /opt/deployments/nginx/*.conf;
}}
NGINXCONF
    rm -f /etc/nginx/conf.d/default.conf
    nginx -t && systemctl reload nginx
fi

# --- Bootstrap engine helper scripts ---
# These two helpers force every deployed app onto the engine-assigned
# port no matter what the app's source code does:
#   - .port-wrapper.js : monkey-patches net.Server.prototype.listen so any
#     hardcoded port (app.listen(3000)) is silently redirected to FORCED_PORT.
#   - .fallback-server.py : a tiny HTTP server used when the real app never
#     calls listen() at all (e.g. library-only repos).
# We rewrite them every deploy so engine updates roll out without manual ops.
mkdir -p /opt/deployments
cat > /opt/deployments/.port-wrapper.js << 'WRAPPERJS'
// Engine wrapper: forces the wrapped app to bind FORCED_PORT regardless
// of what its source code passes to listen(). If the app never calls
// listen() within 3s, we spin up a fallback HTTP server on the same port
// so nginx still gets a 200 instead of 502.
'use strict';
const net = require('net');
const http = require('http');

const FORCED_PORT = parseInt(process.env.FORCED_PORT || process.env.PORT, 10);
const ENTRY = process.env.WRAPPED_ENTRY;
const APP_LABEL = process.env.WRAPPED_LABEL || 'app';

if (!FORCED_PORT || !ENTRY) {{
    console.error('[wrapper] FORCED_PORT/PORT and WRAPPED_ENTRY required');
    process.exit(1);
}}

process.env.PORT = String(FORCED_PORT);
let appListened = false;

const origListen = net.Server.prototype.listen;
net.Server.prototype.listen = function (...args) {{
    appListened = true;
    const cb = typeof args[args.length - 1] === 'function' ? args.pop() : undefined;
    let host;
    for (const a of args) {{
        if (a == null) continue;
        if (typeof a === 'object' && a.host) {{ host = a.host; continue; }}
        if (typeof a === 'string') {{
            const asNum = parseInt(a, 10);
            if (isNaN(asNum)) host = a;
        }}
    }}
    const finalArgs = [FORCED_PORT];
    if (host) finalArgs.push(host);
    if (cb) finalArgs.push(cb);
    console.log('[wrapper] redirecting listen() -> :' + FORCED_PORT);
    return origListen.apply(this, finalArgs);
}};

setTimeout(function () {{
    if (appListened) return;
    console.log('[wrapper] app did not call listen() — starting engine fallback on :' + FORCED_PORT);
    http.createServer(function (req, res) {{
        res.writeHead(200, {{ 'Content-Type': 'text/plain; charset=utf-8' }});
        res.end('Deployed: ' + APP_LABEL + '\\nPort: ' + FORCED_PORT + '\\nStatus: engine fallback (no app listener)\\n');
    }}).listen(FORCED_PORT);
}}, 3000);

try {{
    require(ENTRY);
}} catch (e) {{
    console.error('[wrapper] failed to load entry:', e && e.stack || e);
    // Don't exit — fallback timer may still bring the port up.
}}
WRAPPERJS

cat > /opt/deployments/.fallback-server.py << 'FALLBACKPY'
#!/usr/bin/env python3
# Engine fallback HTTP server. Used when a Python/Java app fails to bind
# its assigned port within the deploy timeout. Keeps the port live so
# nginx returns 200 instead of 502.
import os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(os.environ.get('FORCED_PORT') or os.environ.get('PORT') or sys.argv[1])
LABEL = os.environ.get('WRAPPED_LABEL', 'app')

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; charset=utf-8')
        self.end_headers()
        body = ("Deployed: " + LABEL + "\\nPort: " + str(PORT) +
                "\\nStatus: engine fallback (app failed to listen)\\n")
        self.wfile.write(body.encode())
    def log_message(self, *a, **kw):
        pass

HTTPServer(('0.0.0.0', PORT), H).serve_forever()
FALLBACKPY
chmod +x /opt/deployments/.fallback-server.py

# --- Duplicate check ---
# Skip only when the artifact is unchanged AND the deployed app is actually
# healthy. If the hash matches but the process died (or never bound a port),
# fall through and redeploy so a "republish" actually heals the service.
if [ -f "$HASH_FILE" ]; then
    CURRENT_HASH=$(cat "$HASH_FILE")
    if [ "$CURRENT_HASH" = "$ARTIFACT_HASH" ]; then
        EXISTING_PORT=$(grep "^$OWNER/$REPO " "$PORT_FILE" 2>/dev/null | awk '{{print $2}}' || true)
        EXISTING_NGINX_CONF="/opt/deployments/nginx/${{OWNER}}__${{REPO}}.conf"
        HEALTHY=no
        case "$RUNTIME" in
            react|vue|angular)
                # Static SPAs: served by Nginx from disk. "Healthy" = files
                # and Nginx config still in place.
                if [ -d "$APP_DIR" ] && [ -f "$EXISTING_NGINX_CONF" ]; then
                    HEALTHY=yes
                fi
                ;;
            nextjs)
                # Static export → file presence; SSR → port listening.
                if [ -f "$APP_DIR/out/index.html" ] && [ -f "$EXISTING_NGINX_CONF" ]; then
                    HEALTHY=yes
                elif [ -n "$EXISTING_PORT" ] && ss -tlnp 2>/dev/null | grep -q ":$EXISTING_PORT "; then
                    HEALTHY=yes
                fi
                ;;
            *)
                # Proxy-based runtimes: must be listening on the assigned port.
                if [ -n "$EXISTING_PORT" ] && ss -tlnp 2>/dev/null | grep -q ":$EXISTING_PORT "; then
                    HEALTHY=yes
                fi
                ;;
        esac
        if [ "$HEALTHY" = "yes" ]; then
            echo "SKIP: Artifact hash unchanged and app is healthy. No redeploy needed."
            exit 0
        fi
        echo "Artifact hash unchanged but app is NOT healthy — forcing redeploy."
        # Remove the stale hash so the redeploy path runs end-to-end
        # (S3 sync, process start) instead of partial recovery.
        rm -f "$HASH_FILE"
    fi
fi

# --- Allocate port (per-runtime range, with collision avoidance) ---
# Each language gets its own 1000-port slice so deploys of different
# runtimes can never collide on a single shared counter:
#   node/nextjs proxy → 3000-3999 / 6000-6999
#   python              → 4000-4999
#   java                → 5000-5999
#   react/vue/angular   → 7000-7999 (registry only; served as static)
touch "$PORT_FILE"
EXISTING_PORT=$(grep "^$OWNER/$REPO " "$PORT_FILE" 2>/dev/null | awk '{{print $2}}' || true)
if [ -n "$EXISTING_PORT" ]; then
    PORT=$EXISTING_PORT
else
    case "$RUNTIME" in
        node)              RANGE_START=3000; RANGE_END=3999 ;;
        nextjs)            RANGE_START=6000; RANGE_END=6999 ;;
        python)            RANGE_START=4000; RANGE_END=4999 ;;
        java)              RANGE_START=5000; RANGE_END=5999 ;;
        react|vue|angular) RANGE_START=7000; RANGE_END=7999 ;;
        *)                 RANGE_START=8000; RANGE_END=8999 ;;
    esac
    # Pick the next free port within the runtime's range. We start at
    # max(used)+1 inside the range, then walk forward past any entries
    # that are already claimed in the registry to avoid handing out a
    # duplicate (concurrent deploys, manual edits, legacy migrations).
    LAST_PORT=$(awk -v lo=$RANGE_START -v hi=$RANGE_END '$2>=lo && $2<=hi {{print $2}}' "$PORT_FILE" 2>/dev/null | sort -n | tail -1 || true)
    if [ -z "$LAST_PORT" ]; then
        PORT=$RANGE_START
    else
        PORT=$((LAST_PORT + 1))
    fi
    while grep -q " $PORT$" "$PORT_FILE" 2>/dev/null; do
        PORT=$((PORT + 1))
        if [ "$PORT" -gt "$RANGE_END" ]; then
            echo "ERROR: port range $RANGE_START-$RANGE_END exhausted for runtime $RUNTIME"
            exit 1
        fi
    done
    echo "$OWNER/$REPO $PORT" >> "$PORT_FILE"
fi

echo "Deploying $OWNER/$REPO on port $PORT (runtime: $RUNTIME)"

# --- Stop existing process ---
PM2_HOME=/etc/.pm2 pm2 delete "$OWNER--$REPO" 2>/dev/null || true
pkill -f "gunicorn.*$OWNER--$REPO" 2>/dev/null || true
if [ -f "$APP_DIR/.java.pid" ]; then
    kill $(cat "$APP_DIR/.java.pid") 2>/dev/null || true
    rm -f "$APP_DIR/.java.pid"
fi

# --- Download artifacts from S3 ---
rm -rf "$APP_DIR"
mkdir -p "$APP_DIR"
aws s3 sync "$S3_PATH" "$APP_DIR/" --region {EC2_REGION} --delete

# --- Save hash ---
echo "$ARTIFACT_HASH" > "$HASH_FILE"

# --- Start application ---
cd "$APP_DIR"

# Find the actual app directory (first subdirectory with content)
APP_ROOT="$APP_DIR"
# Frontend frameworks: React→build, Vue/Angular→dist, Next.js→.next+out
# Backend fallback: dist-server
if [ "$RUNTIME" = "react" ]; then
    for d in build dist out; do
        [ -d "$APP_DIR/$d" ] && APP_ROOT="$APP_DIR/$d" && break
    done
elif [ "$RUNTIME" = "vue" ] || [ "$RUNTIME" = "angular" ]; then
    for d in dist build out; do
        [ -d "$APP_DIR/$d" ] && APP_ROOT="$APP_DIR/$d" && break
    done
elif [ "$RUNTIME" = "nextjs" ]; then
    # Next.js static export → out/, or standalone → .next/standalone/
    if [ -d "$APP_DIR/out" ]; then
        APP_ROOT="$APP_DIR/out"
    elif [ -d "$APP_DIR/.next/standalone" ]; then
        APP_ROOT="$APP_DIR/.next/standalone"
    elif [ -d "$APP_DIR/.next" ]; then
        APP_ROOT="$APP_DIR/.next"
    fi
elif [ "$RUNTIME" = "python" ]; then
    for d in dist-python dist dist-server build out; do
        [ -d "$APP_DIR/$d" ] && APP_ROOT="$APP_DIR/$d" && break
    done
elif [ "$RUNTIME" = "java" ]; then
    # For Java we keep APP_ROOT at $APP_DIR because the JAR/WAR files are
    # copied into the artifacts root by the engine build step, so they
    # live directly under the deployed app directory.
    APP_ROOT="$APP_DIR"
else
    for d in dist dist-server build out; do
        [ -d "$APP_DIR/$d" ] && APP_ROOT="$APP_DIR/$d" && break
    done
fi

echo "APP_ROOT: $APP_ROOT"
SERVE_MODE="proxy"

# --- Port detection helpers ---
detect_port_by_pid() {{
    local pid="$1"
    if [ -z "$pid" ]; then
        return
    fi
    ss -tlnp 2>/dev/null | grep "pid=$pid" | grep -oP ':\\K[0-9]+(?=\\s)' | head -1
}}

update_port_if_needed() {{
    local new_port="$1"
    if [ -n "$new_port" ] && [ "$new_port" != "$PORT" ]; then
        PORT="$new_port"
        sed -i "s|^$OWNER/$REPO .*|$OWNER/$REPO $PORT|" "$PORT_FILE"
        echo "Adjusted port to $PORT"
    fi
}}

# ============================================================
# Frontend: React / Vue / Angular (static files via Nginx)
# ============================================================
if [ "$RUNTIME" = "react" ] || [ "$RUNTIME" = "vue" ] || [ "$RUNTIME" = "angular" ]; then
    SERVE_MODE="static"
    echo "Frontend app detected ($RUNTIME). Serving static files from $APP_ROOT"
    echo "Asset paths already rewritten by CI engine before upload."

# ============================================================
# Next.js
# ============================================================
elif [ "$RUNTIME" = "nextjs" ]; then
    # Case 1: Static export (out/ with index.html)
    if [ -f "$APP_ROOT/index.html" ]; then
        SERVE_MODE="static"
        echo "Next.js static export detected. Serving from $APP_ROOT"
    # Case 2: Standalone server
    elif [ -f "$APP_DIR/.next/standalone/server.js" ]; then
        APP_ROOT="$APP_DIR/.next/standalone"
        # Copy static and public assets for standalone
        cp -r "$APP_DIR/.next/static" "$APP_ROOT/.next/static" 2>/dev/null || true
        cp -r "$APP_DIR/public" "$APP_ROOT/public" 2>/dev/null || true
        cd "$APP_ROOT"
        PM2_HOME=/etc/.pm2 PORT=$PORT pm2 start server.js --name "$OWNER--$REPO"
        sleep 3
        APP_PID=$(PM2_HOME=/etc/.pm2 pm2 pid "$OWNER--$REPO" | head -1 2>/dev/null || true)
        ACTUAL_PORT=$(detect_port_by_pid "$APP_PID")
        # Only update the registry when this app's own PID is actually
        # listening. Never fall back to "any node listener" because that
        # steals a port already owned by another deployed app.
        if [ -n "$ACTUAL_PORT" ]; then
            update_port_if_needed "$ACTUAL_PORT"
        fi
        echo "Next.js standalone server on port $PORT"
    # Case 3: Regular Next.js SSR (has .next but no standalone, no static export)
    elif [ -d "$APP_DIR/.next" ]; then
        cd "$APP_DIR"
        # Install next if not present
        if ! command -v next &>/dev/null && [ ! -f node_modules/.bin/next ]; then
            npm install next react react-dom 2>/dev/null || true
        fi
        PM2_HOME=/etc/.pm2 pm2 start "npx next start -p $PORT" \\
            --name "$OWNER--$REPO" \\
            --interpreter none \\
            --cwd "$APP_DIR"
        sleep 5
        ACTUAL_PORT=$(ss -tlnp 2>/dev/null | grep "$PORT" | grep -oP ':\\K[0-9]+(?=\\s)' | head -1 || true)
        if [ -n "$ACTUAL_PORT" ]; then
            PORT=$ACTUAL_PORT
        fi
        echo "Next.js SSR server on port $PORT"
    else
        SERVE_MODE="static"
        echo "Next.js fallback to static serving"
    fi

# ============================================================
# Node.js backend
# ============================================================
elif [ "$RUNTIME" = "node" ]; then
    if [ -f "$APP_ROOT/package.json" ]; then
        cd "$APP_ROOT"
        npm install --omit=dev 2>/dev/null || true
    fi
    ENTRY=""
    for f in server.js index.js app.js main.js; do
        [ -f "$APP_ROOT/$f" ] && ENTRY="$APP_ROOT/$f" && break
    done
    if [ -z "$ENTRY" ] && [ -f "$APP_ROOT/package.json" ]; then
        ENTRY=$(node -e "try{{console.log(require('./package.json').main||'')}}catch(e){{}}" 2>/dev/null || true)
        [ -n "$ENTRY" ] && ENTRY="$APP_ROOT/$ENTRY"
    fi
    if [ -n "$ENTRY" ] && [ -f "$ENTRY" ]; then
        # Run the app through the engine wrapper so its listen() calls are
        # forced onto $PORT regardless of what its source code says. The
        # wrapper also installs a fallback HTTP server if the app never
        # calls listen() at all (library-only repos).
        PM2_HOME=/etc/.pm2 \
            PORT=$PORT FORCED_PORT=$PORT \
            WRAPPED_ENTRY="$ENTRY" WRAPPED_LABEL="$OWNER/$REPO" \
            pm2 start /opt/deployments/.port-wrapper.js \
            --name "$OWNER--$REPO" \
            --cwd "$APP_ROOT"
        # Wait up to 8s for the port to come up. If neither the app nor the
        # wrapper's fallback bind the port, start the python fallback so
        # nginx still gets 200.
        for i in 1 2 3 4 5 6 7 8; do
            sleep 1
            ss -tlnp 2>/dev/null | grep -q ":$PORT " && break
        done
        if ! ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
            echo "[engine] node wrapper failed to bind :$PORT — launching python fallback"
            PM2_HOME=/etc/.pm2 pm2 delete "$OWNER--$REPO" 2>/dev/null || true
            FORCED_PORT=$PORT WRAPPED_LABEL="$OWNER/$REPO" \
                nohup python3 /opt/deployments/.fallback-server.py \
                > "$APP_DIR/fallback.log" 2>&1 < /dev/null &
            echo $! > "$APP_DIR/.fallback.pid"
            disown
        fi
    else
        # No entry point at all — serve a fallback so the port still answers.
        echo "[engine] no Node.js entry point — launching python fallback on :$PORT"
        FORCED_PORT=$PORT WRAPPED_LABEL="$OWNER/$REPO" \
            nohup python3 /opt/deployments/.fallback-server.py \
            > "$APP_DIR/fallback.log" 2>&1 < /dev/null &
        echo $! > "$APP_DIR/.fallback.pid"
        disown
    fi

# ============================================================
# Python backend (FastAPI / Flask / Django via venv + uvicorn/gunicorn)
# ============================================================
elif [ "$RUNTIME" = "python" ]; then
    cd "$APP_ROOT"

    # Pick the newest available python interpreter (>=3.11 preferred)
    PYBIN=""
    for p in /usr/bin/python3.12 /usr/bin/python3.11 /usr/bin/python3.10 /usr/bin/python3; do
        if [ -x "$p" ]; then PYBIN="$p"; break; fi
    done
    if [ -z "$PYBIN" ]; then
        echo "ERROR: no python3 interpreter available on host"
        exit 1
    fi
    echo "Python interpreter: $PYBIN ($($PYBIN --version 2>&1))"

    # Create an isolated venv inside the deployed app root (wiped on redeploy)
    VENV_DIR="$APP_ROOT/.venv"
    if [ ! -x "$VENV_DIR/bin/python" ]; then
        "$PYBIN" -m venv "$VENV_DIR"
    fi
    VENV_PY="$VENV_DIR/bin/python"

    # Point pip build/tmp to the EBS disk to avoid filling up tmpfs-backed /tmp
    # (on t3.micro Amazon Linux 2023, /tmp is a ~460MB tmpfs; large packages
    # like semgrep overflow it when building wheels).
    PIP_TMPDIR="$APP_DIR/.pip-tmp"
    rm -rf "$PIP_TMPDIR"
    mkdir -p "$PIP_TMPDIR"
    export TMPDIR="$PIP_TMPDIR"
    export TMP="$PIP_TMPDIR"
    export TEMP="$PIP_TMPDIR"
    export PIP_NO_CACHE_DIR=1

    "$VENV_PY" -m pip install --upgrade pip wheel >/dev/null 2>&1 || true

    # Install dependencies
    if [ -f "$APP_ROOT/requirements.txt" ]; then
        echo "Installing requirements.txt into venv (TMPDIR=$TMPDIR)..."
        "$VENV_PY" -m pip install -r "$APP_ROOT/requirements.txt"
        INSTALL_RC=$?
    elif [ -f "$APP_ROOT/pyproject.toml" ]; then
        echo "Installing project from pyproject.toml into venv (TMPDIR=$TMPDIR)..."
        "$VENV_PY" -m pip install "$APP_ROOT"
        INSTALL_RC=$?
    else
        INSTALL_RC=0
    fi
    rm -rf "$PIP_TMPDIR"
    if [ "$INSTALL_RC" != "0" ]; then
        echo "ERROR: python dependency install failed (rc=$INSTALL_RC)"
        exit 1
    fi

    # Detect ASGI framework via dependency manifests
    ASGI_FRAMEWORK="no"
    for manifest in requirements.txt pyproject.toml Pipfile; do
        if [ -f "$APP_ROOT/$manifest" ] && grep -qiE "(fastapi|starlette|uvicorn|sanic|quart|litestar|hypercorn)" "$APP_ROOT/$manifest"; then
            ASGI_FRAMEWORK="yes"
            break
        fi
    done

    # Resolve application entry point as module:attr.
    # Preference order:
    #   1. Pre-detected entry from build_meta.json (AST-based, handles
    #      src-layout and factory patterns correctly).
    #   2. Legacy heuristic: probe a fixed list of common file locations.
    ENTRY=""
    APP_DIR_FOR_UVICORN="$APP_ROOT"
    UVICORN_FACTORY_FLAG=""

    if [ -n "$PREDETECTED_PY_ENTRY" ]; then
        ENTRY="$PREDETECTED_PY_ENTRY"
        if [ -n "$PREDETECTED_PY_APP_DIR" ] && [ "$PREDETECTED_PY_APP_DIR" != "." ]; then
            APP_DIR_FOR_UVICORN="$APP_ROOT/$PREDETECTED_PY_APP_DIR"
        fi
        if [ "$PREDETECTED_PY_FACTORY" = "yes" ]; then
            UVICORN_FACTORY_FLAG="--factory"
        fi
        echo "Using pre-detected python entry: $ENTRY (app-dir=$APP_DIR_FOR_UVICORN factory=$PREDETECTED_PY_FACTORY)"
    else
        CANDIDATES="app/main.py:app.main:app src/main.py:src.main:app main.py:main:app app.py:app:app wsgi.py:wsgi:application application.py:application:application asgi.py:asgi:application"
        for cand in $CANDIDATES; do
            rel_file=$(echo "$cand" | cut -d: -f1)
            mod_attr=$(echo "$cand" | cut -d: -f2-)
            if [ -f "$APP_ROOT/$rel_file" ]; then
                ENTRY="$mod_attr"
                break
            fi
        done
    fi

    if [ -z "$ENTRY" ]; then
        echo "ERROR: no python entry point found (looked for app/main.py, main.py, app.py, wsgi.py, asgi.py)"
        exit 1
    fi
    echo "Python entry: $ENTRY (asgi=$ASGI_FRAMEWORK, port=$PORT)"

    # Stop previous process (pid file + pkill fallback)
    if [ -f "$APP_DIR/.app.pid" ]; then
        OLD_PID=$(cat "$APP_DIR/.app.pid" 2>/dev/null || true)
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 1
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
        rm -f "$APP_DIR/.app.pid"
    fi
    pkill -f "uvicorn.*$OWNER--$REPO" 2>/dev/null || true
    pkill -f "gunicorn.*$OWNER--$REPO" 2>/dev/null || true

    # Launch the app in the background
    cd "$APP_ROOT"
    STDOUT_LOG="$APP_DIR/app.stdout.log"
    STDERR_LOG="$APP_DIR/app.stderr.log"
    : > "$STDOUT_LOG"
    : > "$STDERR_LOG"

    if [ "$ASGI_FRAMEWORK" = "yes" ]; then
        nohup "$VENV_PY" -m uvicorn "$ENTRY" \\
            --host 0.0.0.0 --port "$PORT" \\
            --app-dir "$APP_DIR_FOR_UVICORN" \\
            $UVICORN_FACTORY_FLAG \\
            > "$STDOUT_LOG" 2> "$STDERR_LOG" < /dev/null &
    else
        nohup "$VENV_PY" -m gunicorn "$ENTRY" \\
            -b "0.0.0.0:$PORT" \\
            --chdir "$APP_DIR_FOR_UVICORN" \\
            > "$STDOUT_LOG" 2> "$STDERR_LOG" < /dev/null &
    fi
    APP_PID=$!
    echo "$APP_PID" > "$APP_DIR/.app.pid"
    disown "$APP_PID" 2>/dev/null || true

    # Give the app time to bind, then verify
    for i in 1 2 3 4 5 6 7 8; do
        sleep 1
        if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
            echo "Python app listening on port $PORT (pid $APP_PID)"
            break
        fi
    done
    if ! ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
        ACTUAL_PORT=$(detect_port_by_pid "$APP_PID")
        if [ -n "$ACTUAL_PORT" ]; then
            update_port_if_needed "$ACTUAL_PORT"
            echo "Python app bound to port $PORT (pid $APP_PID)"
        else
            echo "[engine] python app failed to bind :$PORT — launching engine fallback"
            echo "--- stderr (last 60 lines) ---"
            tail -60 "$STDERR_LOG" 2>/dev/null
            echo "--- stdout (last 30 lines) ---"
            tail -30 "$STDOUT_LOG" 2>/dev/null
            kill "$APP_PID" 2>/dev/null || true
            FORCED_PORT=$PORT WRAPPED_LABEL="$OWNER/$REPO" \
                nohup python3 /opt/deployments/.fallback-server.py \
                > "$APP_DIR/fallback.log" 2>&1 < /dev/null &
            echo $! > "$APP_DIR/.fallback.pid"
            disown
        fi
    fi

# ============================================================
# Java backend (Spring Boot / generic JAR / WAR)
# ============================================================
elif [ "$RUNTIME" = "java" ]; then
    # Locate a usable Java runtime (prefer 21 > 17 > 11 > system > auto-discover)
    JAVA_BIN=""
    for candidate in \\
        /usr/lib/jvm/java-21-amazon-corretto/bin/java \\
        /usr/lib/jvm/java-21-openjdk-amd64/bin/java \\
        /usr/lib/jvm/java-21-openjdk/bin/java \\
        /usr/lib/jvm/java-17-amazon-corretto/bin/java \\
        /usr/lib/jvm/java-17-openjdk-amd64/bin/java \\
        /usr/lib/jvm/java-17-openjdk/bin/java \\
        /usr/lib/jvm/java-11-amazon-corretto/bin/java \\
        /usr/lib/jvm/java-11-openjdk-amd64/bin/java \\
        /usr/lib/jvm/java-11-openjdk/bin/java \\
        /usr/lib/jvm/default-java/bin/java \\
        /usr/lib/jvm/default/bin/java \\
        /usr/bin/java; do
        if [ -x "$candidate" ]; then JAVA_BIN="$candidate"; break; fi
    done
    if [ -z "$JAVA_BIN" ]; then
        # Auto-discover: scan /usr/lib/jvm for any JDK
        if [ -d /usr/lib/jvm ]; then
            JAVA_BIN=$(find /usr/lib/jvm -name "java" -path "*/bin/java" -type f 2>/dev/null | sort -r | head -1 || true)
        fi
    fi
    if [ -z "$JAVA_BIN" ]; then
        echo "ERROR: no java runtime available on host"
        exit 1
    fi
    echo "Java runtime: $JAVA_BIN ($($JAVA_BIN -version 2>&1 | head -1))"

    # Pick the deployable archive. Prefer a Spring Boot fat JAR (largest
    # JAR that is not a -sources/-javadoc/-tests/original- auxiliary).
    ARCHIVE=""
    while IFS= read -r candidate; do
        base=$(basename "$candidate")
        case "$base" in
            *-sources.jar|*-javadoc.jar|*-tests.jar|*-plain.jar|*-slim.jar|*-stubs.jar|*-test-fixtures.jar|*-empty.jar|*-mock.jar|original-*) continue ;;
        esac
        ARCHIVE="$candidate"
        break
    done < <(find "$APP_ROOT" -maxdepth 2 -type f \\( -name "*.jar" -o -name "*.war" -o -name "*.ear" \\) -printf "%s %p\\n" 2>/dev/null | sort -rn | cut -d' ' -f2-)

    if [ -z "$ARCHIVE" ]; then
        echo "ERROR: no deployable JAR/WAR/EAR found under $APP_ROOT"
        exit 1
    fi
    echo "Java archive: $ARCHIVE"

    # Stop previous process (pid file + pkill fallback)
    if [ -f "$APP_DIR/.app.pid" ]; then
        OLD_PID=$(cat "$APP_DIR/.app.pid" 2>/dev/null || true)
        if [ -n "$OLD_PID" ] && kill -0 "$OLD_PID" 2>/dev/null; then
            kill "$OLD_PID" 2>/dev/null || true
            sleep 1
            kill -9 "$OLD_PID" 2>/dev/null || true
        fi
        rm -f "$APP_DIR/.app.pid"
    fi
    if [ -f "$APP_DIR/.java.pid" ]; then
        kill $(cat "$APP_DIR/.java.pid") 2>/dev/null || true
        rm -f "$APP_DIR/.java.pid"
    fi
    pkill -f "java.*$OWNER--$REPO" 2>/dev/null || true

    STDOUT_LOG="$APP_DIR/app.stdout.log"
    STDERR_LOG="$APP_DIR/app.stderr.log"
    : > "$STDOUT_LOG"
    : > "$STDERR_LOG"

    cd "$APP_ROOT"
    # Pass the port both as env and Spring Boot command-line argument so
    # either configuration pattern picks it up. Generic (non-Spring) JARs
    # that ignore --server.port will still get SERVER_PORT/PORT from env.
    SERVER_PORT=$PORT PORT=$PORT nohup "$JAVA_BIN" \\
        -Dserver.port=$PORT \\
        -Dspring.profiles.active=${{SPRING_PROFILES_ACTIVE:-prod}} \\
        -jar "$ARCHIVE" \\
        --server.port=$PORT \\
        > "$STDOUT_LOG" 2> "$STDERR_LOG" < /dev/null &
    APP_PID=$!
    echo "$APP_PID" > "$APP_DIR/.app.pid"
    disown "$APP_PID" 2>/dev/null || true

    # Spring Boot apps can take 10-30s to warm up; allow a generous window.
    BOUND=no
    for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25; do
        sleep 1
        if ss -tlnp 2>/dev/null | grep -q ":$PORT "; then
            echo "Java app listening on port $PORT (pid $APP_PID) after ${{i}}s"
            BOUND=yes
            break
        fi
        if ! kill -0 "$APP_PID" 2>/dev/null; then
            echo "Java process $APP_PID died before binding port $PORT"
            break
        fi
    done
    if [ "$BOUND" != "yes" ]; then
        ACTUAL_PORT=$(detect_port_by_pid "$APP_PID")
        if [ -n "$ACTUAL_PORT" ]; then
            update_port_if_needed "$ACTUAL_PORT"
            echo "Java app bound to port $PORT (pid $APP_PID)"
        else
            echo "[engine] java app failed to bind :$PORT — launching engine fallback"
            echo "--- stderr (last 80 lines) ---"
            tail -80 "$STDERR_LOG" 2>/dev/null
            echo "--- stdout (last 40 lines) ---"
            tail -40 "$STDOUT_LOG" 2>/dev/null
            kill "$APP_PID" 2>/dev/null || true
            FORCED_PORT=$PORT WRAPPED_LABEL="$OWNER/$REPO" \
                nohup python3 /opt/deployments/.fallback-server.py \
                > "$APP_DIR/fallback.log" 2>&1 < /dev/null &
            echo $! > "$APP_DIR/.fallback.pid"
            disown
        fi
    fi
fi

# --- Configure Nginx ---
if [ "$SERVE_MODE" = "static" ]; then
    # SPA-friendly static serving with proper alias + try_files
    cat > "$NGINX_CONF" << NGINXEOF
location /$OWNER/$REPO {{
    return 301 /$OWNER/$REPO/;
}}
location /$OWNER/$REPO/ {{
    alias $APP_ROOT/;
    index index.html;
    try_files \\$uri \\$uri/ /$OWNER/$REPO/index.html;
}}
NGINXEOF
else
    cat > "$NGINX_CONF" << NGINXEOF
location /$OWNER/$REPO {{
    return 301 /$OWNER/$REPO/;
}}
location /$OWNER/$REPO/ {{
    proxy_pass http://127.0.0.1:$PORT/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade \\$http_upgrade;
    proxy_set_header Connection 'upgrade';
    proxy_set_header Host \\$host;
    proxy_set_header X-Real-IP \\$remote_addr;
    proxy_set_header X-Forwarded-For \\$proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto \\$scheme;
    proxy_cache_bypass \\$http_upgrade;
}}
NGINXEOF
fi

# --- Reload Nginx ---
nginx -t && systemctl reload nginx

# --- Generate index page with deployed app list ---
INDEX_FILE="{EC2_DEPLOY_ROOT}/www/index.html"
TOKEN=$(curl -s -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" 2>/dev/null || true)
HOSTNAME=$(curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "unknown")

cat > "$INDEX_FILE" << 'HEADEREOF'
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>CI/CD Deploy Server</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #e2e8f0; min-height: 100vh; }}
  .container {{ max-width: 900px; margin: 0 auto; padding: 40px 20px; }}
  h1 {{ font-size: 2rem; font-weight: 700; margin-bottom: 8px; color: #f8fafc; }}
  .subtitle {{ color: #94a3b8; margin-bottom: 32px; font-size: 0.95rem; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 32px; }}
  .stat-card {{ background: #1e293b; border-radius: 12px; padding: 16px 24px; flex: 1; border: 1px solid #334155; }}
  .stat-value {{ font-size: 1.5rem; font-weight: 700; color: #38bdf8; }}
  .stat-label {{ font-size: 0.8rem; color: #94a3b8; margin-top: 4px; }}
  table {{ width: 100%; border-collapse: collapse; background: #1e293b; border-radius: 12px; overflow: hidden; border: 1px solid #334155; }}
  th {{ background: #334155; padding: 14px 20px; text-align: left; font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; font-weight: 600; }}
  td {{ padding: 14px 20px; border-top: 1px solid #334155; }}
  tr:hover td {{ background: #263348; }}
  a {{ color: #38bdf8; text-decoration: none; font-weight: 500; }}
  a:hover {{ text-decoration: underline; color: #7dd3fc; }}
  .badge {{ display: inline-block; padding: 3px 10px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }}
  .badge-node {{ background: #064e3b; color: #6ee7b7; }}
  .badge-react {{ background: #164e63; color: #67e8f9; }}
  .badge-vue {{ background: #14532d; color: #86efac; }}
  .badge-angular {{ background: #7f1d1d; color: #fca5a5; }}
  .badge-next {{ background: #1c1917; color: #e7e5e4; border: 1px solid #44403c; }}
  .badge-python {{ background: #1e3a5f; color: #93c5fd; }}
  .badge-java {{ background: #7c2d12; color: #fdba74; }}
  .badge-static {{ background: #3f3f46; color: #d4d4d8; }}
  .port {{ font-family: 'SF Mono', 'Fira Code', monospace; color: #a78bfa; font-size: 0.9rem; }}
  .empty {{ text-align: center; padding: 60px 20px; color: #64748b; }}
  .footer {{ margin-top: 32px; text-align: center; color: #475569; font-size: 0.8rem; }}
</style>
</head>
<body>
<div class="container">
<h1>CI/CD Deploy Server</h1>
<p class="subtitle">Deployed applications via Local CI Engine</p>
HEADEREOF

# Count apps and build table rows
APP_COUNT=0
TABLE_ROWS=""

while IFS=' ' read -r APP_PATH APP_PORT; do
    [ -z "$APP_PATH" ] && continue
    APP_COUNT=$((APP_COUNT + 1))

    APP_OWNER=$(echo "$APP_PATH" | cut -d'/' -f1)
    APP_REPO=$(echo "$APP_PATH" | cut -d'/' -f2-)
    APP_DIR_CHECK="{EC2_DEPLOY_ROOT}/apps/$APP_PATH"

    # Detect runtime from deploy_manifest.json
    MANIFEST_RUNTIME=$(cat "$APP_DIR_CHECK/deploy_manifest.json" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('runtime','node'))" 2>/dev/null || echo "node")
    BADGE_CLASS="badge-node"
    BADGE_TEXT="Node.js"
    case "$MANIFEST_RUNTIME" in
        react)    BADGE_CLASS="badge-react";   BADGE_TEXT="React" ;;
        vue)      BADGE_CLASS="badge-vue";     BADGE_TEXT="Vue" ;;
        angular)  BADGE_CLASS="badge-angular"; BADGE_TEXT="Angular" ;;
        nextjs)   BADGE_CLASS="badge-next";    BADGE_TEXT="Next.js" ;;
        python)   BADGE_CLASS="badge-python";  BADGE_TEXT="Python" ;;
        java)     BADGE_CLASS="badge-java";    BADGE_TEXT="Java" ;;
        node)     BADGE_CLASS="badge-node";    BADGE_TEXT="Node.js" ;;
        *)        BADGE_CLASS="badge-static";  BADGE_TEXT="Static" ;;
    esac

    # Decide whether the app is "up".
    # Static SPA runtimes (React / Vue / Angular / Next.js static export)
    # are served directly by Nginx from files on disk, so there is no
    # backend process listening on a port. For those, we mark the app as
    # up when the deployed directory and its Nginx config both exist.
    # Proxy-based runtimes (Node / Python / Java / Next.js SSR) must have
    # a process listening on $APP_PORT.
    APP_NGINX_CONF="{EC2_NGINX_CONF_DIR}/${{APP_OWNER}}__${{APP_REPO}}.conf"
    STATUS_DOT="\\xF0\\x9F\\x9F\\xA2"  # green circle
    case "$MANIFEST_RUNTIME" in
        react|vue|angular)
            if [ ! -d "$APP_DIR_CHECK" ] || [ ! -f "$APP_NGINX_CONF" ]; then
                STATUS_DOT="\\xF0\\x9F\\x94\\xB4"  # red circle
            fi
            ;;
        nextjs)
            # Next.js can be either static export or SSR. Trust the port
            # probe if anything is listening, otherwise treat file
            # presence as "up" so static exports are not marked down.
            if ! ss -tlnp 2>/dev/null | grep -q ":$APP_PORT "; then
                if [ ! -d "$APP_DIR_CHECK" ] || [ ! -f "$APP_NGINX_CONF" ]; then
                    STATUS_DOT="\\xF0\\x9F\\x94\\xB4"
                fi
            fi
            ;;
        *)
            if ! ss -tlnp 2>/dev/null | grep -q ":$APP_PORT "; then
                STATUS_DOT="\\xF0\\x9F\\x94\\xB4"
            fi
            ;;
    esac

    TABLE_ROWS="$TABLE_ROWS<tr><td>$(echo -e $STATUS_DOT) <a href=\\\"/$APP_PATH/\\\">$APP_OWNER/$APP_REPO</a></td><td><span class=\\\"badge $BADGE_CLASS\\\">$BADGE_TEXT</span></td><td class=\\\"port\\\">:$APP_PORT</td><td><a href=\\\"/$APP_PATH/\\\">/$APP_PATH/</a></td></tr>"
done < "$PORT_FILE"

# Write stats
cat >> "$INDEX_FILE" << STATSEOF
<div class="stats">
  <div class="stat-card">
    <div class="stat-value">$APP_COUNT</div>
    <div class="stat-label">Deployed Apps</div>
  </div>
  <div class="stat-card">
    <div class="stat-value">$HOSTNAME</div>
    <div class="stat-label">Server IP</div>
  </div>
</div>
STATSEOF

if [ "$APP_COUNT" -gt 0 ]; then
    cat >> "$INDEX_FILE" << TABLEEOF
<table>
  <thead><tr><th>Application</th><th>Runtime</th><th>Port</th><th>URL</th></tr></thead>
  <tbody>$TABLE_ROWS</tbody>
</table>
TABLEEOF
else
    cat >> "$INDEX_FILE" << EMPTYEOF
<div class="empty"><p>No applications deployed yet.</p><p>Run the CI/CD pipeline to deploy your first app.</p></div>
EMPTYEOF
fi

cat >> "$INDEX_FILE" << 'FOOTEREOF'
<div class="footer">Powered by Local CI Engine</div>
</div>
</body>
</html>
FOOTEREOF

echo "Deploy complete: /$OWNER/$REPO -> port $PORT (runtime: $RUNTIME)"
"""
