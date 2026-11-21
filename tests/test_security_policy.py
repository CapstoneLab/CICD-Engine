from app.models import SecurityFinding
from app.security_policy import (
    VERDICT_MANUAL_REVIEW,
    VERDICT_PASS,
    evaluate,
    is_blocking,
)


def _finding(*, cwe: str | None, severity: str = "low") -> SecurityFinding:
    return SecurityFinding(
        scanner_name="test",
        rule_id="TEST-001",
        severity=severity,
        title="Test finding",
        file_path="src/example.py",
        line_number=1,
        message="test",
        cwe=cwe,
    )


def test_unselected_finding_does_not_gate_production() -> None:
    verdict = evaluate(
        [_finding(cwe="CWE-999", severity="critical")],
        selected_items=["CWE-79"],
        environment="production",
    )

    assert verdict.verdict == "pass"
    assert not verdict.requires_approval
    assert verdict.out_of_scope_count == 1
    assert not is_blocking(verdict)


def test_out_of_scope_finding_does_not_auto_block_development() -> None:
    verdict = evaluate(
        [_finding(cwe="CWE-999")],
        selected_items=["CWE-79"],
        environment="development",
    )

    assert verdict.verdict == VERDICT_PASS
    assert verdict.out_of_scope_count == 1
    assert not is_blocking(verdict)


def test_catalog_finding_remains_subject_to_severity_gate() -> None:
    verdict = evaluate(
        [_finding(cwe="CWE-89", severity="low")],
        environment="development",
    )

    assert verdict.verdict == "block"
    assert is_blocking(verdict)


def test_gitleaks_finding_is_p0() -> None:
    finding = _finding(cwe="CWE-798")
    finding.scanner_name = "gitleaks"

    verdict = evaluate([finding], environment="production")

    assert verdict.final_risk_tier == "P0"
    assert verdict.verdict == "block"
    assert verdict.policy_version == "1.4.0"


def test_thirty_unique_medium_findings_require_approval() -> None:
    findings = []
    for index in range(30):
        finding = _finding(cwe="CWE-22", severity="low")
        finding.file_path = f"src/example_{index}.py"
        finding.line_number = index + 1
        findings.append(finding)

    verdict = evaluate(findings, environment="production")

    assert verdict.final_risk_tier == "P2"
    assert verdict.medium_finding_count == 30
    assert verdict.verdict == "block_pending_approval"


import pytest
from app.security_policy import normalize_environment


def mediums(n):
    findings = [_finding(cwe="CWE-22") for _ in range(n)]
    for i, f in enumerate(findings):
        f.line_number = i + 1
    return findings


@pytest.mark.parametrize("env", ["production", "staging"])
@pytest.mark.parametrize("extra", ["unknown", "medium10", "medium30", "both"])
@pytest.mark.parametrize("secret", [False, True])
def test_hard_block_cannot_be_downgraded(env, extra, secret):
    finding = _finding(cwe="CWE-798" if secret else "CWE-89")
    if secret:
        finding.scanner_name = "gitleaks"
    extras = {
        "unknown": [_finding(cwe="CWE-999")], "medium10": mediums(10),
        "medium30": mediums(30), "both": mediums(30) + [_finding(cwe="CWE-999")],
    }
    v = evaluate([finding] + extras[extra], environment=env)
    assert v.verdict == "block"
    assert not v.requires_approval
    assert v.gauge_color == "red"


@pytest.mark.parametrize("env", ["production", "staging"])
def test_medium30_requires_approval_with_other_findings(env):
    v = evaluate(mediums(30) + [_finding(cwe="CWE-999")], environment=env)
    assert v.verdict == "block_pending_approval"
    assert v.requires_approval


@pytest.mark.parametrize("env", ["development", "feature", "production", "staging"])
@pytest.mark.parametrize("cwe", ["CWE-798", None, "CWE-999"])
def test_secrets_are_optional_for_selected_runs(env, cwe):
    f = _finding(cwe=cwe)
    f.scanner_name = "gitleaks"
    v = evaluate([f], selected_items=["CWE-79"], environment=env)
    assert v.verdict == "pass"
    assert v.score == 100
    assert "CWE-798" not in {x["cwe"] for x in v.selected_items}


@pytest.mark.parametrize("n,expected", [(1, "warn"), (2, "block_pending_approval"), (30, "block_pending_approval")])
def test_medium_threshold_is_environment_independent(n, expected):
    assert evaluate(mediums(n), environment="production").verdict == expected
    assert evaluate(mediums(n), environment="development").verdict == expected


def test_raw_occurrences_gate_and_unique_count_is_reported():
    verdict = evaluate([_finding(cwe="CWE-22") for _ in range(30)], environment="production")
    assert verdict.verdict == "block_pending_approval"
    assert verdict.medium_finding_count == 1


def test_high_exception_and_score_unchanged():
    f = _finding(cwe="CWE-639")
    assert evaluate([f]).verdict == "block_pending_approval"
    v = evaluate([f], approved_cwes=["CWE-639"])
    assert v.verdict == "pass"
    assert v.score == 95.0
    assert evaluate([_finding(cwe="CWE-89")], approved_cwes=["CWE-89"]).verdict == "block"


def test_environment_typo_is_rejected_and_alias_preserved():
    with pytest.raises(ValueError):
        normalize_environment("prodution")
    assert normalize_environment("prod") == "production"


@pytest.mark.parametrize("env", ["development", "feature", "staging", "production"])
@pytest.mark.parametrize("severity,n,expected", [
    ("critical", 1, "block"), ("high", 1, "block_pending_approval"),
    ("high", 2, "block"), ("medium", 1, "warn"),
    ("medium", 2, "block_pending_approval"), ("low", 1, "warn"),
    ("low", 10, "warn"), ("low", 0, "pass"),
])
def test_policy_threshold_matrix(env, severity, n, expected):
    findings = [_finding(cwe=None, severity=severity) for _ in range(n)]
    v = evaluate(findings, environment=env)
    assert v.verdict == expected
    assert v.requires_approval == (expected == "block_pending_approval")
    assert is_blocking(v) == (expected in ("block", "block_pending_approval"))


def test_high_two_cannot_be_approved():
    v = evaluate([_finding(cwe="CWE-639") for _ in range(2)], approved_cwes=["CWE-639"])
    assert v.verdict == "block"
    assert not v.requires_approval


def test_medium_approval_and_mixed_priority():
    findings = mediums(2)
    assert evaluate(findings, approved_cwes=["CWE-22"]).verdict == "pass"
    assert evaluate(findings + [_finding(cwe="CWE-639")]).verdict == "block_pending_approval"
    assert evaluate(findings + [_finding(cwe="CWE-639") for _ in range(2)]).verdict == "block"
