#!/usr/bin/env python3
"""Align the current DT paper with the terminology of the earlier CWE paper.

The source manuscript remains untouched. The script preserves the title,
chapter structure, equations, algorithm conditions, experimental measurements,
and four-state results while defining how immediate/selective deployment
blocking maps to BLOCK, BLOCK_PENDING_APPROVAL, WARN, and PASS.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_단독제출본.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_용어체계_통합본.docx"
FONT = "Noto Sans CJK KR"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clear_and_set(paragraph: Paragraph, text: str) -> Paragraph:
    """Replace paragraph text while preserving its paragraph and first-run style."""
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


def find_paragraph(document: Document, prefix: str) -> Paragraph:
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


def replace(document: Document, prefix: str, text: str) -> Paragraph:
    return clear_and_set(find_paragraph(document, prefix), text)


def insert_after(
    paragraph: Paragraph,
    text: str,
    *,
    style: str = "Body Text",
) -> Paragraph:
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    inserted = Paragraph(new_p, paragraph._parent)
    inserted.style = style
    return clear_and_set(inserted, text)


def insert_before(
    paragraph: Paragraph,
    text: str,
    *,
    style: str = "Body Text",
) -> Paragraph:
    inserted = paragraph.insert_paragraph_before()
    inserted.style = style
    return clear_and_set(inserted, text)


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


def body_text(document: Document) -> str:
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
    if len(source_doc.tables) != 15 or len(output_doc.tables) != 15:
        raise AssertionError("table count changed")
    if len(source_doc.inline_shapes) != 1 or len(output_doc.inline_shapes) != 1:
        raise AssertionError("figure count changed")
    if len(source_doc.sections) != 1 or len(output_doc.sections) != 1:
        raise AssertionError("section count changed")

    # Tables containing experimental measurements must retain every data row.
    fully_unchanged_tables = (3, 4, 5, 6, 8, 9, 10, 12, 13, 14)
    for index in fully_unchanged_tables:
        if table_signature(source_doc.tables[index]) != table_signature(
            output_doc.tables[index]
        ):
            raise AssertionError(f"table {index + 1} unexpectedly changed")
    for index in (1, 7, 11):
        source_rows = table_signature(source_doc.tables[index])[1:]
        output_rows = table_signature(output_doc.tables[index])[1:]
        if source_rows != output_rows:
            raise AssertionError(f"table {index + 1} data rows changed")

    expected_table3 = (
        ("등급", "건당 감점", "감점 상한", "배포 제어 유형", "실행 상태"),
        ("Critical", "20", "없음; 보조지수 0~40", "즉시 배포 차단", "BLOCK"),
        (
            "High",
            "5",
            "19",
            "즉시 배포 차단",
            "BLOCK_PENDING_APPROVAL",
        ),
        (
            "Medium",
            "1",
            "4",
            "선택적 배포 차단",
            "환경에 따라 BLOCK_PENDING_APPROVAL 또는 WARN",
        ),
        (
            "Low",
            "0.2",
            "0.9",
            "선택적 배포 차단",
            "현재 정책에서는 PASS, 보조지수에만 반영",
        ),
    )
    if table_signature(output_doc.tables[2]) != expected_table3:
        raise AssertionError("Table 3 terminology mapping is incorrect")

    text = body_text(output_doc)
    for required in (
        "3.2.2 탐지 결과 정규화 및 취약점 의사결정 단계",
        "보안 취약점 탐지 단계(Security Scan Step)",
        "취약점 의사결정 단계(Vulnerability Decision-Making Step)",
        "CWE 기반 보안 등급",
        "즉시 배포 차단",
        "선택적 배포 차단",
        "자동 취약점 의사결정 결과",
        "문맥 판독 반영 취약점 의사결정 결과",
        "정책 적용 대상 탐지 항목",
        "정책 외 탐지 항목",
        "Algorithm 1. Environment-Sensitive Vulnerability Decision-Making and Deployment Control",
        "BLOCK은 승인으로 해제할 수 없는 즉시 배포 차단",
        "WARN은 선택적 배포 차단 조건이 현재 배포 환경에서 활성화되지 않아",
        "PASS는 활성화된 배포 차단 조건이 없는 상태",
        "Low 등급은 선택적 배포 차단이 가능한 CWE 기반 보안 등급으로 분류한다.",
        "자동 보조지수/배포 제어 실행 상태",
        "검토 반영 보조지수/배포 제어 실행 상태",
        "정밀도 0.533",
        "재현율 0.772",
        "F1-Score 0.630",
        "TP 728, FP 639, FN 215",
        "PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개",
    ):
        if required not in text:
            raise AssertionError(f"required text missing: {required}")

    for forbidden in (
        "3.2.2 탐지 결과 정규화 및 보안성 판정 단계",
        "자동 예비 게이트",
        "검토 반영 게이트",
        "자동 지수/판정",
        "검토 지수/판정",
        "게이트 판정",
        "환경 민감형 배포 판정.",
        "범위 내 레코드",
        "범위 외 결과",
        "선행연구",
    ):
        if forbidden in text:
            raise AssertionError(f"old terminology remains: {forbidden}")

    title = output_doc.paragraphs[0].text
    if title != source_doc.paragraphs[0].text:
        raise AssertionError("paper title changed")
    for heading in (
        "1. 서론",
        "2. 관련 연구 및 문제 정의",
        "3. 웹 기반 디지털트윈 코드베이스의 정적 보안 측정 절차",
        "4. 웹 기반 디지털트윈의 보안성 측정 사례 및 검증",
        "5. 결론 및 향후 연구",
    ):
        if heading not in text:
            raise AssertionError(f"major heading missing: {heading}")

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

    replace(
        document,
        "웹 기반 DT는 3D 시각화",
        "웹 기반 DT는 3D 시각화, 실시간 센서 동기화 및 원격 제어 기능을 제공하지만, "
        "웹 애플리케이션 계층의 정적 분석 경고를 DT 구성요소와 배포 문맥에서 해석하는 "
        "실증 연구는 제한적이다. 본 연구는 범용 정적 분석기를 DT 전용 탐지기로 제안하는 "
        "대신, Gitleaks와 Semgrep의 경고를 16종 CWE 보안 정책 카탈로그에 따라 재분류하고, "
        "정확 위치 중복 제거, 단일 판독자 문맥 검토, 정책 기반 보조지수 및 즉시·선택적 "
        "배포 차단을 구체화한 환경 민감형 배포 게이트로 연결하는 재현성을 고려한 절차를 "
        "제시한다. OWASP Benchmark v1.2와 공개 DT 14개 고정 커밋을 대상으로 기준 성능 "
        "평가, 수동 판독, 구성요소 제거 및 가중치 민감도 분석을 수행하였다. 정책 중첩 "
        "6개 CWE에서 현재 룰셋은 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 보였고, "
        "CWE-327의 130개 실제 취약 사례는 탐지하지 못하였다. 공개 DT에서 자동 분류된 "
        "274건 가운데 Critical·High 77건과 Medium 30건을 검토한 결과, 중복을 제외한 "
        "Critical·High 72개 위치 중 31개가 확인된 위험 패턴으로 분류되었다. 단일 판독자 "
        "문맥 검토를 반영한 취약점 의사결정 결과, 즉시 배포 차단 상태는 BLOCK 8개와 "
        "BLOCK_PENDING_APPROVAL 1개였으며, 선택적 배포 차단이 활성화되지 않은 Medium "
        "탐지 저장소는 WARN 2개, 활성화된 차단 조건이 없는 저장소는 PASS 3개로 산출되었다.",
    )
    replace(
        document,
        "Web-based digital twins provide",
        "Web-based digital twins provide 3D visualization, real-time sensor synchronization, "
        "and remote control, but empirical studies that interpret static-analysis alerts in DT "
        "component and deployment contexts remain limited. This study does not present "
        "general-purpose analyzers as DT-specific detectors. Instead, it connects Gitleaks and "
        "Semgrep alerts to a 16-CWE security policy catalogue, exact-location deduplication, "
        "single-reviewer contextual adjudication, an auxiliary policy index, and "
        "environment-sensitive deployment control that operationalizes immediate and selective "
        "deployment blocking. OWASP Benchmark v1.2 and 14 pinned public DT repositories were "
        "evaluated through baseline performance, manual adjudication, ablation, and "
        "weight-sensitivity analyses. On six policy-overlapping CWEs, the current ruleset achieved "
        "0.533 precision, 0.772 recall, and an F1-score of 0.630, while all 130 true CWE-327 "
        "cases remained undetected. Of 77 automated Critical/High records in the DT repositories, "
        "72 unique locations remained after deduplication and 31 were classified as confirmed "
        "risky patterns. After single-reviewer contextual adjudication, the vulnerability "
        "decision-making results yielded eight BLOCK and one BLOCK_PENDING_APPROVAL as immediate "
        "deployment-blocking states, two WARN for repositories where selective blocking for "
        "Medium findings was inactive, and three PASS with no active blocking condition.",
    )
    replace(
        document,
        "이처럼 웹 기반 DT의 보안 취약점은",
        "이처럼 웹 기반 DT의 보안 취약점은 물리 시스템의 안정성과 안전에 영향을 줄 수 "
        "있음에도 [4], 기존 DT 보안 연구는 주로 CPS 및 OT(Operational Technology) "
        "관점에서 네트워크 공격, 침입 탐지 및 보안 아키텍처를 다루어 왔다. 웹 애플리케이션 "
        "계층의 소스 코드를 대상으로 한 취약점 분석과 정량적 보안성 측정은 상대적으로 "
        "충분히 다루어지지 않았다. 관련 연구는 제2.1절에서 구체적으로 검토한다.",
    )
    replace(
        document,
        "따라서 웹 기반 DT 소프트웨어에서는",
        "따라서 웹 기반 DT 소프트웨어에서는 소스 코드의 잠재적 보안 경고를 체계적으로 "
        "탐지하고, DT 구성요소와 배포 문맥을 함께 기록하여 검토 우선순위와 배포 제어 "
        "판정으로 연결할 절차가 필요하다. 이때 정량값은 절대적인 보안 수준이나 실제 악용 "
        "가능성을 나타내는 점수가 아니라, 선택한 정책 범위의 경고 분포를 요약하는 "
        "보조지수로 한정되어야 한다.",
    )
    replace(
        document,
        "본 연구는 범용 정적 분석 도구가 생성한 경고를 웹 기반 DT 코드베이스의",
        "본 연구는 범용 정적 분석 도구가 생성한 경고를 웹 기반 DT 코드베이스의 "
        "구성요소와 배포 문맥에서 판독하고, 정확 위치 중복 제거, 정책 기반 보조지수와 "
        "즉시·선택적 배포 차단을 구체화한 환경별 DevSecOps 배포 제어로 연결하는 "
        "재현성을 고려한 실증 절차를 제시한다. 자동 경고는 확정 취약점이 아니므로 자동 "
        "취약점 의사결정 결과와 단일 판독자 문맥 판독 반영 취약점 의사결정 결과를 "
        "구분한다. Benchmark의 정책 중첩 6개 CWE에서 현재 룰셋의 기준 성능과 미탐 영역을 "
        "확인하고, 공개 DT 14개에 적용하여 경고 처리 단계가 배포 제어 실행 상태에 미치는 "
        "변화를 분석하였다.",
    )
    replace(
        document,
        "추적 가능한 경고–판정 연결 절차:",
        "추적 가능한 경고–취약점 의사결정 연결 절차: Gitleaks·Semgrep 경고를 16종 "
        "CWE 보안 정책 카탈로그에 매핑하고, 정확 위치 중복 제거와 단일 판독자 문맥 "
        "판독을 거쳐 정책 기반 보조지수와 환경별 배포 제어로 연결하였다(제3.1절 및 "
        "제3.2절).",
    )
    replace(
        document,
        "RQ2:",
        "RQ2: 정확 위치 중복 제거와 단일 판독자 문맥 판독은 탐지량과 배포 제어 실행 "
        "상태를 어떻게 변화시키는가?",
    )
    replace(
        document,
        "RQ3:",
        "RQ3: 정책 기반 보조지수와 환경 민감형 배포 제어는 구성요소 제거, 가중치 변화 "
        "및 코드 계보 중복에 대해 어느 정도 안정적인가?",
    )
    replace(
        document,
        "선행연구 분석을 통해",
        "관련 연구 분석을 통해 웹 기반 DT 소프트웨어의 보안성 측정과 관련된 다음 세 가지 "
        "연구 공백을 도출하였다.",
    )
    replace(
        document,
        "둘째, 탐지 결과를 DT 소프트웨어의",
        "둘째, 보안 탐지 항목을 DT 소프트웨어의 검토 우선순위와 배포 가능 여부로 "
        "변환하는 일관된 절차가 미흡하다. 기존 SAST 도구는 개별 경고의 유형과 심각도를 "
        "제공하지만, 범용 경고를 DT 구성요소 및 배포 환경과 함께 기록하고 정책 범위의 "
        "보조지수와 배포 제어 판정으로 변환하는 방법은 충분히 제시되지 않았다. 이로 인해 "
        "경고량을 절대 보안 수준으로 오해하거나, 경고를 검토 없이 DevSecOps 차단 조건으로 "
        "사용하는 문제가 발생할 수 있다.",
    )
    replace(
        document,
        "본 연구는 이러한 연구 공백을",
        "본 연구는 이러한 연구 공백을 다루기 위해 범용 정적 분석 경고를 DT 구성요소 "
        "문맥과 연결하고, 중복 제거·단일 판독자 검토·정책 기반 보조지수·환경 민감형 배포 "
        "제어로 이어지는 절차를 정의한다. RQ1은 제4.3.1절의 Benchmark 기준 성능과 룰 "
        "진단으로, RQ2는 제4.3.2절 및 제4.4.1절의 공개 DT 판독과 구성요소 제거로, RQ3은 "
        "제4.4.2절 및 제4.4.3절의 민감도와 탐색적 프로파일 분석으로 각각 답한다.",
    )

    overview = replace(
        document,
        "본 장에서는 범용 정적 분석 도구가 생성한 경고를",
        "본 장에서는 범용 정적 분석 도구가 생성한 정적 분석 경고를 웹 기반 DT "
        "코드베이스의 구성요소와 배포 문맥에서 정리하고, 정책 기반 보조지수와 배포 제어 "
        "판정으로 연결하는 절차를 정의한다. 탐지 코어인 Gitleaks와 Semgrep은 일반 웹 "
        "애플리케이션에도 적용 가능하며, 본 연구의 DT 맥락은 구성요소–위협–정책 매핑과 "
        "수동 판독의 배포 관련성 해석에서 부여된다. 각 단계의 산출물은 JSON 형식으로 "
        "전달되어 CI/CD 파이프라인에서 처리된다.",
    )
    definition_1 = insert_after(
        overview,
        "본 연구에서 취약점 의사결정은 정적 분석 경고를 CWE 식별자에 따라 정규화하고, "
        "CWE 보안 정책 카탈로그를 기준으로 Critical, High, Medium 및 Low의 CWE 기반 "
        "보안 등급으로 재분류한 후 배포 제어 여부를 결정하는 과정이다. Critical과 High는 "
        "즉시 배포 차단 대상으로, Medium과 Low는 선택적 배포 차단 대상으로 분류한다. "
        "환경 민감형 배포 게이트는 이러한 두 배포 제어 유형을 BLOCK, "
        "BLOCK_PENDING_APPROVAL, WARN 및 PASS의 네 가지 배포 제어 실행 상태로 "
        "구체화한다.",
        style="Body Text",
    )
    insert_after(
        definition_1,
        "본 연구에서 적용한 정책 설정에서는 Medium의 선택적 차단 여부를 배포 환경에 "
        "따라 결정하며, Low의 선택적 차단은 활성화하지 않고 정책 기반 보조지수에만 "
        "반영한다.",
        style="Body Text",
    )
    replace(
        document,
        "전체 프로세스는 그림 1과 같다.",
        "전체 프로세스는 그림 1과 같다. 고정 커밋에서 Gitleaks와 Semgrep을 순차 실행한 "
        "뒤 16종 CWE 보안 정책 카탈로그를 적용하고, 동일 저장소·CWE·파일·라인의 중복 "
        "레코드를 하나의 위치로 통합한다. 자동 결과는 자동 취약점 의사결정 결과의 배포 "
        "제어 실행 상태를 생성하며, 수동 검증에서 확인된 패턴, 문맥 제한 패턴, 오탐 및 "
        "중복으로 분류한 뒤 Critical·High 건수를 갱신하여 문맥 판독 반영 취약점 "
        "의사결정 결과의 배포 제어 실행 상태를 산출한다. Medium·Low는 전체 자동 결과를 "
        "유지하되 표본 판독으로 해석 범위를 평가한다.",
    )
    replace(
        document,
        "Fig. 1.",
        "Fig. 1. Security scan, contextual adjudication, and four-state deployment-control process",
    )
    replace(
        document,
        "보안 정책은 OWASP",
        "CWE 보안 정책 카탈로그는 OWASP Top 10:2021 [17]과 CVSS v3.1 [18]의 질적 "
        "심각도 용어를 참고하되, 표 2의 CWE 기반 보안 등급과 감점은 본 연구의 운영 "
        "정책으로 정의하였다. 20·5·1·0.2의 감점은 CVSS에서 도출한 경험적 위험값이 아니며, "
        "정책 기반 보조지수의 가중치 변화는 제4.4.2절에서 민감도만 평가한다.",
    )
    replace(
        document,
        "Table 2.",
        "Table 2. CWE-based security levels, scanners, observed rule IDs, and assignment basis",
    )
    replace(
        document,
        "16개 항목은 Critical",
        "16개 항목은 Critical·High·Medium·Low 각 4종으로 구성되며, CWE를 공통 "
        "식별자로 사용해 스캐너 결과를 CWE 기반 보안 등급으로 재분류한다. 표 2에는 CWE "
        "기반 보안 등급, 실제 관찰 스캐너와 대표 룰 ID를 제시하였다. 전체 룰 ID와 관찰 "
        "횟수는 분석 과정에서 별도로 기록했으나 본 원고에는 대표 룰만 수록한다. 이 "
        "카탈로그는 DT 전용 CWE 집합이 아니며, CWE 보안 정책 카탈로그 밖의 탐지는 정책 "
        "외 탐지 항목으로 유지한다.",
    )

    replace(
        document,
        "탐지 단계는 일반 소프트웨어에도",
        "보안 취약점 탐지 단계(Security Scan Step)는 Gitleaks 기반 경량 보안 스캔과 "
        "Semgrep 기반 심층 정적 보안 스캔으로 구성된다. 이 단계는 일반 소프트웨어에도 "
        "적용 가능하며, DT 구성요소 문맥과 배포 관련성은 탐지 이후의 정규화·판독 단계에서 "
        "기록한다.",
    )
    replace(
        document,
        "두 스캐너의 결과는",
        "두 스캐너의 결과는 rule_id, CWE, file_path, line, scanner, "
        "policy_severity(CWE 기반 보안 등급) 및 in_scope(정책 적용 대상 여부) 필드로 "
        "통합한다. 동일 저장소·CWE·파일·라인을 정확 위치 키로 사용해 교차 스캐너·교차 "
        "룰 중복을 제거한다. 수동 판독은 ‘확인된 위험 패턴’, ‘문맥 제한 패턴’, ‘오탐’, "
        "‘중복’의 네 범주와 production, CI/build, test, documentation/example, "
        "generated/tooling의 배포 관련성을 함께 기록한다. 확인된 위험 패턴은 위험한 "
        "구문이나 자격증명 내장이 실제로 존재한다는 뜻이며, 원격 악용 가능성이나 "
        "자격증명의 현재 유효성을 자동으로 의미하지 않는다.",
    )
    decision_heading = replace(
        document,
        "3.2.2 탐지 결과 정규화 및 보안성 판정 단계",
        "3.2.2 탐지 결과 정규화 및 취약점 의사결정 단계",
    )
    insert_after(
        decision_heading,
        "취약점 의사결정 단계(Vulnerability Decision-Making Step)는 보안 취약점 탐지 "
        "단계에서 수집된 탐지 항목을 CWE 기준으로 정규화하고, CWE 보안 정책 카탈로그에 "
        "따라 CWE 기반 보안 등급을 재분류한 후 최종 배포 제어 실행 상태를 결정한다. 본 "
        "연구에서는 정확 위치 중복 제거와 문맥 판독을 추가하여 배포 제어에 반영되는 탐지 "
        "항목을 조정하고, 정책 기반 보조지수와 환경 민감형 배포 게이트를 산출한다.",
        style="First Paragraph",
    )
    replace(
        document,
        "정확 위치 중복 제거 후 범위 내 레코드의",
        "정책 기반 보조지수는 취약점 의사결정에 따른 배포 차단 여부를 결정하는 임계값이 "
        "아니라, CWE 기반 보안 등급별 탐지 분포를 요약하는 부가 지표이다. 정확 위치 중복 "
        "제거 후 정책 적용 대상 레코드의 등급별 분포로 100점 만점 형식의 정책 기반 "
        "보조지수 S를 산출한다. 이 값은 실제 공격 성공 확률, 절대 보안 수준 또는 전문가 "
        "위험 순위를 추정하지 않으며, 선택한 16개 정책의 경고 분포를 운영상 비교하기 위한 "
        "요약량이다. 배포 제어 판정은 본 절에서 후술하는 계층형 규칙이 독립적으로 결정한다.",
    )
    replace(
        document,
        "여기서 C_C",
        "여기서 C_C, C_H, C_M, C_L은 각각 Critical, High, Medium, Low의 CWE 기반 "
        "보안 등급에 해당하는 정책 적용 대상 탐지 항목 수이며 D_H, D_M, D_L은 등급별 "
        "상한이 적용된 감점 합계이다.",
    )
    replace(
        document,
        "이 설계에서 Low 전체 감점은",
        "이 설계에서 Low 전체 감점은 Medium 한 건보다, Medium 전체 감점은 High 한 "
        "건보다, High 전체 감점은 Critical 한 건보다 작다. 표 3과 같이 보조지수와 배포 "
        "제어 실행 상태를 분리함으로써 지수는 정책 경고 구성의 비교에만 사용하고, 상위 "
        "심각도 탐지는 별도의 승인·차단 절차로 연결한다.",
    )
    replace(
        document,
        "Table 3.",
        "Table 3. Severity weights, deduction caps, deployment-control types, and execution states",
    )
    replace(
        document,
        "정책 기반 보조지수는 원본",
        "정책 기반 보조지수는 원본 레코드·중복 제거 건수·수동 판독 결과와 함께 제공한다. "
        "따라서 동일한 지수라도 경고 구성과 배포 문맥이 다른 경우를 구분할 수 있고, 배포 "
        "제어 실행 상태의 근거를 파일 위치까지 추적할 수 있다.",
    )
    replace(
        document,
        "환경 민감형 배포 판정.",
        "환경 민감형 배포 제어.",
    )
    replace(
        document,
        "배포 판정은 정책 기반 보조지수의",
        "배포 제어 판정은 정책 기반 보조지수의 단일 임계값이 아니라 CWE 기반 보안 등급과 "
        "배포 환경의 조합으로 수행한다. 표 4는 production, staging, development 및 "
        "feature 환경에서 Critical·High·Medium 탐지를 처리하는 규칙을 나타낸다.",
    )
    replace(
        document,
        "Table 4.",
        "Table 4. Environment-sensitive deployment-control execution-state rules",
    )
    algorithm = find_paragraph(document, "Algorithm 1.")
    insert_before(
        algorithm,
        "Critical과 High는 환경과 관계없이 탐지 즉시 파이프라인을 중단하므로 즉시 배포 "
        "차단에 해당한다. Medium은 배포 환경에 따라 차단 여부가 결정되므로 선택적 배포 "
        "차단에 해당한다. Low는 선택적 배포 차단 범주에 포함되지만, 본 연구에서 적용한 "
        "정책에서는 차단 조건을 활성화하지 않아 보조지수에만 반영한다.",
    )
    algorithm_suffix = algorithm.text.split("\n", 1)[1]
    clear_and_set(
        algorithm,
        "Algorithm 1. Environment-Sensitive Vulnerability Decision-Making and Deployment Control\n"
        + algorithm_suffix,
    )
    replace(
        document,
        "게이트는 우선순위 순으로 동작한다.",
        "취약점 의사결정은 우선순위 순으로 동작한다. 수동 판독이 완료되기 전에는 자동 "
        "정책 건수로 자동 취약점 의사결정 결과를 생성하고, 완료 후에는 중복·오탐을 제외한 "
        "확인 건수로 문맥 판독 반영 취약점 의사결정 결과를 갱신한다. 알고리즘에서 BLOCK과 "
        "BLOCK_PENDING_APPROVAL은 모두 탐지 즉시 후속 빌드·배포를 중단한다. BLOCK은 "
        "승인으로 해제할 수 없는 즉시 배포 차단 상태이고, BLOCK_PENDING_APPROVAL은 "
        "명시적 승인 후 재개할 수 있는 즉시 또는 선택적 배포 차단 상태이다.",
    )
    replace(
        document,
        "환경 규칙은 상위 심각도의 처리를",
        "Medium에 대한 BLOCK_PENDING_APPROVAL과 WARN의 구분은 환경별 선택적 배포 "
        "차단 정책에 따른다. Low 등급은 선택적 배포 차단이 가능한 CWE 기반 보안 등급으로 "
        "분류한다. 다만 본 연구에서 적용한 환경별 배포 정책에서는 Low의 선택적 차단 "
        "조건을 활성화하지 않았으므로, Low 탐지는 정책 기반 보조지수에만 반영하고 배포 "
        "제어 실행 상태는 PASS로 처리한다. WARN은 선택적 배포 차단 조건이 현재 배포 "
        "환경에서 활성화되지 않아 배포를 계속하되 경고를 제공하는 상태이며, PASS는 "
        "활성화된 배포 차단 조건이 없는 상태다.",
    )
    replace(
        document,
        "예를 들어 High 1건이",
        "예를 들어 High 1건이 탐지되면 정책 기반 보조지수는 95일 수 있으나 배포 제어 "
        "실행 상태는 BLOCK_PENDING_APPROVAL이므로 승인 전 배포가 중단된다. 이 예시는 "
        "보조지수가 배포 허용 임계값이나 절대적인 보안 수준이 아님을 보여준다.",
    )

    replace(
        document,
        "저장소당 프로그래밍 언어 비공백 LOC는",
        "저장소당 프로그래밍 언어 비공백 LOC는 Semgrep이 실제 스캔한 파일을 기준으로 "
        "계산했으며, JSON·YAML·데이터 파일은 코드 LOC에서 제외하였다. 14개 DT의 코드 "
        "LOC와 정책 적용 대상 자동 탐지 항목 수의 Spearman 상관은 ρ=0.811로 나타나 "
        "저장소 규모의 영향을 확인하였다. 이에 제4.4.3절의 집단 비교는 건수 대신 저장소 "
        "보유 여부를 사용하고, 관련 저장소를 10개 코드 계보로 축약한 민감도 분석을 "
        "추가하였다.",
    )
    replace(
        document,
        "기준 성능 평가는 OWASP Benchmark",
        "기준 성능 평가는 OWASP Benchmark v1.2 정답표와 16종 정책이 공통으로 포함하는 "
        "CWE-22, CWE-78, CWE-79, CWE-89, CWE-327 및 CWE-614를 대상으로 수행하였다. "
        "테스트 케이스 ID와 CWE가 모두 일치하는 정책 적용 대상 탐지 항목을 TP·FP·FN으로 "
        "집계하였다. 표 6의 마이크로 합계는 TP 728, FP 639, FN 215이며 정밀도 0.533, "
        "재현율 0.772, F1-Score 0.630이다. 이는 우수성을 주장하는 비교 성능이 아니라 "
        "현재 고정 룰셋의 기준 성능이다.",
    )
    replace(
        document,
        "14개 공개 DT 웹앱은",
        "14개 공개 DT 웹앱은 표 5의 전체 커밋 SHA를 고정하고 development 환경에서 "
        "재검사하였다. 모든 저장소에서 두 스캐너가 완료되고 배포 제어 실행 상태 JSON이 "
        "생성되었으며, 저장소당 전체 분석 시간 중앙값은 30.5초였다. 자동 결과, 정확 위치 "
        "중복 제거 결과 및 Critical·High 단일 판독자 문맥 판독 반영 결과를 표 8에 함께 "
        "제시한다.",
    )
    replace(
        document,
        "원시 탐지 482건 가운데",
        "원시 탐지 482건 가운데 274건이 CWE 보안 정책 카탈로그의 정책 적용 대상 탐지 "
        "항목으로 분류되고 208건은 정책 외 탐지 항목으로 분리되었다. 자동 CWE 기반 보안 "
        "등급 분포는 Critical 69건, High 8건, Medium 197건이며, 정확 위치 중복 제거 후 "
        "220개 위치로 축약되었다. 자동 취약점 의사결정 결과의 배포 제어 실행 상태는 PASS "
        "3개, WARN 1개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 9개였다. 단일 판독자가 "
        "Critical·High의 확인 패턴만 유지하고 Medium·Low는 중복 제거 자동 결과를 유지한 "
        "문맥 판독 반영 취약점 의사결정 결과의 배포 제어 실행 상태는 PASS 3개, WARN 2개, "
        "BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개로 변경되었다.",
    )
    replace(
        document,
        "SecuPipeline을 development 환경으로",
        "SecuPipeline을 development 환경으로 실행한 결과, 정책 기반 보조지수 94/100과 "
        "배포 제어 실행 상태 BLOCK_PENDING_APPROVAL이 도출되었다. High 등급 CWE-319와 "
        "Medium 등급 CWE-79가 정책 적용 대상 탐지 항목으로 분류되었으며, 표 10은 각 "
        "탐지의 정책 항목, 파일 및 코드 위치를 나타낸다.",
    )
    replace(
        document,
        "Table 10.",
        "Table 10. Policy-applied findings in the hydrogen-powered ship digital twin",
    )
    replace(
        document,
        "정책 카탈로그 밖에서는",
        "CWE 보안 정책 카탈로그 밖에서는 Subresource Integrity 누락(CWE-353), "
        "정규표현식 DoS(CWE-1333), runAsNonRoot 설정(CWE-250), Kubernetes 권한 "
        "설정(CWE-732) 및 CSRF 미들웨어(CWE-352)와 관련된 정책 외 탐지 항목 5건이 "
        "식별되었다. 이 결과는 정책 적용 대상 탐지 항목의 취약점 의사결정 결과와 함께 "
        "인프라·런타임 보안 검토 목록으로 보존하였다.",
    )
    replace(
        document,
        "범위 내 2건은",
        "정책 적용 대상 탐지 항목 2건은 웹 기반 DT의 실시간 통신과 동적 시각화 경계에서 "
        "확인된 보안 검토 지점이다.",
    )
    replace(
        document,
        "각 구성요소가 탐지량과 게이트에",
        "각 구성요소가 탐지량과 배포 제어 실행 상태에 미치는 영향을 확인하기 위해 Semgrep "
        "단독, 두 스캐너 전체, 16종 정책 적용, 정확 위치 중복 제거 및 Critical·High 수동 "
        "판독 반영 구성을 순차 비교하였다.",
    )
    replace(
        document,
        "Table 11.",
        "Table 11. Ablation results for scanner combination, policy filtering, deduplication, "
        "and deployment-control execution states after single-reviewer adjudication",
    )
    replace(
        document,
        "Gitleaks 결합은 Semgrep 단독 대비",
        "Gitleaks 결합은 Semgrep 단독 대비 Hardcoded Secret을 포함하여 자동 BLOCK을 "
        "5개에서 9개로 확대하였다. 16종 정책 필터는 전체 482건을 274건으로 축약하면서 "
        "PASS를 1개에서 3개로 조정하였다. 정확 위치 중복 제거는 54건을 줄였으나 배포 "
        "제어 실행 상태 분포는 유지되었다. 단일 판독자 문맥 검토는 실행 상태 한 건을 "
        "변경하였다. 이 결과는 자동 경고를 실제 악용 가능성이 확인된 취약점으로 간주하지 "
        "않고 검토 단계를 분리할 필요성을 보여준다.",
    )
    replace(
        document,
        "세 계층형 가중치 조합에서",
        "세 계층형 가중치 조합에서 저장소 순위는 거의 동일했으나(ρ=0.999), 상한 지수와 "
        "단순 건수의 상관은 0.776이었다. 이는 선택한 범위의 가중치 변화에 대한 순위 "
        "안정성을 보여줄 뿐, 20·5·1·0.2가 전문가 판단이나 실제 배포 위험을 정확히 "
        "반영한다는 타당성 증거는 아니다. 배포 제어 실행 상태는 보조지수와 독립적으로 "
        "CWE 기반 보안 등급의 존재 여부를 사용하므로 모든 가중치에서 동일했다.",
    )
    replace(
        document,
        "본 연구는 범용 정적 분석기를 DT 전용 탐지기로",
        "본 연구는 웹 기반 DT 코드베이스의 정적 분석 경고를 CWE 기준으로 정규화하고 "
        "CWE 기반 보안 등급으로 재분류한 후, 즉시·선택적 배포 차단을 구체화한 환경 민감형 "
        "배포 제어 실행 상태로 연결하였다. Benchmark의 정책 중첩 6개 CWE에서 현재 룰셋의 "
        "기준 성능은 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630이었으며, CWE-327의 "
        "미탐 영역을 확인하였다. 공개 DT에서는 자동 정책 적용 대상 탐지 항목 274건이 "
        "정확 위치 220개로 축약되었고, Critical·High 고유 72개 위치 중 31개가 확인된 "
        "위험 패턴으로 분류되었다. 문맥 판독 반영 취약점 의사결정 결과, 즉시 배포 차단 "
        "상태인 BLOCK은 8개, 승인 후 재개할 수 있는 즉시 배포 차단 상태인 "
        "BLOCK_PENDING_APPROVAL은 1개, 선택적 배포 차단이 활성화되지 않은 경고 상태인 "
        "WARN은 2개, 활성화된 차단 조건이 없는 PASS는 3개였다. 가중치 민감도 ρ=0.999는 "
        "순위 안정성만을 의미하며 가중치의 경험적 타당성으로 해석하지 않는다.",
    )

    # Table terminology. Data and experimental values are not changed.
    set_cell(document.tables[0].cell(4, 4), "CWE 기반 보안 등급과 문맥 판독에 따름")
    set_cell(document.tables[1].cell(0, 2), "CWE 기반 보안 등급")

    table3 = document.tables[2]
    table3_values = (
        ("등급", "건당 감점", "감점 상한", "배포 제어 유형", "실행 상태"),
        ("Critical", "20", "없음; 보조지수 0~40", "즉시 배포 차단", "BLOCK"),
        (
            "High",
            "5",
            "19",
            "즉시 배포 차단",
            "BLOCK_PENDING_APPROVAL",
        ),
        (
            "Medium",
            "1",
            "4",
            "선택적 배포 차단",
            "환경에 따라 BLOCK_PENDING_APPROVAL 또는 WARN",
        ),
        (
            "Low",
            "0.2",
            "0.9",
            "선택적 배포 차단",
            "현재 정책에서는 PASS, 보조지수에만 반영",
        ),
    )
    for row, values in zip(table3.rows, table3_values, strict=True):
        for cell, value in zip(row.cells, values, strict=True):
            set_cell(cell, value)

    set_cell(
        document.tables[7].cell(0, 5),
        "자동 보조지수/배포 제어 실행 상태",
    )
    set_cell(
        document.tables[7].cell(0, 7),
        "검토 반영 보조지수/배포 제어 실행 상태",
    )
    set_cell(document.tables[11].cell(0, 3), "배포 제어 실행 상태 영향")

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
        "validated=terminology:true title:true structure:true equations:true "
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
