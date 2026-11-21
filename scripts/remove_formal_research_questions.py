#!/usr/bin/env python3
"""Replace formal RQ1-RQ3 items with prose validation objectives."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_최종제출본.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_최종제출본_RQ제거.docx"
FONT = "Noto Sans CJK KR"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def find_paragraph(document: Document, prefix: str):
    matches = [
        paragraph
        for paragraph in document.paragraphs
        if paragraph.text.startswith(prefix)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"paragraph {prefix!r}: expected 1, found {len(matches)}"
        )
    return matches[0]


def replace(document: Document, prefix: str, text: str):
    return clear_and_set(find_paragraph(document, prefix), text)


def delete_paragraph(paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is None:
        raise ValueError("paragraph has no parent")
    parent.remove(element)
    paragraph._p = paragraph._element = None


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
    if len(source_doc.paragraphs) - len(output_doc.paragraphs) != 3:
        raise AssertionError("unexpected paragraph-count change")
    if len(source_doc.tables) != 15 or len(output_doc.tables) != 15:
        raise AssertionError("table count changed")
    for index, (source_table, output_table) in enumerate(
        zip(source_doc.tables, output_doc.tables, strict=True),
        start=1,
    ):
        if table_signature(source_table) != table_signature(output_table):
            raise AssertionError(f"table {index} data changed")
    if len(source_doc.inline_shapes) != 1 or len(output_doc.inline_shapes) != 1:
        raise AssertionError("figure count changed")
    if len(source_doc.sections) != 1 or len(output_doc.sections) != 1:
        raise AssertionError("section count changed")
    if source_doc.paragraphs[0].text != output_doc.paragraphs[0].text:
        raise AssertionError("paper title changed")

    text = all_text(output_doc)
    for forbidden in (
        "RQ1",
        "RQ2",
        "RQ3",
        "연구 질문은 다음과 같다",
        "검증 절차는 연구 질문에 따라",
    ):
        if forbidden in text:
            raise AssertionError(f"formal research-question text remains: {forbidden}")
    for required in (
        "제안 절차를 검증하기 위해 먼저 OWASP Benchmark를 이용하여",
        "검증 절차는 세 가지 관점으로 구성하였다.",
        "제4.3.1절에서는 Benchmark 기준 성능과 룰 진단을",
        "OWASP Benchmark v1.2는 현재 룰셋의 기준 성능 평가에 사용하고",
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

    rq_intro = replace(
        document,
        "이러한 기여를 평가하기 위한 연구 질문은 다음과 같다.",
        "제안 절차를 검증하기 위해 먼저 OWASP Benchmark를 이용하여 현재 정적 분석 "
        "룰셋의 CWE별 탐지 성능과 취약 영역을 확인한다. 다음으로 공개 DT 코드베이스에서 "
        "정확 위치 중복 제거와 문맥 판독이 탐지 결과 및 배포 제어 실행 상태에 미치는 "
        "영향을 분석한다. 마지막으로 구성요소 제거, 가중치 민감도 및 코드 계보 분석을 "
        "통해 정책 기반 보조지수와 배포 제어 실행 상태의 안정성을 평가한다.",
    )
    rq_paragraphs = [
        find_paragraph(document, "RQ1:"),
        find_paragraph(document, "RQ2:"),
        find_paragraph(document, "RQ3:"),
    ]
    for paragraph in rq_paragraphs:
        delete_paragraph(paragraph)

    replace(
        document,
        "본 연구는 이러한 연구 공백을",
        "본 연구는 이러한 연구 공백을 다루기 위해 범용 정적 분석 경고를 DT 구성요소 "
        "문맥과 연결하고, 중복 제거·문맥 검토·정책 기반 보조지수·환경 민감형 배포 제어로 "
        "이어지는 절차를 정의한다. 제4.3.1절에서는 Benchmark 기준 성능과 룰 진단을, "
        "제4.3.2절과 제4.4.1절에서는 공개 DT 판독과 구성요소 제거를, 제4.4.2절과 "
        "제4.4.3절에서는 민감도와 탐색적 프로파일 분석을 제시한다.",
    )
    replace(
        document,
        "검증용 취약 웹앱(8개):",
        "검증용 취약 웹앱(8개): OWASP Juice-Shop, OWASP NodeGoat, DVNA, WebGoat, "
        "Vulnerable-Flask-App, django.nV, OWASP Benchmark 및 dvpwa를 사용하였다. "
        "공식 테스트 케이스별 정답표가 포함된 OWASP Benchmark v1.2는 현재 룰셋의 기준 "
        "성능 평가에 사용하고, 나머지 7개는 일반 웹앱 모집단 비교가 아닌 탐색적 CWE "
        "프로파일 기술에만 활용하였다.",
    )
    replace(
        document,
        "검증 절차는 연구 질문에 따라 구성하였다.",
        "검증 절차는 세 가지 관점으로 구성하였다. 첫째, OWASP Benchmark v1.2와 정책이 "
        "중첩되는 6개 CWE의 TP·FP·FN 및 룰별 기여를 분석하였다. 둘째, 공개 DT 14개의 "
        "자동 탐지, 정확 위치 중복 제거 및 문맥 판독을 비교하였다. 셋째, 구성요소 제거와 "
        "보조지수 가중치 민감도를 평가하고 코드 계보 중복의 영향을 탐색적으로 기술하였다.",
    )

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
        "validated=formal_rq_removed:true tables:15 figure:1 equations:true "
        "algorithm_conditions:true experimental_data:true"
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
