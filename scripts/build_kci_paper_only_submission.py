#!/usr/bin/env python3
"""Create a paper-only KCI submission version.

This removes claims that a supplementary archive, public artifact release, or
DOI accompanies the manuscript. The single-reviewer limitation remains
explicit and unperformed inter-rater validation stays in future work.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_심사피드백_반영본.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_단독제출본.docx"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_and_set(
    paragraph,
    text: str,
    *,
    font: str = "Noto Sans CJK KR",
):
    for run in list(paragraph.runs):
        paragraph._p.remove(run._r)
    run = paragraph.add_run(text)
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
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
    paragraph = find_paragraph(document, prefix)
    clear_and_set(paragraph, text)
    return paragraph


def table_signature(table) -> tuple[str, ...]:
    return tuple(cell.text for row in table.rows for cell in row.cells)


def row_signature(row) -> tuple[str, ...]:
    return tuple(cell.text for cell in row.cells)


def validate(source: Path, destination: Path, source_hash: str) -> None:
    if sha256(source) != source_hash:
        raise AssertionError("source DOCX changed")
    with zipfile.ZipFile(destination) as archive:
        if bad_member := archive.testzip():
            raise AssertionError(f"corrupt DOCX member: {bad_member}")

    source_doc = Document(source)
    output_doc = Document(destination)
    if len(source_doc.tables) != 15 or len(output_doc.tables) != 15:
        raise AssertionError("table count changed")
    if Counter(map(table_signature, source_doc.tables[:14])) != Counter(
        map(table_signature, output_doc.tables[:14])
    ):
        raise AssertionError("main table data changed")
    if len(source_doc.tables[14].rows) != 7 or len(output_doc.tables[14].rows) != 5:
        raise AssertionError("appendix artifact rows were not reduced as intended")
    if [
        row_signature(row) for row in source_doc.tables[14].rows[:5]
    ] != [
        row_signature(row) for row in output_doc.tables[14].rows
    ]:
        raise AssertionError("available appendix artifact identifiers changed")
    if len(source_doc.inline_shapes) != 1 or len(output_doc.inline_shapes) != 1:
        raise AssertionError("process figure changed")
    if len(output_doc.sections) != 1:
        raise AssertionError("section count changed")

    all_text = "\n".join(paragraph.text for paragraph in output_doc.paragraphs)
    all_text += "\n" + "\n".join(
        cell.text
        for table in output_doc.tables
        for row in table.rows
        for cell in row.cells
    )
    for forbidden in (
        "보조자료 S1",
        "웹기반DT_KCI_재현성자료.zip",
        "analysis/",
        "experiment_output_sha256.csv",
        "https://github.com/CapstoneLab/CICD-Engine",
        "영구 보관 DOI",
        "재현 가능한 절차",
        "재현 가능한 실증 절차",
        "reproducible procedure",
    ):
        if forbidden in all_text:
            raise AssertionError(f"paper-only forbidden text remains: {forbidden}")

    for required in (
        "단일 판독자",
        "평가자 간 일치도와 Cohen’s κ를 보고하지 못했다",
        "별도 보조자료로 제공하지 않는다",
        "CWE-327은 TP=0, FN=130",
        "정밀도 0.533",
        "재현율 0.772",
        "F1-Score 0.630",
        "RQ1:",
        "RQ2:",
        "RQ3:",
        "Table 1. Mapping of DT components",
        "Table 7. Rule-level diagnostic analysis",
    ):
        if required not in all_text:
            raise AssertionError(f"required text missing: {required}")


def build(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    source_hash = sha256(source)
    document = Document(source)

    # Reproducibility is described at the level actually available in the paper.
    for paragraph in document.paragraphs:
        original = paragraph.text
        revised = (
            original.replace("재현 가능한 절차", "재현성을 고려한 절차")
            .replace("재현 가능한 실증 절차", "재현성을 고려한 실증 절차")
            .replace(
                "a reproducible procedure",
                "a traceable empirical procedure",
            )
        )
        if revised != original:
            clear_and_set(paragraph, revised)

    replace(
        document,
        "재현 가능한 경고–판정 연결 절차:",
        "추적 가능한 경고–판정 연결 절차: Gitleaks·Semgrep 경고를 16종 CWE 정책에 "
        "매핑하고, 정확 위치 중복 제거와 단일 판독자 문맥 판독을 거쳐 정책 기반 보조지수와 "
        "환경별 배포 게이트로 연결하였다(제3.1절 및 제3.2절).",
    )
    replace(
        document,
        "16개 항목은 Critical",
        "16개 항목은 Critical·High·Medium·Low 각 4종으로 구성되며, CWE를 공통 "
        "식별자로 사용해 스캐너 결과를 정책 등급으로 재분류한다. 표 2에는 정책 등급, 실제 "
        "관찰 스캐너와 대표 룰 ID를 제시하였다. 전체 룰 ID와 관찰 횟수는 분석 과정에서 "
        "별도로 기록했으나 본 원고에는 대표 룰만 수록한다. 이 정책은 DT 전용 CWE 집합이 "
        "아니며, 카탈로그 밖 탐지는 범위 외 결과로 유지한다.",
    )
    replace(
        document,
        "실험은 Ubuntu 26.04 LTS",
        "실험은 Ubuntu 26.04 LTS, Intel N95 4코어(최대 3.40 GHz), 메모리 7 GiB "
        "환경에서 수행하였다. Semgrep v1.157.0과 Gitleaks v8.21.2를 사용했으며, 공개 "
        "DT 14개는 development 환경과 16개 정책으로 실행하였다. Semgrep core 룰 번들 "
        "SHA-256은 574df0e5…a669e, Gitleaks 설정 SHA-256은 2ce9d818…430bb이다. "
        "명시적 제외 경로는 없고, 집계에서 엔진이 삽입한 .localci/workflow.yml만 제외하였다. "
        "테스트·예제·생성 코드는 자동 스캔에 포함하고 단일 판독자 검토에서 별도 문맥으로 "
        "분류하였다.",
    )
    replace(
        document,
        "표 7의 룰별 건수는",
        "표 7의 룰별 건수는 고유 테스트 케이스 기준이며, 하나의 테스트가 여러 룰에 "
        "탐지될 수 있어 표 6의 CWE 합계와 단순 합산되지 않는다. 이 집계는 고정한 Benchmark "
        "실행의 정규화 탐지 결과에서 룰 ID와 테스트 케이스 ID를 다시 대조하여 산출하였다.",
    )
    replace(
        document,
        "부록 A. 고정 커밋 및 재현성 산출물",
        "부록 A. 고정 커밋 및 재현성 조건",
    )
    replace(
        document,
        "표 A1은 분석한 공개 DT의 전체 커밋 SHA를 제시한다.",
        "표 A1은 분석한 공개 DT의 전체 커밋 SHA를 제시하고, 표 A2는 고정한 룰·설정·"
        "바이너리의 버전과 SHA-256 식별자를 제시한다. 본문의 실행 명령, 분석 범위 및 "
        "집계 기준과 함께 사용하면 동일한 공개 커밋을 대상으로 절차 수준의 반복 실험을 "
        "구성할 수 있다.",
    )
    replace(
        document,
        "보조자료 S1에는",
        "데이터 이용 가능성: 원시 Gitleaks 보고서와 코드 문맥 파일은 후보 자격증명 및 "
        "코드 스니펫을 포함할 수 있어 별도 보조자료로 제공하지 않는다. 분석 대상은 표 A1의 "
        "공개 저장소와 고정 커밋으로 식별하며, 논문에는 집계 결과, 판독 기준, 대표 룰 및 "
        "재현성 조건만 제시한다. 따라서 비트 단위 원시 산출물의 독립 검증에는 제한이 "
        "있으며, 이는 본 연구의 재현성 한계다.",
    )
    # The final two rows identify local files that are not part of a paper-only
    # submission. Keep the independently meaningful tool/configuration hashes.
    artifact_table = document.tables[14]
    for row in reversed(artifact_table.rows[5:]):
        artifact_table._tbl.remove(row._tr)

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
    print("validated=paper_only:true tables:15 figure:1 single_reviewer:explicit")


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
