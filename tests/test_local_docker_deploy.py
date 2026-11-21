from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.steps.local_docker_deploy import (
    _app_compose_service,
    _container_name,
    _port_range_from_env,
    _prepare_runtime_context,
    _replace_container,
    _router_default_config,
    _router_service_config,
    _select_port,
)
from app.utils.shell import CommandResult


def test_port_selection_is_stable_and_avoids_reserved_port() -> None:
    service = "example/api"
    first = _select_port(service, 10000, 10010, set())

    assert _select_port(service, 10000, 10010, set()) == first
    assert _select_port(service, 10000, 10010, {first}) != first


def test_port_range_rejects_invalid_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEPLOY_PORT_START", "20000")
    monkeypatch.setenv("DEPLOY_PORT_END", "10000")

    with pytest.raises(ValueError, match="deployment port range"):
        _port_range_from_env()


def test_container_name_is_docker_safe_and_service_specific() -> None:
    first = _container_name("My Org", "Frontend@Service", "my org/frontend@service")
    second = _container_name("My Org", "Backend@Service", "my org/backend@service")

    assert first.startswith("cicd-app-my-org-frontend-service-")
    assert first != second
    assert len(first) <= 63


def test_app_compose_service_only_publishes_on_loopback() -> None:
    service = _app_compose_service(
        container_name="cicd-app-example",
        image_name="cicd-managed/example:123",
        service_key="example/api",
        owner="example",
        repo_name="api",
        runtime="node",
        artifact_hash="123",
        bind_address="127.0.0.1",
        host_port=12000,
        container_port=3000,
    )

    assert service["ports"] == ["127.0.0.1:12000:3000"]


def test_router_preserves_proxy_metadata_and_websocket_upgrade() -> None:
    default_config = _router_default_config()
    route = _router_service_config(
        "/services/Example/API", "cicd-app-example", 3000, "example/api", runtime="node"
    )

    assert "map $http_upgrade $cicd_connection_upgrade" in default_config
    assert "proxy_set_header Connection $cicd_connection_upgrade" in route
    assert "proxy_set_header Host $http_host" in route
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for" in route
    assert "proxy_set_header X-Forwarded-Proto $cicd_forwarded_proto" in route


def test_python_router_root_opens_api_docs() -> None:
    route = _router_service_config(
        "/services/Example/API", "cicd-app-example", 8000, "example/api", runtime="python"
    )

    assert "location = /services/Example/API/ { return 302 /services/Example/API/docs; }" in route


def test_backend_router_route_forwards_websocket_upgrade() -> None:
    route_path = Path(__file__).resolve().parents[1] / "deployments/router/routes/capstone-back.conf"
    route = route_path.read_text(encoding="utf-8")

    assert "location ^~ /api/" in route
    assert "proxy_http_version 1.1;" in route
    assert "proxy_set_header Upgrade $http_upgrade;" in route
    assert "proxy_set_header Connection $cicd_connection_upgrade;" in route
    assert "proxy_read_timeout 3600s;" in route


