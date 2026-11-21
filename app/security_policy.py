from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from app.models import SecurityFinding
from app.security_catalog import (
    ALL_CWES,
    GRADE_CAP,
    GRADE_CRITICAL,
    GRADE_DEDUCTION,
    GRADE_HIGH,
    GRADE_MEDIUM,
    lookup_by_cwe,
    normalize_selected_cwes,
    resolve_item,
    selected_items_summary,
)

POLICY_VERSION = "1.4.0"


# Gate verdicts (hierarchy-driven; score is advisory only and never gates).
VERDICT_BLOCK = "block"                              # Critical >= 1 or High >= 2 (no exception)
VERDICT_BLOCK_PENDING_APPROVAL = "block_pending_approval"  # High = 1 or Medium >= 2 (approval exception)
VERDICT_MANUAL_REVIEW = "manual_review"              # Out-of-scope findings in strict environments
VERDICT_WARN = "warn"                                # Medium = 1 or Low >= 1
VERDICT_PASS = "pass"                                # No active findings

# Gauge color follows the GATE verdict, not a score band, so it can never
# contradict the verdict (see manual §4-4 fix).
GAUGE_COLOR = {
    VERDICT_BLOCK: "red",
    VERDICT_BLOCK_PENDING_APPROVAL: "orange",
    VERDICT_MANUAL_REVIEW: "orange",
    VERDICT_WARN: "yellow",
    VERDICT_PASS: "green",
}

ENVIRONMENTS = {"production", "staging", "development", "feature"}


@dataclass
class SecurityVerdict:
    verdict: str
    score: float
    score_label: str
    gauge_color: str
    environment: str
    counts: dict[str, int]
    selected_count: int
    selected_items: list[dict[str, str]]
    out_of_scope_count: int
    requires_approval: bool
    score_breakdown: dict[str, float]
    scanned_commit_sha: str | None = None
    acknowledged_cwes: list[str] = field(default_factory=list)
    block_reasons: list[str] = field(default_factory=list)
    warn_reasons: list[str] = field(default_factory=list)
    policy_version: str = POLICY_VERSION
    final_risk_tier: str = "P4"
    unique_finding_count: int = 0
    medium_finding_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_environment(value: str | None) -> str:
    if not value:
        return "development"
    candidate = value.strip().lower()
    if candidate in ENVIRONMENTS:
        return candidate
    aliases = {
        "prod": "production",
        "stage": "staging",
        "dev": "development",
        "develop": "development",
        "feat": "feature",
        "feature_branch": "feature",
    }
    if candidate in aliases:
        return aliases[candidate]
    raise ValueError(f"Unsupported deployment environment: {value}")


def effective_severity(scanner: str | None, catalog: str | None = None, cvss: float | None = None) -> str:
    ranks = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    severity = (scanner or "").lower()
    if severity not in ranks:
        severity = "high"  # Unknown risk must not silently become Low.
    candidates = [severity, catalog or "low"]
    if cvss is not None:
        candidates.append("critical" if cvss >= 9 else "high" if cvss >= 7 else "medium" if cvss >= 4 else "low")
    return max(candidates, key=lambda value: ranks[value])


def _mark_scope(findings: Iterable[SecurityFinding], selected_cwes: set[str]) -> None:
    """Only selected items gate a selective run; full runs include every finding."""
    for finding in findings:
        if finding.scanner_name.lower() == "gitleaks":
            finding.cwe = "CWE-798"
        item = lookup_by_cwe(finding.cwe)
        if item:
            finding.policy_item = item.key
        finding.severity = effective_severity(finding.severity, item.grade if item else None, finding.cvss_score)
        finding.in_scope = selected_cwes == set(ALL_CWES) or (item is not None and item.cwe in selected_cwes)


