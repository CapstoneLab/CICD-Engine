import json
from types import SimpleNamespace

import pytest
from app.steps import lightweight_security as light, deep_security as deep
from app.security_workflow import validate_security_workflow
from app.workflow import WorkflowStepDefinition as Step, WorkflowDefinition
from app.models import StepRunResult
from app.orchestrator import LocalOrchestrator
from app import orchestrator as module, poller


def scans():
    return [Step("secret", "builtin", "lightweight_security_scan", continue_on_failure=True),
            Step("deep", "builtin", "deep_security_scan"), Step("deploy", "builtin", "deploy")]


@pytest.mark.parametrize("name,contents", [("light", None), ("light", "broken"), ("light", "{}"),
    ("deep", None), ("deep", "broken"), ("deep", "{}"),
    ("deep", '{"results":[],"errors":[{"message":"timeout"}]}')])
def test_invalid_report_fails_scan(monkeypatch, tmp_path, name, contents):
    scanner = light if name == "light" else deep
    report = tmp_path / "report.json"
    report.write_text('[]' if name == "light" else '{"results":[]}')  # stale success must be deleted
    monkeypatch.setattr(scanner, "resolve_executable", lambda _: "mock")
    def run(**kwargs):
        assert not report.exists()
        if contents is not None:
            report.write_text(contents)
        return SimpleNamespace(exit_code=0, output="")
    monkeypatch.setattr(scanner, "run_command", run)
    fn = light.run_lightweight_security_scan if name == "light" else deep.run_deep_security_scan
    result = fn(tmp_path, tmp_path / "scan.log", report)
    assert result.status == "failed"


@pytest.mark.parametrize("scanner", [light, deep])
def test_valid_empty_report_passes(monkeypatch, tmp_path, scanner):
    report = tmp_path / "report.json"
    monkeypatch.setattr(scanner, "resolve_executable", lambda _: "mock")
    def run(**kwargs):
        report.write_text('[]' if scanner is light else '{"results":[],"errors":[],"paths":{"scanned":["app.py"]}}')
        return SimpleNamespace(exit_code=0, output="")
    monkeypatch.setattr(scanner, "run_command", run)
    fn = light.run_lightweight_security_scan if scanner is light else deep.run_deep_security_scan
    assert fn(tmp_path, tmp_path / "scan.log", report).status == "success"


@pytest.mark.parametrize("steps", [[Step("deploy", "builtin", "deploy")], list(reversed(scans())),
    [scans()[0], scans()[2], scans()[1]], scans() + [scans()[1]]])
def test_unsafe_workflow_is_rejected(steps):
    with pytest.raises(ValueError):
        validate_security_workflow(steps)


def test_security_gate_precedes_deploy_and_scanner_failure_cannot_continue(monkeypatch, tmp_path):
    seen = []
    obj = LocalOrchestrator(tmp_path, source="mirae")
    monkeypatch.setattr(obj, "_check_required_env", lambda *a: None)
    monkeypatch.setattr(module, "resolve_workflow_definition", lambda **k: WorkflowDefinition("test", "node", scans(), "test"))
    def execute(**kwargs):
        name = kwargs["step_name"]
        seen.append(name)
        return StepRunResult(status="failed" if name == "secret" else "success", exit_code=1 if name == "secret" else 0, summary_message="test")
    monkeypatch.setattr(obj, "_execute_step", execute)
    result, _ = obj.run("https://github.com/example/repo", "main")
    assert result.status == "failed"
    assert seen == ["clone", "secret"]


def test_clean_pipeline_runs_gate_before_deploy(monkeypatch, tmp_path):
    obj = LocalOrchestrator(tmp_path)
    monkeypatch.setattr(obj, "_check_required_env", lambda *a: None)
    monkeypatch.setattr(module, "resolve_workflow_definition", lambda **k: WorkflowDefinition("test", "node", scans(), "test"))
    def execute(**kwargs):
        if kwargs["step_name"] == "deploy":
            assert obj._security_verdict is not None
            assert obj._security_verdict.verdict == "pass"
        return StepRunResult(status="success", exit_code=0, summary_message="test")
    monkeypatch.setattr(obj, "_execute_step", execute)
    result, _ = obj.run("https://github.com/example/repo", "main")
    assert result.status == "success"
    assert next(s for s in result.steps if s.step_name == "security_gate").status == "success"


def test_poller_refuses_invalid_environment(monkeypatch):
    monkeypatch.setattr(poller.subprocess, "Popen", lambda *a, **k: pytest.fail("must not spawn"))
    assert poller._spawn_pipeline({"job_id": "job", "repo_url": "https://github.com/a/b", "environment": "prodution"}, "") is None


def test_claim_returns_revalidated_scope(monkeypatch):
    fresh = {"job_id":"job", "approved_cwes":[], "repo_url":"https://github.com/a/b"}
    monkeypatch.setattr(poller,"_http_json",lambda *a,**k:(200,fresh,""))
    assert poller._claim("http://backend","job","token","engine") is fresh


def test_claim_does_not_fall_back_to_stale_pending_payload(monkeypatch):
    monkeypatch.setattr(poller,"_http_json",lambda *a,**k:(200,{},""))
    errors=[]
    monkeypatch.setattr(poller,"_report_failure",lambda *a,**k:errors.append(k))
    assert poller._claim("http://backend","job","token","engine") is None
    assert errors[0]["reason"] == "engine_start_failed"


@pytest.mark.parametrize('environment', ['development','feature','staging','production'])
@pytest.mark.parametrize('approved', [False, True])
def test_high_one_halts_before_deploy_until_approved(monkeypatch,tmp_path,environment,approved):
    from app.models import SecurityFinding
    seen=[];callbacks=[]
    obj=LocalOrchestrator(tmp_path,environment=environment,approved_cwes=['CWE-639'] if approved else [],callback_url='http://backend/get-results')
    obj._scanned_commit_sha='a'*40
    monkeypatch.setattr(obj,'_check_required_env',lambda *a:None)
    monkeypatch.setattr(module,'resolve_workflow_definition',lambda **k:WorkflowDefinition('test','node',scans(),'test'))
    monkeypatch.setattr(module,'post_step_callback',lambda **k:(callbacks.append(k['payload']) or True,'http 200'))
    def execute(**kwargs):
        seen.append(kwargs['step_name'])
        findings=[SecurityFinding(scanner_name='semgrep',rule_id='idor',severity='high',title='IDOR',
            file_path='app.py',line_number=1,message='test',cwe='CWE-639')] if kwargs['step_name']=='deep' else []
        return StepRunResult(status='success',exit_code=0,summary_message='test',security_findings=findings)
    monkeypatch.setattr(obj,'_execute_step',execute)
    result,_=obj.run('https://github.com/example/repo','main')
    assert ('deploy' in seen) is approved
    assert result.status == ('success' if approved else 'failed')
    snapshot=next(p['step']['metadata']['security_gate'] for p in callbacks
        if p['step']['step_name']=='security_gate' and p['type']=='step_complete')
    assert snapshot['findings'][0]['severity']=='high'
    assert snapshot['verdict'] == ('pass' if approved else 'block_pending_approval')


@pytest.fixture(autouse=True)
def synthetic_workspace_checkpoint(monkeypatch):
    # These workflow-policy unit tests use mocked clone commands, not a Git workspace.
    monkeypatch.setattr('app.resume.save_checkpoint', lambda *args: None)
