from __future__ import annotations

import json
from pathlib import Path

from app.models import SecurityFinding, SecuritySummary


def parse_gitleaks_report(report_file: Path) -> tuple[SecuritySummary, list[SecurityFinding]]:
    # File/JSON errors propagate to the scan step and halt the pipeline.
    data = json.loads(report_file.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("Gitleaks report must be a JSON array")
    if any(not isinstance(item, dict) or not item.get("RuleID") or not item.get("File")
           or not isinstance(item.get("StartLine", item.get("Line")), int) for item in data):
        raise ValueError("Gitleaks report contains malformed findings")

    findings: list[SecurityFinding] = []
    for item in data if isinstance(data, list) else []:
        findings.append(
            SecurityFinding(
                scanner_name="gitleaks",
                rule_id=str(item.get("RuleID", "unknown")),
                severity="critical",
                title=str(item.get("Description", "Potential secret detected")),
                file_path=str(item.get("File", "")),
                line_number=int(item.get("StartLine", item.get("Line", 0)) or 0),
                message="Hardcoded secret detected (auto-classified as Critical per security policy)",
                cvss_score=None,
                cwe="CWE-798",
                policy_item="hardcoded-secret",
                column_number=int(item.get("StartColumn", 0) or 0) or None,
            )
        )

    count = len(findings)
    summary = SecuritySummary(
        scanner_name="gitleaks",
        scan_type="lightweight",
        critical_count=count,
        high_count=0,
        medium_count=0,
        low_count=0,
        max_detected_severity="critical" if count > 0 else "none",
    )
    return summary, findings
