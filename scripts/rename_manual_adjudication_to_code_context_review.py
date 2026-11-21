#!/usr/bin/env python3
"""Standardize manual/contextual adjudication as code-context review."""

from __future__ import annotations

import hashlib
import re
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_최종제출본_RQ제거.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_최종제출본_코드문맥검토.docx"
FONT = "Noto Sans CJK KR"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def transform_text(text: str) -> str:
    text = (
        text.replace("Single-reviewer adjudication", "Code-context review")
        .replace("single-reviewer adjudication", "code-context review")
        .replace("Manual adjudication", "Code-context review")
        .replace("manual adjudication", "code-context review")
        .replace("Contextual adjudication", "Code-context review")
        .replace("contextual adjudication", "code-context review")
        .replace("Contextual validation", "Code-context review")
        .replace("contextual validation", "code-context review")
        .replace("Contextually adjusted", "Code-context-review-adjusted")
        .replace("contextually adjusted", "code-context-review-adjusted")
        .replace("Manual validation", "Code-context review")
        .replace("manual validation", "code-context review")
    )
    text = re.sub(
        r"수동 판독|수동 검증|수동 검토|문맥 판독|문맥 검토",
        "코드 문맥 검토",
        text,
    )
    text = text.replace("정규화·판독", "정규화·코드 문맥 검토")
    text = text.replace("판독", "검토")
    return (
        text.replace("코드 문맥 검토을", "코드 문맥 검토를")
        .replace("코드 문맥 검토이", "코드 문맥 검토가")
        .replace("코드 문맥 검토과", "코드 문맥 검토와")
        .replace("코드 문맥 검토은", "코드 문맥 검토는")
        .replace("추가 검토이", "추가 검토가")
        .replace("이 검토으로", "이 검토로")
        .replace("표본 검토으로", "표본 검토로")
        .replace("공개 DT 검토과", "공개 DT 코드 문맥 검토와")
    )


def clear_and_set(paragraph, text: str):
    run_properties = None
    if paragraph.runs and paragraph.runs[0]._r.rPr is not None:
        run_properties = deepcopy(paragraph.runs[0]._r.rPr)
    for run in list(paragraph.runs):
        paragraph._p.remove(run._r)
    run = paragraph.add_run(text)
    if run_properties is not None:
        run._r.insert(0, run_properties)
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    return paragraph


def set_cell(cell, text: str) -> None:
    cell.text = text
    for paragraph in cell.paragraphs:
        for run in paragraph.runs:
            run.font.name = FONT
            run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)


def table_signature(table) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(cell.text for cell in row.cells)
        for row in table.rows
    )


def all_text(document: Document) -> str:
    chunks = [paragraph.text for paragraph in document.paragraphs]
    chunks.extend(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )
    return "\n".join(chunks)


