from __future__ import annotations

import os
import re

SENSITIVE_KEYWORDS = ("KEY", "SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "AUTH")
MIN_VALUE_LENGTH = 4
MASK = "****"


def _is_sensitive_key(name: str) -> bool:
    upper = name.upper()
    return any(keyword in upper for keyword in SENSITIVE_KEYWORDS)


def collect_sensitive_values() -> list[str]:
    values: list[str] = []
    for key, value in os.environ.items():
        if not value or len(value) < MIN_VALUE_LENGTH:
            continue
        if _is_sensitive_key(key):
            values.append(value)
    values.sort(key=len, reverse=True)
    return values


def mask_line(line: str, sensitive_values: list[str] | None = None) -> str:
    if sensitive_values is None:
        sensitive_values = collect_sensitive_values()
    masked = line
    for value in sensitive_values:
        if value and value in masked:
            masked = masked.replace(value, MASK)
    masked = _mask_inline_assignments(masked)
    return masked


_ASSIGN_PATTERN = re.compile(
    r"\b([A-Z][A-Z0-9_]*)=('[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)


def _mask_inline_assignments(text: str) -> str:
    def _sub(match: re.Match[str]) -> str:
        name = match.group(1)
        if not _is_sensitive_key(name):
            return match.group(0)
        raw_value = match.group(2)
        quote = ""
        if raw_value.startswith("'") and raw_value.endswith("'"):
            quote = "'"
        elif raw_value.startswith('"') and raw_value.endswith('"'):
            quote = '"'
        return f"{name}={quote}{MASK}{quote}"

    return _ASSIGN_PATTERN.sub(_sub, text)