def count_by_severity(findings: Iterable[SecurityFinding]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        severity = (finding.severity or "low").lower()
        if severity not in counts:
            severity = "low"
        counts[severity] += 1
    return counts


def calculate_score(counts: dict[str, int]) -> tuple[float, dict[str, float]]:
    """Capped score per manual §4. Returns (score, breakdown).

    Caps keep the hierarchy intact: a lower grade's total deduction can never
    reach a single finding of the grade above it (19<20, 4<5, 0.9<1).
    With Critical present the score is forced into the 0~40 danger zone.
    """
    high_ded = min(counts.get("high", 0) * GRADE_DEDUCTION["high"], GRADE_CAP["high"])
    med_ded = min(counts.get("medium", 0) * GRADE_DEDUCTION["medium"], GRADE_CAP["medium"])
    low_ded = min(counts.get("low", 0) * GRADE_DEDUCTION["low"], GRADE_CAP["low"])
    crit = counts.get("critical", 0)

    if crit >= 1:
        raw = 100.0 - crit * GRADE_DEDUCTION["critical"] - high_ded - med_ded - low_ded
        score = max(0.0, min(40.0, raw))
    else:
        score = max(0.0, 100.0 - high_ded - med_ded - low_ded)

    breakdown = {
        "critical": round(crit * GRADE_DEDUCTION["critical"], 2),
        "high": round(high_ded, 2),
        "medium": round(med_ded, 2),
        "low": round(low_ded, 2),
    }
    return round(score, 1), breakdown


_GRADE_LABEL = {"critical": "Critical", "high": "High", "medium": "Medium", "low": "Low"}


def _gate_reasons(findings: list[SecurityFinding], grade: str, *, hard_block: bool = False) -> list[str]:
    """Item-specific gate-rule strings (manual §6 rule 1), one per distinct item."""
    seen: dict[str, SecurityFinding] = {}
    for f in findings:
        if (f.severity or "").lower() != grade:
            continue
        key = f.policy_item or f.cwe or f.rule_id
        seen.setdefault(key, f)
    reasons: list[str] = []
    policy = "즉시 차단 정책" if grade == "critical" or hard_block else "승인 필요 정책"
    for f in seen.values():
        item = lookup_by_cwe(f.cwe)
        name = item.name if item else (f.title or f.rule_id)
        cwe = (item.cwe if item else f.cwe) or "CWE-?"
        reasons.append(f"{name} ({cwe}, {_GRADE_LABEL[grade]}) 검출 — {policy}")
    return reasons


def _normalize_approved_cwes(approved: Iterable[object] | None) -> set[str]:
    """Resolve approval tokens (CWE ids or item keys) to a set of CWE ids.
    Critical items are dropped here — Critical can never be acknowledged."""
    result: set[str] = set()
    for token in approved or []:
        item = resolve_item(token)
        if item is not None and item.grade != GRADE_CRITICAL:
            result.add(item.cwe)
    return result


def _unique_findings(findings: Iterable[SecurityFinding]) -> list[SecurityFinding]:
    unique: dict[tuple[str | None, str | None, str, int], SecurityFinding] = {}
    for finding in findings:
        key = (finding.cwe, finding.rule_id, finding.file_path, finding.line_number)
        unique.setdefault(key, finding)
    return list(unique.values())


def evaluate(
    findings: list[SecurityFinding],
    selected_items: Iterable[object] | None = None,
    environment: str = "development",
    approved_cwes: Iterable[object] | None = None,
    scanned_commit_sha: str | None = None,
) -> SecurityVerdict:
    env = normalize_environment(environment)
    selected_cwes = normalize_selected_cwes(selected_items)
    approved_set = _normalize_approved_cwes(approved_cwes)

    _mark_scope(findings, selected_cwes)
    in_scope = [f for f in findings if f.in_scope]
    unique_in_scope = _unique_findings(in_scope)
    out_of_scope_count = sum(1 for f in findings if not f.in_scope)

    # Approval never overrides Critical or the original High >= 2 threshold.
    acknowledged = [
        f for f in in_scope
        if f.severity in (GRADE_HIGH, GRADE_MEDIUM) and f.cwe in approved_set
    ]
    acknowledged_cwes = sorted({f.cwe for f in acknowledged if f.cwe})
    active_high = [f for f in in_scope if f.severity == GRADE_HIGH and f.cwe not in approved_set]
    active_medium = [f for f in in_scope if f.severity == GRADE_MEDIUM and f.cwe not in approved_set]

    # score reflects all in-scope findings — accepted risk still counts toward health
    counts = count_by_severity(in_scope)
    score, breakdown = calculate_score(counts)

    selected_summary = selected_items_summary(selected_cwes)
    selected_count = len(selected_summary)
    score_label = f"{score}/100 (전체 검사 기준)" if selected_cwes == set(ALL_CWES) else f"{score}/100 (선택한 검사 항목 {selected_count}개 기준)"

    block_reasons: list[str] = []
    warn_reasons: list[str] = []
    requires_approval = False
    final_risk_tier = "P4"
    medium_finding_count = sum(
        1 for finding in unique_in_scope if (finding.severity or "").lower() == GRADE_MEDIUM
    )

    # ----- hierarchy gate (manual §3): first match wins -----
    # acknowledged High no longer triggers the gate.
    if any(finding.scanner_name.lower() == "gitleaks" for finding in in_scope):
        final_risk_tier = "P0"
        verdict = VERDICT_BLOCK
        block_reasons.append("Gitleaks Secret 탐지 — P0 보안 보류")
    elif counts["critical"] >= 1:
        final_risk_tier = "P1"
        verdict = VERDICT_BLOCK
        block_reasons.extend(_gate_reasons(in_scope, "critical"))
    elif counts["high"] >= 2:
        final_risk_tier = "P1"
        verdict = VERDICT_BLOCK
        block_reasons.extend(_gate_reasons(in_scope, "high", hard_block=True))
    elif active_high or len(active_medium) >= 2:
        final_risk_tier = "P1" if active_high else "P2"
        verdict = VERDICT_BLOCK_PENDING_APPROVAL
        requires_approval = True
        block_reasons.extend(_gate_reasons(active_high, "high"))
        if len(active_medium) >= 2:
            block_reasons.extend(_gate_reasons(active_medium, "medium"))
    elif active_medium or counts["low"] >= 1:
        final_risk_tier = "P2" if active_medium else "P3"
        verdict = VERDICT_WARN
        if active_medium:
            warn_reasons.append(f"Medium {len(active_medium)}건 검출 — 경고(배포 통과)")
        if counts["low"]:
            warn_reasons.append(f"Low {counts['low']}건 검출 — 경고(배포 통과)")
    else:
        verdict = VERDICT_PASS

    if acknowledged_cwes:
        warn_reasons.append(
            f"승인 수용된 High/Medium: {', '.join(acknowledged_cwes)}"
        )

    return SecurityVerdict(
        verdict=verdict,
        score=score,
        score_label=score_label,
        gauge_color=GAUGE_COLOR[verdict],
        environment=env,
        counts=counts,
        selected_count=selected_count,
        selected_items=selected_summary,
        out_of_scope_count=out_of_scope_count,
        requires_approval=requires_approval,
        score_breakdown=breakdown,
        scanned_commit_sha=scanned_commit_sha,
        acknowledged_cwes=acknowledged_cwes,
        block_reasons=block_reasons,
        warn_reasons=warn_reasons,
        final_risk_tier=final_risk_tier,
        unique_finding_count=len(unique_in_scope),
        medium_finding_count=medium_finding_count,
    )


def is_blocking(verdict: SecurityVerdict | str) -> bool:
    """Both hard block and pending-approval halt the pipeline."""
    value = verdict.verdict if isinstance(verdict, SecurityVerdict) else verdict
    return value in (
        VERDICT_BLOCK,
        VERDICT_BLOCK_PENDING_APPROVAL,
        VERDICT_MANUAL_REVIEW,
    )


def format_summary(verdict: SecurityVerdict) -> str:
    counts = verdict.counts
    base = (
        f"verdict={verdict.verdict.upper()} {verdict.score_label} env={verdict.environment} "
        f"critical={counts['critical']} high={counts['high']} "
        f"medium={counts['medium']} low={counts['low']}"
    )
    base += f" risk={verdict.final_risk_tier} policy={verdict.policy_version}"
    if verdict.out_of_scope_count:
        base += f" (out_of_scope={verdict.out_of_scope_count})"
    if verdict.verdict in (
        VERDICT_BLOCK,
        VERDICT_BLOCK_PENDING_APPROVAL,
        VERDICT_MANUAL_REVIEW,
    ):
        suffix = " | approval required" if verdict.requires_approval else ""
        return f"{base} | blocked: {'; '.join(verdict.block_reasons)}{suffix}"
    if verdict.verdict == VERDICT_WARN:
        return f"{base} | warn: {'; '.join(verdict.warn_reasons)}"
    return base