def validate(source: Path, destination: Path, source_hash: str) -> None:
    if sha256(source) != source_hash:
        raise AssertionError("source DOCX changed")
    with zipfile.ZipFile(destination) as archive:
        if bad_member := archive.testzip():
            raise AssertionError(f"corrupt DOCX member: {bad_member}")

    source_doc = Document(source)
    output_doc = Document(destination)
    if len(source_doc.paragraphs) != len(output_doc.paragraphs):
        raise AssertionError("paragraph count changed")
    for index, (source_paragraph, output_paragraph) in enumerate(
        zip(source_doc.paragraphs, output_doc.paragraphs, strict=True)
    ):
        expected = transform_text(source_paragraph.text)
        if output_paragraph.text != expected:
            raise AssertionError(f"paragraph {index} changed beyond terminology")
        if output_paragraph.style.name != source_paragraph.style.name:
            raise AssertionError(f"paragraph {index} style changed")

    if len(source_doc.tables) != 15 or len(output_doc.tables) != 15:
        raise AssertionError("table count changed")
    for index, (source_table, output_table) in enumerate(
        zip(source_doc.tables, output_doc.tables, strict=True),
        start=1,
    ):
        expected = tuple(
            tuple(transform_text(cell) for cell in row)
            for row in table_signature(source_table)
        )
        if table_signature(output_table) != expected:
            raise AssertionError(f"table {index} changed beyond terminology")

    if len(source_doc.inline_shapes) != 1 or len(output_doc.inline_shapes) != 1:
        raise AssertionError("figure count changed")
    if len(source_doc.sections) != 1 or len(output_doc.sections) != 1:
        raise AssertionError("section count changed")
    if source_doc.paragraphs[0].text != output_doc.paragraphs[0].text:
        raise AssertionError("paper title changed")

    text = all_text(output_doc)
    for forbidden in (
        "수동 판독",
        "수동 검증",
        "수동 검토",
        "문맥 판독",
        "판독",
        "manual adjudication",
        "contextual adjudication",
        "contextual validation",
        "contextually adjusted",
        "검토을",
        "검토이",
        "검토과",
        "검토으로",
        "검토은",
        "single-reviewer",
        "Cohen",
        "RQ1",
        "RQ2",
        "RQ3",
    ):
        if forbidden.lower() in text.lower():
            raise AssertionError(f"old term remains: {forbidden}")
    if re.search(r"(?<!코드 )문맥 검토", text):
        raise AssertionError("unqualified context-review term remains")

    for required in (
        "코드 문맥 검토",
        "정규화·코드 문맥 검토 단계",
        "자동 탐지 결과의 코드 문맥 검토.",
        "검토 기준은 확인된 위험 패턴",
        "Table 8. Automatic, deduplicated, and code-context-review-adjusted DT results",
        "Table 9. Code-context review of automated DT findings",
        "after code-context review",
        "정밀도 0.533",
        "재현율 0.772",
        "F1-Score 0.630",
        "TP 728, FP 639, FN 215",
        "PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개",
        "CWE-327은 TP=0, FN=130",
        "Algorithm 1. Environment-Sensitive Vulnerability Decision-Making and Deployment Control",
    ):
        if required not in text:
            raise AssertionError(f"required content missing: {required}")

    for equation in (
        "D_H = min(5C_H, 19),   D_M = min(C_M, 4),   D_L = min(0.2C_L, 0.9)",
        "S = 100 − D_H − D_M − D_L  (C_C = 0);",
    ):
        if equation not in text:
            raise AssertionError(f"equation changed: {equation}")
    algorithm_conditions = (
        "INPUT: C_C, C_H, C_M, C_L, C_H^approved, environment\n"
        "C_H^active ← max(0, C_H − C_H^approved)\n"
        "IF C_C ≥ 1 THEN BLOCK\n"
        "ELSE IF C_H^active ≥ 1 THEN BLOCK_PENDING_APPROVAL\n"
        "ELSE IF C_M ≥ 1 AND environment ∈ {production, staging} "
        "THEN BLOCK_PENDING_APPROVAL\n"
        "ELSE IF C_M ≥ 1 THEN WARN\n"
        "ELSE PASS"
    )
    if algorithm_conditions not in text:
        raise AssertionError("Algorithm 1 conditions changed")


def build(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    source_hash = sha256(source)
    document = Document(source)

    for paragraph in document.paragraphs:
        revised = transform_text(paragraph.text)
        if revised != paragraph.text:
            clear_and_set(paragraph, revised)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                revised = transform_text(cell.text)
                if revised != cell.text:
                    set_cell(cell, revised)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".tmp.docx",
        delete=False,
    ) as handle:
        temp_path = Path(handle.name)
    try:
        document.save(temp_path)
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()

    validate(source, destination, source_hash)
    print(f"source={source}")
    print(f"source_sha256={source_hash}")
    print(f"output={destination}")
    print(f"output_sha256={sha256(destination)}")
    print(
        "validated=code_context_review_terminology:true tables:15 figure:1 "
        "equations:true algorithm_conditions:true experimental_data:true"
    )


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) >= 2 else DEFAULT_SOURCE
    destination = Path(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_DESTINATION
    if len(sys.argv) > 3:
        raise SystemExit(
            f"usage: {Path(sys.argv[0]).name} [SOURCE.docx] [DESTINATION.docx]"
        )
    build(source, destination)


if __name__ == "__main__":
    main()
