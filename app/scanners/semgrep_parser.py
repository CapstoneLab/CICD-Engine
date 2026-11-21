from __future__ import annotations

import json
import re
from pathlib import Path

from app.security_policy import effective_severity
from app.models import SecurityFinding, SecuritySummary
from app.security_catalog import lookup_by_cwe, normalize_cwe


def _extract_cwe(extra: dict, selected_cwes: set[str] | None = None) -> str | None:
    metadata = extra.get("metadata", {}) or {}
    if selected_cwes:
        candidates = metadata.get("cwe") or metadata.get("cwe_id") or extra.get("cwe") or []
        if not isinstance(candidates, list):
            candidates = [candidates]
        for candidate in candidates:
            normalized = normalize_cwe(candidate)
            if normalized in selected_cwes:
                return normalized
    for candidate in (metadata.get("cwe"), metadata.get("cwe_id"), extra.get("cwe")):
        normalized = normalize_cwe(candidate)
        if normalized:
            return normalized
    return None


def _normalize_severity(extra: dict) -> str:
    levels = []
    metadata = extra.get("metadata") or {}
    for raw in (extra.get("severity"), metadata.get("severity"), metadata.get("impact")):
        value = str(raw or "").lower()
        for aliases, level in (({"critical"}, "critical"), ({"high", "error"}, "high"), ({"medium", "warning"}, "medium"), ({"low", "info", "inventory", "experiment"}, "low")):
            if value in aliases:
                levels.append(level)
    return max(levels, key={"low":0,"medium":1,"high":2,"critical":3}.get) if levels else "high"


def _max_severity(critical: int, high: int, medium: int, low: int) -> str:
    if critical > 0:
        return "critical"
    if high > 0:
        return "high"
    if medium > 0:
        return "medium"
    if low > 0:
        return "low"
    return "none"


def _extract_cvss_score(extra: dict) -> float | None:
    metadata = extra.get("metadata", {})

    candidates = [
        metadata.get("cvss_score"),
        metadata.get("security-severity"),
        metadata.get("cvss"),
        extra.get("cvss_score"),
    ]

    for candidate in candidates:
        if candidate is None:
            continue

        if isinstance(candidate, (int, float)):
            return float(candidate)

        if isinstance(candidate, dict):
            nested = candidate.get("score")
            if isinstance(nested, (int, float)):
                return float(nested)
            if isinstance(nested, str):
                try:
                    return float(nested)
                except ValueError:
                    continue

        if isinstance(candidate, str):
            try:
                return float(candidate)
            except ValueError:
                continue

    return None


def parse_semgrep_report(report_file: Path, selected_cwes: set[str] | None = None) -> tuple[SecuritySummary, list[SecurityFinding]]:
    # File/JSON errors propagate to the scan step and halt the pipeline.
    data = json.loads(report_file.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("results"), list):
        raise ValueError("Semgrep report must contain a results array")
    if not isinstance(data.get("paths"), dict) or not data["paths"].get("scanned"):
        raise ValueError("Semgrep scanned no files; coverage is unverified")
    if data.get("errors"):
        raise ValueError("Semgrep report contains scan errors; scan is incomplete")
    if any(not isinstance(item, dict) or not item.get("path")
           or not isinstance(item.get("start"), dict)
           or not isinstance(item.get("extra"), dict) for item in data["results"]):
        raise ValueError("Semgrep report contains malformed findings")

    findings: list[SecurityFinding] = []
    critical = 0
    high = 0
    medium = 0
    low = 0
    max_cvss_score: float | None = None

    for item in data.get("results", []):
        extra = item.get("extra", {})
        cvss_score = _extract_cvss_score(extra)

        # Grade is derived from the CWE via the 16-item catalog. semgrep's own
        # severity is only a fallback for CWEs outside the catalog.
        cwe = _extract_cwe(extra, selected_cwes)
        catalog_item = lookup_by_cwe(cwe)
        if catalog_item is not None:
            severity = effective_severity(_normalize_severity(extra), catalog_item.grade, cvss_score)
            policy_item = catalog_item.key
        else:
            severity = effective_severity(_normalize_severity(extra), cvss=cvss_score)
            policy_item = None

        if cvss_score is not None:
            max_cvss_score = cvss_score if max_cvss_score is None else max(max_cvss_score, cvss_score)

        if severity == "critical":
            critical += 1
        elif severity == "high":
            high += 1
        elif severity == "medium":
            medium += 1
        else:
            low += 1

        findings.append(
            SecurityFinding(
                scanner_name="semgrep",
                rule_id=str(item.get("check_id", "unknown")),
                severity=severity,
                title=str(extra.get("message", "Semgrep finding")),
                file_path=str(item.get("path", "")),
                line_number=int(item.get("start", {}).get("line", 0) or 0),
                message=str(extra.get("message", "Semgrep finding")),
                cvss_score=cvss_score,
                cwe=cwe,
                policy_item=policy_item,
                column_number=int(item.get("start", {}).get("col", 0) or 0) or None,
            )
        )

    summary = SecuritySummary(
        scanner_name="semgrep",
        scan_type="deep",
        critical_count=critical,
        high_count=high,
        medium_count=medium,
        low_count=low,
        max_detected_severity=_max_severity(critical, high, medium, low),
        max_cvss_score=max_cvss_score,
    )

    return summary, findings
