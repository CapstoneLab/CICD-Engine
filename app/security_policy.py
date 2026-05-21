from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Iterable

from app.models import SecurityFinding


VERDICT_BLOCK = "block"
VERDICT_WARN = "warn"
VERDICT_PASS = "pass"


ENVIRONMENT_THRESHOLDS: dict[str, dict[str, Any]] = {
    "production": {"min_score": 85, "max_critical": 0, "max_high": 2},
    "staging": {"min_score": 75, "max_critical": 0, "max_high": 4},
    "development": {"min_score": 60, "max_critical": 0, "max_high": 4},
    "feature": {"min_score": 50, "max_critical": 0, "max_high": 4},
}

UNIVERSAL_BLOCK_RULES = {
    "max_total_findings": 50,
    "warn_high_min": 1,
    "warn_high_max": 4,
    "warn_medium_min": 20,
}


@dataclass
class SecurityVerdict:
    verdict: str
    score: float
    environment: str
    counts: dict[str, int]
    thresholds: dict[str, Any]
    block_reasons: list[str] = field(default_factory=list)
    warn_reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def normalize_environment(value: str | None) -> str:
    if not value:
        return "development"
    candidate = value.strip().lower()
    if candidate in ENVIRONMENT_THRESHOLDS:
        return candidate
    aliases = {
        "prod": "production",
        "stage": "staging",
        "dev": "development",
        "develop": "development",
        "feat": "feature",
        "feature_branch": "feature",
    }
    return aliases.get(candidate, "development")


def count_by_severity(findings: Iterable[SecurityFinding]) -> dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in findings:
        severity = (finding.severity or "low").lower()
        if severity not in counts:
            severity = "low"
        counts[severity] += 1
    return counts


def calculate_score(counts: dict[str, int]) -> float:
    if counts.get("critical", 0) >= 5:
        return 0.0
    score = (
        100.0
        - counts.get("critical", 0) * 20
        - counts.get("high", 0) * 5
        - counts.get("medium", 0) * 1
        - counts.get("low", 0) * 0.2
    )
    if score < 0:
        return 0.0
    return round(score, 1)


def evaluate(
    findings: list[SecurityFinding],
    environment: str = "development",
) -> SecurityVerdict:
    env = normalize_environment(environment)
    thresholds = ENVIRONMENT_THRESHOLDS[env].copy()
    thresholds["max_total_findings"] = UNIVERSAL_BLOCK_RULES["max_total_findings"]

    counts = count_by_severity(findings)
    total = sum(counts.values())
    score = calculate_score(counts)

    block_reasons: list[str] = []
    warn_reasons: list[str] = []

    if counts["critical"] > thresholds["max_critical"]:
        block_reasons.append(
            f"Critical findings {counts['critical']} > {thresholds['max_critical']}"
        )
    if counts["high"] >= 5:
        block_reasons.append(f"High findings {counts['high']} >= 5")
    elif counts["high"] > thresholds["max_high"]:
        block_reasons.append(
            f"High findings {counts['high']} exceeds {env} limit ({thresholds['max_high']})"
        )
    if total > thresholds["max_total_findings"]:
        block_reasons.append(
            f"Total findings {total} > {thresholds['max_total_findings']}"
        )
    if score < thresholds["min_score"]:
        block_reasons.append(
            f"Security score {score} < {env} threshold ({thresholds['min_score']})"
        )

    if not block_reasons:
        if (
            UNIVERSAL_BLOCK_RULES["warn_high_min"]
            <= counts["high"]
            <= UNIVERSAL_BLOCK_RULES["warn_high_max"]
        ):
            warn_reasons.append(f"High findings {counts['high']} (1~4 range)")
        if counts["medium"] >= UNIVERSAL_BLOCK_RULES["warn_medium_min"]:
            warn_reasons.append(f"Medium findings {counts['medium']} >= 20")

    if block_reasons:
        verdict = VERDICT_BLOCK
    elif warn_reasons:
        verdict = VERDICT_WARN
    else:
        verdict = VERDICT_PASS

    return SecurityVerdict(
        verdict=verdict,
        score=score,
        environment=env,
        counts=counts,
        thresholds=thresholds,
        block_reasons=block_reasons,
        warn_reasons=warn_reasons,
    )


def format_summary(verdict: SecurityVerdict) -> str:
    counts = verdict.counts
    base = (
        f"verdict={verdict.verdict.upper()} score={verdict.score} env={verdict.environment} "
        f"critical={counts['critical']} high={counts['high']} "
        f"medium={counts['medium']} low={counts['low']}"
    )
    if verdict.verdict == VERDICT_BLOCK:
        return f"{base} | blocked: {'; '.join(verdict.block_reasons)}"
    if verdict.verdict == VERDICT_WARN:
        return f"{base} | warn: {'; '.join(verdict.warn_reasons)}"
    return base
