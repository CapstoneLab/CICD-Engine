import json
from pathlib import Path
import pytest
from app.models import SecurityFinding
from app.security_policy import evaluate
from app.scanners.semgrep_parser import parse_semgrep_report
from app.policy_environment import effective_environment
from app.utils.sandbox import sandbox_commands, wrap_command, validate_repository
from app.steps import clone
from app.utils.shell import CommandResult


def finding(cwe, severity, cvss=None):
    return SecurityFinding(scanner_name="semgrep", rule_id="x", severity=severity, title="x", file_path="x.py", line_number=1, message="x", cwe=cwe, cvss_score=cvss)


@pytest.mark.parametrize("cwe", ["CWE-89", "CWE-999", None])
def test_unselected_critical_does_not_gate(cwe):
    v = evaluate([finding(cwe, "critical")], selected_items=["CWE-79"], environment="development", approved_cwes=[cwe])
    assert v.verdict == "pass" and v.score == 100 and not v.requires_approval
    assert v.out_of_scope_count == 1


@pytest.mark.parametrize("severity,cvss", [("critical", None), ("low", 9.8)])
def test_catalog_does_not_lower_scanner_risk(severity, cvss):
    v = evaluate([finding("CWE-918", severity, cvss)], environment="development")
    assert v.counts["critical"] == 1 and v.verdict == "block"


@pytest.mark.parametrize("requested", [None, "development", "feature", "staging", "production"])
def test_operator_floor(requested, monkeypatch):
    monkeypatch.delenv("SECURITY_POLICY_MIN_ENVIRONMENT", raising=False)
    assert effective_environment(requested) == "production"


def test_scanner_cvss_and_metadata_preserved(tmp_path):
    report=tmp_path/'report.json'
    report.write_text(json.dumps({"results":[{"check_id":"x", "path":"x.py", "start":{"line":1}, "extra":{"severity":"INFO","metadata":{"cwe":"CWE-918","cvss_score":9.8}}}],"paths":{"scanned":["x.py"]}}))
    summary, findings = parse_semgrep_report(report)
    assert summary.critical_count == 1
    assert evaluate(findings).verdict == "block"


@pytest.mark.parametrize("paths", [None, {}, {"scanned":[]}])
def test_zero_or_missing_coverage_fails(tmp_path, paths):
    report=tmp_path/'report.json'; report.write_text(json.dumps({"results":[],"paths":paths}))
    with pytest.raises(ValueError, match="coverage"):
        parse_semgrep_report(report)


def test_external_symlink_rejected(tmp_path):
    (tmp_path/'escape').symlink_to('/etc/passwd')
    with pytest.raises(ValueError, match="escapes"):
        validate_repository(tmp_path)


def test_no_sandbox_image_never_falls_back_to_host(tmp_path, monkeypatch):
    monkeypatch.delenv("CICD_SANDBOX_IMAGE", raising=False)
    with sandbox_commands(tmp_path), pytest.raises(ValueError, match="pinned"):
        wrap_command(["sh","-c","id"],tmp_path,{})


def test_commit_failure_never_runs_other_code(tmp_path, monkeypatch):
    repo=tmp_path/'repo'; repo.mkdir()
    monkeypatch.setattr(clone, '_run_clone_command', lambda **kw: (kw['repo_dir'].mkdir(exist_ok=True) or CommandResult(0,'')))
    monkeypatch.setattr(clone, '_checkout_commit', lambda *a: False)
    result=clone.run_clone('https://github.com/a/b','main',repo,tmp_path/'log',commit_sha='a'*40)
    assert result.status == 'failed' and not repo.exists()
