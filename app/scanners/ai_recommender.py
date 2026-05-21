from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import SecurityFinding


MODEL_ID = "claude-sonnet-4-6"
MAX_TOKENS = 1500

SYSTEM_PROMPT = (
    "You are a secure-coding reviewer. For each vulnerability finding provided by the user, "
    "respond with exactly 4 sentences in Korean that (1) explain the root cause, "
    "(2) describe the concrete fix at the reported file and line, "
    "(3) mention a safer API or pattern to adopt, "
    "and (4) give one preventative guideline for the codebase. "
    "Do not use bullet points, headings, or code fences. Return only the 4 sentences as a single paragraph."
)


def _build_user_prompt(finding: "SecurityFinding") -> str:
    cvss = f"{finding.cvss_score:.1f}" if finding.cvss_score is not None else "N/A"
    return (
        f"rule_id: {finding.rule_id}\n"
        f"severity: {finding.severity} (cvss={cvss})\n"
        f"file: {finding.file_path}:{finding.line_number}\n"
        f"message: {finding.message}"
    )


def generate_recommendations(findings: list["SecurityFinding"]) -> None:
    if not findings:
        return

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return

    try:
        from anthropic import Anthropic
    except ImportError:
        return

    client = Anthropic(api_key=api_key)

    for finding in findings:
        try:
            response = client.messages.create(
                model=MODEL_ID,
                max_tokens=MAX_TOKENS,
                system=[
                    {
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": _build_user_prompt(finding)}],
            )
        except Exception as exc:  # noqa: BLE001
            finding.ai_recommendation = f"[AI 권고 생성 실패: {exc}]"
            continue

        text_parts: list[str] = []
        for block in response.content:
            text = getattr(block, "text", None)
            if text:
                text_parts.append(text)
        finding.ai_recommendation = " ".join(text_parts).strip() or None