def test_prepare_node_context_uses_fallback_artifact(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    fallback = artifacts / "dist-server"
    fallback.mkdir(parents=True)
    (fallback / "package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8"
    )
    (fallback / "server.js").write_text("require('http').createServer().listen(3000)\n", encoding="utf-8")
    (artifacts / "build_meta.json").write_text(
        json.dumps({"fallback_directory": "dist-server"}), encoding="utf-8"
    )

    spec = _prepare_runtime_context(
        repo_dir=tmp_path / "repo",
        artifacts_dir=artifacts,
        context_dir=tmp_path / "context",
        runtime="node",
        python_entry=None,
        public_path="/services/example/api",
    )

    assert spec.container_port == 3000
    assert (spec.context_dir / "app/server.js").is_file()
    dockerfile = (spec.context_dir / "Dockerfile").read_text(encoding="utf-8")
    assert 'CMD ["npm", "start"]' in dockerfile


def test_prepare_frontend_context_adds_spa_fallback(tmp_path: Path) -> None:
    artifacts = tmp_path / "artifacts"
    output = artifacts / "dist"
    output.mkdir(parents=True)
    (output / "index.html").write_text(
        '<script src="/assets/app.js"></script><main>ok</main>', encoding="utf-8"
    )

    (output / "assets").mkdir()
    (output / "assets/app.js").write_text("console.log(1)")
    spec = _prepare_runtime_context(
        repo_dir=tmp_path / "repo",
        artifacts_dir=artifacts,
        context_dir=tmp_path / "context",
        runtime="react",
        python_entry=None,
        public_path="/services/example/web",
    )

    assert spec.container_port == 80
    index_html = (spec.context_dir / "app/index.html").read_text(encoding="utf-8")
    assert 'src="/services/example/web/assets/app.js"' in index_html
    nginx_config = (spec.context_dir / "default.conf").read_text(encoding="utf-8")
    assert "try_files $uri /index.html" in nginx_config


def test_failed_docker_run_does_not_remove_name_collision(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    commands: list[list[str]] = []

    def fake_docker(args: list[str], **_kwargs) -> CommandResult:
        commands.append(args)
        return CommandResult(exit_code=1, output="name is already in use")

    monkeypatch.setattr("app.steps.local_docker_deploy._docker", fake_docker)

    deployed = _replace_container(
        current_container="",
        container_name="cicd-app-example",
        image_name="cicd-managed/example:123",
        service_key="example/api",
        owner="example",
        repo_name="api",
        runtime="node",
        artifact_hash="123",
        bind_address="0.0.0.0",
        host_port=12000,
        container_port=3000,
        network="capstone-internal",
        health_host="127.0.0.1",
        cwd=tmp_path,
        log_file=tmp_path / "deploy.log",
    )

    assert deployed is False
    assert commands[0][0] == "run"
    assert not any(command[:2] == ["rm", "-f"] for command in commands)


def test_compose_healthcheck_uses_sibling_container_network(monkeypatch):
    from app.steps.local_docker_deploy import _compose_probe_address
    monkeypatch.setattr(Path, 'exists', lambda self: str(self)=='/.dockerenv')
    assert _compose_probe_address('app-container',8080,13539)==('app-container',8080)
    monkeypatch.setattr(Path, 'exists', lambda self:False)
    assert _compose_probe_address('app-container',8080,13539)==('127.0.0.1',13539)


def test_missing_compose_fails_before_deployment_mutation(monkeypatch,tmp_path):
    from app.steps import local_docker_deploy as d
    monkeypatch.setattr(d,'_docker',lambda *a,**k:CommandResult(exit_code=1,output='missing plugin'))
    monkeypatch.setattr(d,'_state_dir',lambda *a:pytest.fail('must not mutate deployment'))
    with pytest.raises(OSError,match='Compose plugin'):
        d._compose_replace_service(current_container='',container_name='app',image_name='image',
            service_key='a/b',owner='a',repo_name='b',runtime='java',artifact_hash='a',bind_address='127.0.0.1',
            host_port=13539,container_port=8080,network='capstone-internal',public_path='/a/b',cwd=tmp_path,log_file=tmp_path/'log')


def test_router_state_migration_copies_existing_api_and_app_routes(monkeypatch,tmp_path):
    from app.steps import local_docker_deploy as d
    calls=[]
    def docker(args,**kwargs):
        calls.append(args)
        return CommandResult(0,'/previous/router/routes' if args[0]=='inspect' else '')
    monkeypatch.setattr(d,'_docker',docker)
    d._preserve_router_routes(tmp_path,cwd=tmp_path,log_file=tmp_path/'log')
    assert calls[1]==['cp','capstone-deploy-router:/etc/nginx/routes/.',str(tmp_path)]


def test_router_existing_mount_is_not_copied_onto_itself(monkeypatch,tmp_path):
    from app.steps import local_docker_deploy as d
    calls=[]
    def docker(args,**kwargs):calls.append(args);return CommandResult(0,str(tmp_path))
    monkeypatch.setattr(d,'_docker',docker)
    d._preserve_router_routes(tmp_path,cwd=tmp_path,log_file=tmp_path/'log')
    assert len(calls)==1


def test_router_copy_failure_prevents_route_replacement(monkeypatch,tmp_path):
    from app.steps import local_docker_deploy as d
    monkeypatch.setattr(d,'_docker',lambda args,**kwargs:CommandResult(0,'/previous') if args[0]=='inspect' else CommandResult(1,'copy error'))
    with pytest.raises(OSError,match='preserve'):
        d._preserve_router_routes(tmp_path,cwd=tmp_path,log_file=tmp_path/'log')


def test_custom_assets_rewritten_without_changing_routes(tmp_path):
    from app.steps.local_docker_deploy import _rewrite_static_paths
    (tmp_path / 'logo.svg').write_text('<svg/>')
    script = tmp_path / 'app.js'
    script.write_text('const a=`/logo.svg`;const route="/projects/";const external="//cdn/logo.svg"')
    _rewrite_static_paths(tmp_path, '/services/a/b')
    expected = 'const a=`/services/a/b/logo.svg`;const route="/projects/";const external="//cdn/logo.svg"'
    assert script.read_text() == expected
    _rewrite_static_paths(tmp_path, '/services/a/b')
    assert script.read_text() == expected


def test_http_readiness_rejects_html_in_place_of_javascript(monkeypatch, tmp_path):
    from app.steps import local_docker_deploy as d
    from io import BytesIO
    def response(url, **kwargs):
        result = BytesIO(b'<script src="/app.js"></script>')
        result.status = 200
        result.headers = {'Content-Type': 'text/html'}
        return result
    monkeypatch.setattr(d, 'urlopen', response)
    clock = iter([0, 0, 2])
    monkeypatch.setattr(d.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(d.time, 'sleep', lambda _: None)
    assert not d._wait_for_static_http('http://app/', tmp_path/'log', 1)


def test_api_router_root_falls_back_to_landing_page_only_on_404() -> None:
    route = _router_service_config(
        "/services/printwd/sample_java1",
        "cicd-app-printwd-sample_java1-80504368",
        8080,
        "printwd/sample_java1",
        runtime="java",
    )
    fallback = "@cicd_root_cicd_app_printwd_sample_java1_80504368"

    assert "location = /services/printwd/sample_java1/ {\n" in route
    assert "  rewrite ^ / break;\n" in route
    assert "  proxy_intercept_errors on;\n" in route
    assert f"  error_page 404 = {fallback};\n" in route
    assert f"location {fallback} {{\n" in route
    # Non-browser clients and non-GET methods keep a real 404.
    assert 'if ($cicd_root_client !~* "^(GET|HEAD):.*text/html") { return 404; }' in route
    # Every other path still goes to the app untouched.
    assert "rewrite ^/services/printwd/sample_java1/(.*)$ /$1 break;" in route
    assert route.count("proxy_intercept_errors") == 1


def test_root_fallback_page_is_safe_inside_nginx_string() -> None:
    from app.steps.local_docker_deploy import _root_fallback_page

    page = _root_fallback_page("/services/Ex'am$ple/A\\PI")

    assert "'" not in page and "$" not in page and "\\" not in page
    assert "Example/API" in page


@pytest.mark.parametrize("runtime", ["python", "react", "vue", "angular", None])
def test_root_fallback_is_limited_to_server_runtimes(runtime) -> None:
    route = _router_service_config(
        "/services/Example/App", "cicd-app-example", 80, "example/app", runtime=runtime
    )

    assert "proxy_intercept_errors" not in route
    assert "@cicd_root_" not in route


@pytest.mark.parametrize("status", [200, 302, 404])
def test_probe_root_status_reports_app_status_without_following_redirects(
    status, tmp_path: Path
) -> None:
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    from app.steps.local_docker_deploy import _probe_root_status

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(status)
            if status == 302:
                self.send_header("Location", "/elsewhere")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        assert _probe_root_status("127.0.0.1", server.server_port, tmp_path / "deploy.log") == status
    finally:
        server.shutdown()
        server.server_close()


def test_probe_root_status_is_none_when_unreachable(tmp_path: Path) -> None:
    from app.steps.local_docker_deploy import _probe_root_status

    assert _probe_root_status("127.0.0.1", 1, tmp_path / "deploy.log", attempts=1) is None
