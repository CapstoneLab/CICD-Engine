from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


@dataclass
class SecurityFinding:
    scanner_name: str
    rule_id: str
    severity: str
    title: str
    file_path: str
    line_number: int
    message: str
    cvss_score: float | None = None
    ai_recommendation: str | None = None
    code_snippet: str | None = None
    code_snippet_start_line: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class SecuritySummary:
    scanner_name: str
    scan_type: str
    critical_count: int
    high_count: int
    medium_count: int
    low_count: int
    max_detected_severity: str
    max_cvss_score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class StepRunResult:
    status: str
    exit_code: int | None
    summary_message: str
    security_summary: SecuritySummary | None = None
    security_findings: list[SecurityFinding] = field(default_factory=list)


@dataclass
class PipelineStep:
    step_name: str
    continue_on_failure: bool = False
    status: str = "pending"
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None
    summary_message: str | None = None
    log_file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PipelineRun:
    run_id: str
    repo_url: str
    branch: str | None
    runtime_type: str = "node"
    runtime_version: str | None = None
    workflow_name: str | None = None
    workflow_source: str | None = None
    status: str = "queued"
    current_step: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    steps: list[PipelineStep] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "repo_url": self.repo_url,
            "branch": self.branch,
            "runtime_type": self.runtime_type,
            "runtime_version": self.runtime_version,
            "workflow_name": self.workflow_name,
            "workflow_source": self.workflow_source,
            "status": self.status,
            "current_step": self.current_step,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "steps": [step.to_dict() for step in self.steps],
        }
