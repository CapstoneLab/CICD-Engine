#!/usr/bin/env python3
"""Apply reviewer-oriented framing and evidence clarifications to the KCI DOCX.

The script starts from the reorganized manuscript, preserves all existing
experimental tables and figures, and adds two evidence-backed tables:

1. DT component/threat/policy coverage mapping.
2. Rule-level diagnostic analysis of OWASP Benchmark TP/FP contributions.

No second-reviewer result, expert calibration, or unperformed experiment is
introduced.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sys
import tempfile
import zipfile
from collections import Counter
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_실험검증_목차재구성본.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_심사피드백_반영본.docx"
RULE_ANALYSIS = ROOT / "analysis/benchmark_rule_error_analysis.csv"


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
    bold: bool = False,
    size: float | None = None,
    font: str = "Noto Sans CJK KR",
):
    for run in list(paragraph.runs):
        paragraph._p.remove(run._r)
    run = paragraph.add_run(text)
    run.bold = bold
    if size is not None:
        run.font.size = Pt(size)
    run.font.name = font
    run._element.rPr.rFonts.set(qn("w:eastAsia"), font)
    return paragraph


def find_paragraph(document: Document, prefix: str):
    matches = [paragraph for paragraph in document.paragraphs if paragraph.text.startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(f"paragraph {prefix!r}: expected 1, found {len(matches)}")
    return matches[0]


def replace(document: Document, prefix: str, text: str):
    paragraph = find_paragraph(document, prefix)
    clear_and_set(paragraph, text)
    return paragraph


def insert_paragraph_after(document: Document, anchor, text: str, style: str | None = None):
    paragraph = document.add_paragraph()
    if style:
        paragraph.style = style
    clear_and_set(paragraph, text)
    anchor._element.addnext(paragraph._p)
    return paragraph


def insert_paragraph_after_element(
    document: Document,
    anchor_element,
    text: str,
    style: str | None = None,
):
    paragraph = document.add_paragraph()
    if style:
        paragraph.style = style
    clear_and_set(paragraph, text)
    anchor_element.addnext(paragraph._p)
    return paragraph


def repeat_header(table) -> None:
    tr_pr = table.rows[0]._tr.get_or_add_trPr()
    existing = tr_pr.find(qn("w:tblHeader"))
    if existing is None:
        existing = OxmlElement("w:tblHeader")
        tr_pr.append(existing)
    existing.set(qn("w:val"), "true")


def shade_header(table, color: str = "D9EAF7") -> None:
    for cell in table.rows[0].cells:
        tc_pr = cell._tc.get_or_add_tcPr()
        shd = tc_pr.find(qn("w:shd"))
        if shd is None:
            shd = OxmlElement("w:shd")
            tc_pr.append(shd)
        shd.set(qn("w:fill"), color)


def insert_table_after(
    document: Document,
    anchor,
    data: list[list[str]],
    *,
    font_size: float = 6.5,
):
    table = document.add_table(rows=len(data), cols=len(data[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for row_index, values in enumerate(data):
        for column_index, value in enumerate(values):
            cell = table.cell(row_index, column_index)
            cell.text = value
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            for paragraph in cell.paragraphs:
                paragraph.alignment = (
                    WD_ALIGN_PARAGRAPH.CENTER
                    if row_index == 0
                    else WD_ALIGN_PARAGRAPH.LEFT
                )
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
                    run.font.name = "Noto Sans CJK KR"
                    run._element.rPr.rFonts.set(
                        qn("w:eastAsia"),
                        "Noto Sans CJK KR",
                    )
                    run.bold = row_index == 0
        tr_pr = table.rows[row_index]._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:cantSplit")) is None:
            tr_pr.append(OxmlElement("w:cantSplit"))
    repeat_header(table)
    shade_header(table)
    anchor._element.addnext(table._tbl)
    return table


def renumber_existing_tables(document: Document) -> None:
    korean_map = {
        1: 2,
        2: 3,
        3: 4,
        4: 5,
        5: 6,
        6: 8,
        7: 9,
        8: 10,
        9: 11,
        10: 12,
        11: 13,
    }
    english_map = {
        1: 2,
        2: 3,
        3: 4,
        4: 5,
        5: 6,
        6: 8,
        7: 9,
        8: 10,
        9: 11,
        10: 12,
        11: 13,
    }

    for paragraph in document.paragraphs:
        original = paragraph.text

        def korean(match: re.Match[str]) -> str:
            old = int(match.group(1))
            return f"표 {korean_map.get(old, old)}"

        def english(match: re.Match[str]) -> str:
            old = int(match.group(1))
            return f"Table {english_map.get(old, old)}."

        revised = re.sub(r"표 (1[01]|[1-9])(?!\d)", korean, original)
        revised = re.sub(r"Table (1[01]|[1-9])\.", english, revised)
        if revised != original:
            clear_and_set(paragraph, revised)


def table_signature(table) -> tuple[str, ...]:
    return tuple(cell.text.strip() for row in table.rows for cell in row.cells)


def normalized_signature(table) -> tuple[str, ...]:
    return tuple(
        value.replace("보조지수", "점수")
        for value in table_signature(table)
    )


def rule_analysis_summary() -> dict[str, list[dict[str, str]]]:
    with RULE_ANALYSIS.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped.setdefault(row["cwe"], []).append(row)
    return grouped


def validate(source: Path, destination: Path, source_hash: str) -> None:
    if sha256(source) != source_hash:
        raise AssertionError("source DOCX changed")
    with zipfile.ZipFile(destination) as archive:
        if bad_member := archive.testzip():
            raise AssertionError(f"corrupt DOCX member: {bad_member}")
        document_xml = archive.read("word/document.xml").decode("utf-8")
        if 'w:type="page"' in document_xml:
            raise AssertionError("unexpected explicit page break")

    source_doc = Document(source)
    output_doc = Document(destination)
    if len(source_doc.tables) != 13 or len(output_doc.tables) != 15:
        raise AssertionError("expected 13 source tables and 15 output tables")
    if len(source_doc.inline_shapes) != 1 or len(output_doc.inline_shapes) != 1:
        raise AssertionError("the process figure was not preserved")
    if len(output_doc.sections) != 1:
        raise AssertionError("unexpected section count")

    existing_output = [
        table
        for index, table in enumerate(output_doc.tables)
        if index not in (0, 6)
    ]
    source_signatures = Counter(
        normalized_signature(table)
        for table in source_doc.tables
    )
    output_signatures = Counter(
        normalized_signature(table)
        for table in existing_output
    )
    if source_signatures != output_signatures:
        raise AssertionError("existing experimental table content changed")

    all_text = "\n".join(paragraph.text for paragraph in output_doc.paragraphs)
    all_text += "\n" + "\n".join(
        cell.text
        for table in output_doc.tables
        for row in table.rows
        for cell in row.cells
    )

    required = (
        "범용 정적 분석기를 DT 전용 탐지기로 제안하는 대신",
        "RQ1:",
        "RQ2:",
        "RQ3:",
        "Table 1. Mapping of DT components, security review points, policy coverage, and deployment impact",
        "Table 7. Rule-level diagnostic analysis of OWASP Benchmark detections",
        "CWE-327의 130개 실제 취약 사례",
        "단일 판독자 검토 반영 게이트",
        "탐색적 CWE 탐지 프로파일 비교",
        "정책 기반 보조지수",
        "보조자료 S1",
        "analysis/benchmark_rule_error_analysis.csv",
        "정밀도 0.533",
        "재현율 0.772",
        "F1-Score 0.630",
        "자동 정책 범위 274건",
        "정확 위치 220개",
        "ρ=0.999",
        "ρ=0.811",
        "1,074개 OSS 룰",
        "Gitleaks v8.21.2",
        "Semgrep v1.157.0",
    )
    for value in required:
        if value not in all_text:
            raise AssertionError(f"required text missing: {value}")

    forbidden = (
        "보안 점수",
        "이를 반영한 최종 판정",
        "수동 판독을 반영한 최종 게이트",
        "4.3.1 OWASP Benchmark v1.2 기반 탐지 정확도",
        "4.4.3 DT와 검증용 취약 웹앱의 CWE 탐지 프로파일 비교",
    )
    for value in forbidden:
        if value in all_text:
            raise AssertionError(f"overstated or obsolete wording remains: {value}")

    captions = [
        paragraph.text
        for paragraph in output_doc.paragraphs
        if paragraph.text.startswith("Table ")
    ]
    expected_numbers = [str(index) for index in range(1, 14)] + ["A1", "A2"]
    actual_numbers = [
        re.match(r"Table ([A0-9]+)\.", caption).group(1)
        for caption in captions
    ]
    if actual_numbers != expected_numbers:
        raise AssertionError(
            f"table captions out of order: {actual_numbers}"
        )

    manual = json.loads(
        (ROOT / "analysis/dt_manual_validation_summary.json").read_text()
    )
    experiment = json.loads(
        (ROOT / "analysis/dt_revision_experiments.json").read_text()
    )
    metadata = json.loads(
        (ROOT / "analysis/dt_repository_metadata.json").read_text()
    )
    if manual["unique_location_count"] != 101:
        raise AssertionError("manual validation count changed")
    if manual["unique_assessment_counts"] != {
        "confirmed_pattern": 33,
        "context_only": 28,
        "false_positive": 40,
    }:
        raise AssertionError("manual assessment distribution changed")
    if experiment["ablation"]["combined_policy"]["finding_count"] != 274:
        raise AssertionError("policy finding count changed")
    if experiment["ablation"]["combined_policy_deduplicated"]["finding_count"] != 220:
        raise AssertionError("deduplicated finding count changed")
    if experiment["ablation"]["manual_ch_confirmed_raw_ml"]["finding_count"] != 179:
        raise AssertionError("review-adjusted finding count changed")
    if len(metadata) != 14 or not all(
        row["full_commit_sha"] in all_text for row in metadata
    ):
        raise AssertionError("repository metadata or commit SHA missing")


def build(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    if not RULE_ANALYSIS.exists():
        raise FileNotFoundError(
            f"{RULE_ANALYSIS} is missing; run scripts/analyze_benchmark_rule_errors.py"
        )

    source_hash = sha256(source)
    document = Document(source)
    renumber_existing_tables(document)

    # Title, abstracts, and terminology.
    title = document.paragraphs[0]
    clear_and_set(
        title,
        "웹 기반 디지털트윈 코드베이스의 정적 보안 측정과 환경 민감형 배포 게이트: 공개 저장소 기반 실증\n"
        "Static Security Measurement and Environment-Sensitive Deployment Gates for "
        "Web-Based Digital Twin Codebases: An Empirical Study of Public Repositories",
        bold=True,
        size=14,
    )
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    replace(
        document,
        "웹 기반 DT는",
        "웹 기반 DT는 3D 시각화, 실시간 센서 동기화 및 원격 제어 기능을 제공하지만, "
        "웹 애플리케이션 계층의 정적 분석 경고를 DT 구성요소와 배포 문맥에서 해석하는 "
        "실증 연구는 제한적이다. 본 연구는 범용 정적 분석기를 DT 전용 탐지기로 제안하는 "
        "대신, Gitleaks와 Semgrep의 경고를 16종 CWE 정책, 정확 위치 중복 제거, 단일 판독자 "
        "문맥 검토, 정책 기반 보조지수 및 환경 민감형 배포 게이트로 연결하는 재현 가능한 "
        "절차를 제시한다. OWASP Benchmark v1.2와 공개 DT 14개 고정 커밋을 대상으로 기준 "
        "성능 평가, 수동 판독, 구성요소 제거 및 가중치 민감도 분석을 수행하였다. 정책 중첩 "
        "6개 CWE에서 현재 룰셋은 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 보였고, "
        "CWE-327의 130개 실제 취약 사례는 탐지하지 못하였다. 공개 DT에서 자동 분류된 "
        "274건 가운데 Critical·High 77건과 Medium 30건을 검토한 결과, 중복을 제외한 "
        "Critical·High 72개 위치 중 31개가 확인된 위험 패턴으로 분류되었다. 단일 판독자 "
        "검토 반영 게이트는 BLOCK 8개, BLOCK_PENDING_APPROVAL 1개, WARN 2개 및 PASS "
        "3개였다.",
    )
    replace(
        document,
        "Web-based digital twins provide",
        "Web-based digital twins provide 3D visualization, real-time sensor synchronization, "
        "and remote control, but empirical studies that interpret static-analysis alerts in "
        "DT component and deployment contexts remain limited. This study does not present "
        "general-purpose analyzers as DT-specific detectors. Instead, it provides a reproducible "
        "procedure that connects Gitleaks and Semgrep alerts to a 16-CWE policy catalogue, "
        "exact-location deduplication, single-reviewer contextual adjudication, an auxiliary "
        "policy index, and an environment-sensitive deployment gate. OWASP Benchmark v1.2 and "
        "14 pinned public DT repositories were evaluated through baseline performance, manual "
        "adjudication, ablation, and weight-sensitivity analyses. On six policy-overlapping "
        "CWEs, the current ruleset achieved 0.533 precision, 0.772 recall, and an F1-score of "
        "0.630, while all 130 true CWE-327 cases remained undetected. Of 77 automated "
        "Critical/High records in the DT repositories, 72 unique locations remained after "
        "deduplication and 31 were classified as confirmed risky patterns. The single-reviewer-"
        "adjusted gates were eight BLOCK, one BLOCK_PENDING_APPROVAL, two WARN, and three PASS.",
    )
    replace(
        document,
        "디지털트윈, 웹 보안",
        "디지털트윈, 웹 보안, 정적 애플리케이션 보안 테스팅, 정책 기반 보조지수, "
        "보안 게이트, DevSecOps",
    )
    replace(
        document,
        "Digital twin, static application security testing",
        "Digital twin, static application security testing, contextual adjudication, "
        "auxiliary policy index, security gate, DevSecOps",
    )

    # Introduction: narrow the claim and add explicit RQs.
    replace(
        document,
        "따라서 웹 기반 DT 소프트웨어의 보안성을 검증하기 위해서는",
        "따라서 웹 기반 DT 소프트웨어에서는 소스 코드의 잠재적 보안 경고를 체계적으로 "
        "탐지하고, DT 구성요소와 배포 문맥을 함께 기록하여 검토 우선순위와 배포 판정으로 "
        "연결할 절차가 필요하다. 이때 정량값은 절대적인 보안 수준이나 실제 악용 가능성을 "
        "나타내는 점수가 아니라, 선택한 정책 범위의 경고 분포를 요약하는 보조지수로 "
        "한정되어야 한다.",
    )
    replace(
        document,
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 정적 분석 결과를",
        "본 연구는 범용 정적 분석 도구가 생성한 경고를 웹 기반 DT 코드베이스의 구성요소와 "
        "배포 문맥에서 판독하고, 정확 위치 중복 제거, 정책 기반 보조지수 및 환경별 DevSecOps "
        "배포 판정으로 연결하는 재현 가능한 실증 절차를 제시한다. 자동 경고는 확정 취약점이 "
        "아니므로 자동 예비 게이트와 단일 판독자 검토 반영 게이트를 구분한다. Benchmark의 "
        "정책 중첩 6개 CWE에서 현재 룰셋의 기준 성능과 미탐 영역을 확인하고, 공개 DT 14개에 "
        "적용하여 경고 처리 단계가 판정에 미치는 변화를 분석하였다.",
    )
    replace(
        document,
        "DT 웹앱 대상 측정 체계 제안:",
        "재현 가능한 경고–판정 연결 절차: Gitleaks·Semgrep 경고를 16종 CWE 정책에 매핑하고, "
        "정확 위치 중복 제거와 단일 판독자 문맥 판독을 거쳐 정책 기반 보조지수와 환경별 "
        "배포 게이트로 연결하였다(제3.1절 및 제3.2절).",
    )
    replace(
        document,
        "정책 기반 보조지수·판정 모델 설계:",
        "DT 구성요소 문맥과 적용 범위 명시: 실시간 상태 채널, 원격 제어 API, 센서 데이터 "
        "시각화, 3D 생성 코드 및 CI·배포 구성을 정책과 연결하고, 상태 무결성·재전송·물리 "
        "제어 의미 검증은 현재 정적 정책의 범위 밖임을 구분하였다(표 1).",
    )
    contribution3 = replace(
        document,
        "DT 코드베이스의 실증 분석:",
        "다층 실증 평가: OWASP Benchmark의 기준 성능, 공개 DT 14개의 단일 판독자 검토, "
        "구성요소 제거 및 가중치 민감도 분석을 수행하였다. 취약 웹앱과의 CWE 비교는 모집단 "
        "차이 검정이 아닌 후속 연구용 탐색적 분석으로 한정하였다(제4.3절 및 제4.4절).",
    )
    anchor = insert_paragraph_after(
        document,
        contribution3,
        "이러한 기여를 평가하기 위한 연구 질문은 다음과 같다.",
        "Body Text",
    )
    anchor = insert_paragraph_after(
        document,
        anchor,
        "RQ1: 정책과 중첩되는 CWE에서 현재 정적 분석 룰셋의 기준 탐지 성능과 취약한 "
        "정책 영역은 무엇인가?",
    )
    anchor = insert_paragraph_after(
        document,
        anchor,
        "RQ2: 정확 위치 중복 제거와 단일 판독자 문맥 판독은 탐지량과 배포 판정을 "
        "어떻게 변화시키는가?",
    )
    insert_paragraph_after(
        document,
        anchor,
        "RQ3: 정책 기반 보조지수와 배포 게이트는 구성요소 제거, 가중치 변화 및 코드 계보 "
        "중복에 대해 어느 정도 안정적인가?",
    )

    # Problem definition: replace population-comparison language with context interpretation.
    replace(
        document,
        "둘째, 탐지 결과를 DT 소프트웨어의 보안 수준과",
        "둘째, 탐지 결과를 DT 소프트웨어의 검토 우선순위와 배포 가능 여부로 변환하는 "
        "일관된 절차가 미흡하다. 기존 SAST 도구는 개별 경고의 유형과 심각도를 제공하지만, "
        "범용 경고를 DT 구성요소 및 배포 환경과 함께 기록하고 정책 범위의 보조지수와 "
        "배포 판정으로 변환하는 방법은 충분히 제시되지 않았다. 이로 인해 경고량을 절대 "
        "보안 수준으로 오해하거나, 경고를 검토 없이 DevSecOps 차단 조건으로 사용하는 "
        "문제가 발생할 수 있다.",
    )
    replace(
        document,
        "셋째, DT 웹앱의 취약점 특성에 관한 실증적 프로파일이",
        "셋째, 범용 정적 분석 경고를 실시간 센서 채널, 원격 제어 API, 3D·Unity 생성 코드 "
        "및 센서 데이터 시각화와 같은 DT 구성요소 문맥에서 판독한 실증 자료가 부족하다. "
        "CWE 자체는 DT 전용이 아니므로, 어떤 경고가 DT의 배포 산출물과 연결되고 어떤 위협이 "
        "현재 정책 범위 밖에 남는지를 구분하여 제시할 필요가 있다.",
    )
    replace(
        document,
        "본 연구는 이러한 연구 공백을 해소하기 위해",
        "본 연구는 이러한 연구 공백을 다루기 위해 범용 정적 분석 경고를 DT 구성요소 문맥과 "
        "연결하고, 중복 제거·단일 판독자 검토·정책 기반 보조지수·환경별 게이트로 이어지는 "
        "절차를 정의한다. RQ1은 제4.3.1절의 Benchmark 기준 성능과 룰 진단으로, RQ2는 "
        "제4.3.2절 및 제4.4.1절의 공개 DT 판독과 구성요소 제거로, RQ3은 제4.4.2절 및 "
        "제4.4.3절의 민감도와 탐색적 프로파일 분석으로 각각 답한다.",
    )

    # Method: explicitly state the generic detection core and add DT context mapping.
    replace(
        document,
        "3. 웹 기반 디지털트윈을 위한 보안성 측정 기법",
        "3. 웹 기반 디지털트윈 코드베이스의 정적 보안 측정 절차",
    )
    replace(
        document,
        "본 장에서는 웹 기반 DT 소프트웨어의 보안성을 정량적으로",
        "본 장에서는 범용 정적 분석 도구가 생성한 경고를 웹 기반 DT 코드베이스의 구성요소와 "
        "배포 문맥에서 정리하고, 정책 기반 보조지수와 배포 판정으로 연결하는 절차를 정의한다. "
        "탐지 코어인 Gitleaks와 Semgrep은 일반 웹 애플리케이션에도 적용 가능하며, 본 연구의 "
        "DT 맥락은 구성요소–위협–정책 매핑과 수동 판독의 배포 관련성 해석에서 부여된다. 각 "
        "단계의 산출물은 JSON 형식으로 전달되어 CI/CD 파이프라인에서 처리된다.",
    )
    figure_caption = find_paragraph(document, "Fig. 1.")
    mapping_intro = insert_paragraph_after(
        document,
        figure_caption,
        "표 1은 웹 기반 DT의 주요 구성요소를 보안 검토 지점, 현재 정책 범위 및 배포 영향과 "
        "연결한다. 이 매핑은 CWE를 DT 전용 취약점으로 재정의하기 위한 것이 아니라, 범용 "
        "경고를 DT 배포 산출물의 문맥에서 판독하고 현재 정적 정책이 다루지 못하는 영역을 "
        "명시하기 위한 해석 계층이다.",
        "Body Text",
    )
    mapping_caption = insert_paragraph_after(
        document,
        mapping_intro,
        "Table 1. Mapping of DT components, security review points, policy coverage, and deployment impact",
    )
    mapping_table = insert_table_after(
        document,
        mapping_caption,
        [
            ["DT 구성요소", "주요 보안 검토 지점", "관련 CWE", "현재 분석 범위", "배포 영향"],
            [
                "실시간 센서·상태 동기화 채널",
                "평문 전송, 토큰·JWT 검증",
                "319, 347, 798",
                "319·798 정책 적용; 347은 DT 표본 미관찰",
                "High 승인 필요 / Critical 차단",
            ],
            [
                "원격 제어·백엔드 API",
                "명령·코드·SQL 삽입, 객체 권한",
                "78, 89, 94, 639",
                "정책 포함; DT 표본에서는 78 관찰",
                "Critical 차단 / High 승인 필요",
            ],
            [
                "센서·운영 데이터 시각화",
                "동적 데이터의 DOM·응답 렌더링",
                "79",
                "공개 DT 및 수소선박 사례에서 관찰",
                "Medium 경고; 운영 환경 승인 필요",
            ],
            [
                "Unity WebGL·3D 생성 코드",
                "통신 주소, 경로·동적 렌더링 설정",
                "22, 79, 319",
                "생성 코드 포함 스캔 후 배포 관련성 판독",
                "정책 등급과 문맥 판독에 따름",
            ],
            [
                "CI·빌드·배포 구성",
                "자격증명 내장, 셸 실행 경계",
                "798, 78",
                "Gitleaks·Semgrep 결합 및 문맥 분류",
                "Critical 차단",
            ],
            [
                "상태 무결성·재전송·물리 제어 의미",
                "상태 변조, 재전송, 안전하지 않은 제어 의미",
                "직접 대응 없음",
                "현재 16종 정적 정책 범위 밖",
                "향후 동적·런타임 검증 대상",
            ],
        ],
    )
    insert_paragraph_after_element(
        document,
        mapping_table._tbl,
        "따라서 본 절차는 DT 전용 탐지기를 주장하지 않으며, 현재 정책으로 포착 가능한 웹 계층 "
        "경고와 상태 무결성·물리 제어 의미처럼 별도 검증이 필요한 DT 위협을 구분한다.",
        "Body Text",
    )
    replace(
        document,
        "보안 정책은 OWASP",
        "보안 정책은 OWASP Top 10:2021 [17]과 CVSS v3.1 [18]의 질적 심각도 용어를 "
        "참고하되, 표 2의 등급과 감점은 본 연구의 운영 정책으로 정의하였다. 20·5·1·0.2의 "
        "감점은 CVSS에서 도출한 경험적 위험값이 아니며, 정책 기반 보조지수의 가중치 변화는 "
        "제4.4.2절에서 민감도만 평가한다.",
    )
    replace(
        document,
        "16개 항목은 Critical",
        "16개 항목은 Critical·High·Medium·Low 각 4종으로 구성되며, CWE를 공통 식별자로 "
        "사용해 스캐너 결과를 정책 등급으로 재분류한다. 표 2에는 정책 등급, 실제 관찰 "
        "스캐너와 대표 룰 ID를 공개하고, 전체 룰 ID·횟수는 "
        "analysis/policy_catalog_with_observed_rules.csv에 보존하였다. 이 정책은 DT "
        "전용 CWE 집합이 아니며, 카탈로그 밖 탐지는 범위 외 결과로 유지한다.",
    )
    replace(
        document,
        "보안 취약점 탐지는 2단계 스캔 체계로 수행된다.",
        "탐지 단계는 일반 소프트웨어에도 적용 가능한 2단계 스캔 체계로 수행된다. DT 구성요소 "
        "문맥과 배포 관련성은 탐지 이후의 정규화·판독 단계에서 기록한다.",
    )
    replace(
        document,
        "정확 위치 중복 제거 후 범위 내 레코드의 등급별",
        "정확 위치 중복 제거 후 범위 내 레코드의 등급별 분포로 100점 만점 형식의 정책 기반 "
        "보조지수 S를 산출한다. 이 값은 실제 공격 성공 확률, 절대 보안 수준 또는 전문가 "
        "위험 순위를 추정하지 않으며, 선택한 16개 정책의 경고 분포를 운영상 비교하기 위한 "
        "요약량이다. 배포 판정은 본 절에서 후술하는 계층형 게이트가 독립적으로 결정한다.",
    )
    replace(
        document,
        "등급별 건당 감점 20·5·1·0.2와 상한",
        "등급별 건당 감점 20·5·1·0.2와 상한 19·4·0.9는 상위 등급 한 건이 하위 등급의 "
        "누적보다 우선하도록 정한 운영 정책 매개변수다. Critical 존재 시 0~40 구간으로 "
        "제한한 것도 상위 경고가 있는 저장소를 표시상 분리하기 위한 규칙이며, 전문가 판단이나 "
        "배포 사고 자료로 보정한 임계값이 아니다. 제4.4.2절에서는 상한 제거, 단순 건수, "
        "CVSS 질적 구간 중앙값 및 대안 가중치에 대한 순위 민감도만 비교한다.",
    )
    replace(
        document,
        "이 설계에서 Low 전체 감점은",
        "이 설계에서 Low 전체 감점은 Medium 한 건보다, Medium 전체 감점은 High 한 건보다, "
        "High 전체 감점은 Critical 한 건보다 작다. 표 3과 같이 보조지수와 게이트 판정을 "
        "분리함으로써 지수는 정책 경고 구성의 비교에만 사용하고, 상위 심각도 탐지는 별도의 "
        "승인·차단 절차로 연결한다.",
    )
    replace(
        document,
        "배포 판정은 보조 점수의 단일 임계값이 아니라",
        "배포 판정은 정책 기반 보조지수의 단일 임계값이 아니라 탐지 심각도와 배포 환경의 "
        "조합으로 수행한다. 표 4는 production, staging, development 및 feature 환경에서 "
        "Critical·High·Medium 탐지를 처리하는 규칙을 나타낸다.",
    )
    replace(
        document,
        "예를 들어 High 1건이 탐지되면",
        "예를 들어 High 1건이 탐지되면 정책 기반 보조지수는 95일 수 있으나 판정은 "
        "BLOCK_PENDING_APPROVAL이므로 승인 전 배포가 중단된다. 이 예시는 보조지수가 "
        "배포 허용 임계값이나 절대적인 보안 수준이 아님을 보여준다.",
    )

    # Replace score wording inside existing table cells and remaining prose.
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if "점수" in cell.text:
                    cell.text = cell.text.replace("점수", "보조지수")
    for paragraph in document.paragraphs:
        original = paragraph.text
        revised = (
            original.replace("보조 점수", "정책 기반 보조지수")
            .replace("점수 모델", "보조지수 모델")
            .replace("게이트는 점수와 독립적으로", "게이트는 보조지수와 독립적으로")
        )
        if revised != original:
            clear_and_set(paragraph, revised)

    # Experiment design and RQ alignment.
    replace(
        document,
        "본 연구의 분석 대상은 공개 DT 웹앱",
        "본 연구의 분석 대상은 공개 DT 웹앱 14개와 수소추진선박 DT 1개이며, 현재 룰셋의 "
        "기준 성능 평가와 탐색적 CWE 프로파일 기술을 위해 검증용 취약 웹앱 8개를 함께 "
        "사용하였다.",
    )
    replace(
        document,
        "검증용 취약 웹앱(8개):",
        "검증용 취약 웹앱(8개): OWASP Juice-Shop, OWASP NodeGoat, DVNA, WebGoat, "
        "Vulnerable-Flask-App, django.nV, OWASP Benchmark 및 dvpwa를 사용하였다. 공식 "
        "테스트 케이스별 정답표가 포함된 OWASP Benchmark v1.2는 RQ1의 기준 성능 평가에 "
        "사용하고, 나머지 7개는 일반 웹앱 모집단 비교가 아닌 탐색적 CWE 프로파일 기술에만 "
        "활용하였다.",
    )
    replace(
        document,
        "검증 절차는 세 부분으로 구성하였다.",
        "검증 절차는 연구 질문에 따라 구성하였다. RQ1은 OWASP Benchmark v1.2와 정책이 "
        "중첩되는 6개 CWE의 TP·FP·FN 및 룰별 기여를 분석하였다. RQ2는 공개 DT 14개의 "
        "자동 탐지, 정확 위치 중복 제거 및 단일 판독자 문맥 판독을 비교하였다. RQ3은 "
        "구성요소 제거와 보조지수 가중치 민감도를 평가하고, 코드 계보 중복의 영향을 "
        "탐색적으로 기술하였다.",
    )

    # Benchmark: baseline-performance framing and rule-level diagnostics.
    replace(
        document,
        "4.3 취약점 탐지 결과 및 유형",
        "4.3 기준 성능 및 적용 결과",
    )
    replace(
        document,
        "4.3.1 OWASP Benchmark v1.2 기반 탐지 정확도",
        "4.3.1 OWASP Benchmark v1.2 기반 룰셋 기준 성능",
    )
    replace(
        document,
        "정확도 평가는 OWASP Benchmark",
        "기준 성능 평가는 OWASP Benchmark v1.2 정답표와 16종 정책이 공통으로 포함하는 "
        "CWE-22, CWE-78, CWE-79, CWE-89, CWE-327 및 CWE-614를 대상으로 수행하였다. "
        "테스트 케이스 ID와 CWE가 모두 일치하는 범위 내 탐지를 TP·FP·FN으로 집계하였다. "
        "표 6의 마이크로 합계는 TP 728, FP 639, FN 215이며 정밀도 0.533, 재현율 0.772, "
        "F1-Score 0.630이다. 이는 우수성을 주장하는 비교 성능이 아니라 현재 고정 룰셋의 "
        "기준 성능이다.",
    )
    benchmark_interpretation = replace(
        document,
        "CWE-22, CWE-78 및 CWE-89의 재현율은",
        "CWE-22, CWE-78 및 CWE-89의 재현율은 각각 0.902, 0.929 및 0.930이었고, "
        "CWE-614는 정밀도와 재현율이 모두 1.000이었다. 반면 CWE-327은 TP=0, FN=130으로 "
        "현재 룰셋이 해당 Benchmark 패턴을 탐지하지 못하였다. 마이크로 정밀도 0.533은 "
        "탐지 경고의 상당 부분에 추가 판독이 필요함을 의미하므로, 본 결과는 자동 확정 "
        "성능이 아니라 현재 룰셋의 커버리지 불균형과 보완 우선순위를 보여주는 기준선으로 "
        "해석한다.",
    )
    rule_caption = insert_paragraph_after(
        document,
        benchmark_interpretation,
        "Table 7. Rule-level diagnostic analysis of OWASP Benchmark detections",
    )
    grouped = rule_analysis_summary()
    expected_rule_counts = {
        "CWE-22": [(120, 106, 0)],
        "CWE-78": [(112, 96, 0), (33, 30, 0)],
        "CWE-79": [(202, 108, 146)],
        "CWE-89": [(234, 143, 0), (97, 81, 0)],
        "CWE-327": [(0, 0, 0)],
        "CWE-614": [(36, 0, 0)],
    }
    actual_rule_counts = {
        cwe: [
            (
                int(row["rule_tp_unique_tests"]),
                int(row["rule_fp_same_cwe_unique_tests"]),
                int(row["rule_fp_cross_cwe_unique_tests"]),
            )
            for row in rows
        ]
        for cwe, rows in grouped.items()
    }
    if actual_rule_counts != expected_rule_counts:
        raise AssertionError(
            f"archived rule-level counts changed: {actual_rule_counts}"
        )
    short = {
        "CWE-22": (
            "httpservlet-path-traversal",
            "120/106/0",
            "경로 흐름의 안전·취약 문맥 구분 부족",
            "정규화·검증 조건 정제",
        ),
        "CWE-78": (
            "tainted-cmd; process-builder",
            "112/96/0; 33/30/0",
            "두 룰 중복 및 명령 구성 문맥 오탐",
            "인자 배열·검증 흐름 구분",
        ),
        "CWE-79": (
            "no-direct-response-writer",
            "202/108/146",
            "직접 응답 쓰기와 교차 CWE 분류가 광범위",
            "출력 인코딩·데이터 흐름 조건 추가",
        ),
        "CWE-89": (
            "tainted-sql; jdbc-sqli",
            "234/143/0; 97/81/0",
            "두 룰 중복 및 SQL 구성 문맥 오탐",
            "파라미터 바인딩·검증 흐름 구분",
        ),
        "CWE-327": (
            "대응 in-scope 매치 없음",
            "0/0/0",
            "실제 취약 사례 130건 전부 미탐",
            "Benchmark 패턴 대응 암호 룰 보강",
        ),
        "CWE-614": (
            "cookie-missing-secure-flag",
            "36/0/0",
            "고정 속성 패턴을 정확히 식별",
            "현재 규칙 유지·회귀 검증",
        ),
    }
    if set(grouped) != set(short):
        raise AssertionError("rule analysis CWE set changed")
    rule_table = insert_table_after(
        document,
        rule_caption,
        [
            ["CWE", "주요 룰(축약)", "룰별 TP/동일 CWE FP/교차 CWE FP", "관찰", "보완 방향"],
            *[
                [cwe, *short[cwe]]
                for cwe in ("CWE-22", "CWE-78", "CWE-79", "CWE-89", "CWE-327", "CWE-614")
            ],
        ],
    )
    insert_paragraph_after_element(
        document,
        rule_table._tbl,
        "표 7의 룰별 건수는 고유 테스트 케이스 기준이며, 하나의 테스트가 여러 룰에 탐지될 수 "
        "있어 표 6의 CWE 합계와 단순 합산되지 않는다. 집계 결과는 보조자료의 "
        "analysis/benchmark_rule_error_analysis.csv에 보존하였다.",
        "Body Text",
    )
    replace(
        document,
        "Table 8. Automatic, deduplicated, and Critical/High review-adjusted DT results",
        "Table 8. Automatic, deduplicated, and single-reviewer-adjusted DT results",
    )
    replace(
        document,
        "Table 11. Ablation results for scanner combination, policy filtering, deduplication, and manual review",
        "Table 11. Ablation results for scanner combination, policy filtering, deduplication, "
        "and single-reviewer adjudication",
    )

    # Public-DT manual adjudication: make the single-reviewer boundary explicit.
    replace(
        document,
        "14개 공개 DT 웹앱은 표",
        "14개 공개 DT 웹앱은 표 5의 전체 커밋 SHA를 고정하고 development 환경에서 "
        "재검사하였다. 모든 저장소에서 두 스캐너가 완료되고 판정 JSON이 생성되었으며, "
        "저장소당 전체 분석 시간 중앙값은 30.5초였다. 자동 결과, 정확 위치 중복 제거 결과 "
        "및 Critical·High 단일 판독자 검토 반영 결과를 표 8에 함께 제시한다.",
    )
    replace(
        document,
        "원시 탐지 482건 가운데",
        "원시 탐지 482건 가운데 274건이 16개 정책 범위에 포함되고 208건은 범위 외로 "
        "분리되었다. 자동 범위 내 분포는 Critical 69건, High 8건, Medium 197건이며, "
        "정확 위치 중복 제거 후 220개 위치로 축약되었다. 자동 예비 게이트는 PASS 3개, "
        "WARN 1개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 9개였다. 단일 판독자가 "
        "Critical·High의 확인 패턴만 유지하고 Medium·Low는 중복 제거 자동 결과를 유지한 "
        "검토 반영 게이트는 PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK "
        "8개로 변경되었다.",
    )
    replace(
        document,
        "Critical 69건과 High 8건을 전수 검토하였다.",
        "1명의 판독자가 Critical 69건과 High 8건을 전수 검토하였다. Medium은 CWE-79 "
        "6건을 전수 검토하고, CWE-22 191건에서 난수 시드 20260723으로 24건을 비복원 "
        "단순무작위 추출하였다. 정확 위치 중복을 제외하면 Critical·High 72개, CWE-79 "
        "6개, CWE-22 표본 23개로 총 101개 위치다. 판독 기준은 확인된 위험 패턴, 문맥 "
        "제한 패턴, 오탐 및 중복이며, 확인된 위험 패턴은 위험 구문이나 자격증명 내장 패턴의 "
        "존재를 뜻할 뿐 실제 악용 가능성이 확인된 취약점을 의미하지 않는다.",
    )
    replace(
        document,
        "Gitleaks 결합은 Semgrep 단독 대비",
        "Gitleaks 결합은 Semgrep 단독 대비 Hardcoded Secret을 포함하여 자동 BLOCK을 "
        "5개에서 9개로 확대하였다. 16종 정책 필터는 전체 482건을 274건으로 축약하면서 "
        "PASS를 1개에서 3개로 조정하였다. 정확 위치 중복 제거는 54건을 줄였으나 게이트 "
        "분포는 유지되었다. 단일 판독자 문맥 검토는 게이트 한 건을 변경하였다. 이 결과는 "
        "자동 경고를 실제 악용 가능성이 확인된 취약점으로 간주하지 않고 검토 단계를 분리할 "
        "필요성을 보여준다.",
    )
    replace(
        document,
        "세 계층형 가중치 조합에서 순위는",
        "세 계층형 가중치 조합에서 저장소 순위는 거의 동일했으나(ρ=0.999), 상한 지수와 "
        "단순 건수의 상관은 0.776이었다. 이는 선택한 범위의 가중치 변화에 대한 순위 "
        "안정성을 보여줄 뿐, 20·5·1·0.2가 전문가 판단이나 실제 배포 위험을 정확히 "
        "반영한다는 타당성 증거는 아니다. 게이트는 보조지수와 독립적으로 심각도 존재 여부를 "
        "사용하므로 모든 가중치에서 동일했다.",
    )

    # Exploratory comparison: explicitly reject population inference.
    replace(
        document,
        "4.4.3 DT와 검증용 취약 웹앱의 CWE 탐지 프로파일 비교",
        "4.4.3 DT와 검증용 취약 웹앱의 탐색적 CWE 탐지 프로파일 비교",
    )
    replace(
        document,
        "검증용 취약 웹앱 8개와 공개 DT 14개의 자동 정책 범위 CWE 분포를",
        "검증용 취약 웹앱 8개와 공개 DT 14개의 자동 정책 범위 CWE 분포를 탐색적으로 "
        "기술하였다. DT 집합에는 Autodesk 2개, iTwin 2개, Vertex 3개의 관련 코드 계보가 "
        "포함되므로, 14개 저장소 분석과 함께 10개 계보 단위 민감도 분석을 수행하였다. "
        "표 13은 저장소 단위 및 계보 단위의 Odds Ratio와 양측 Fisher 정확 검정 결과를 "
        "제시하지만, 이는 모집단 차이의 확증 검정으로 사용하지 않는다.",
    )
    replace(
        document,
        "표 13의 분자는",
        "표 13의 분자는 해당 CWE가 한 건 이상 자동 탐지된 저장소 또는 계보 수이다. "
        "비교군이 의도적으로 취약하게 구성되었고 코드 규모·언어·저장소 유형이 다르므로, "
        "p-value와 Odds Ratio는 일반 웹앱 모집단과 DT 모집단의 우열이나 DT 특이성을 "
        "입증하지 않는다. 본 분석의 목적은 본 실험 집합의 구성을 기술하고 후속 규모·언어 "
        "매칭 연구의 가설 후보를 제시하는 데 있다.",
    )
    replace(
        document,
        "저장소 단위에서 CWE-319와 CWE-79는",
        "저장소 단위에서 CWE-319와 CWE-79는 각각 OR=0.167, p=0.1365 및 OR=0.164, "
        "p=0.0815였고, 계보 단위에서도 OR=0.250, p=0.3213 및 OR=0.257, p=0.3416으로 "
        "차이가 확인되지 않았다. CWE-89는 DT에서 관찰되지 않아 저장소 단위 p<0.001, "
        "계보 단위 p=0.0003이었지만, 이는 의도적으로 취약한 비교군의 SQL 주입 구성이 "
        "반영된 결과다. CWE-798은 두 분석 모두 차이가 없었다(p=1.0000). 따라서 이 결과를 "
        "DT 고유 분포로 일반화하지 않고 후속 매칭 연구를 위한 탐색적 기준선으로만 해석한다.",
    )

    # Limitations, conclusion, and reproducibility availability.
    limitation = replace(
        document,
        "결과의 적용 범위는 다음과 같다.",
        "결과의 적용 범위는 다음과 같다. Benchmark 기준 성능은 정책과 중첩되는 6개 CWE에 "
        "한정되며, CWE-327은 TP=0, FN=130으로 현 룰셋의 명확한 미탐 영역이다. 공개 DT "
        "수동 판독은 1인이 수행하여 평가자 간 일치도와 Cohen’s κ를 보고하지 못했다. "
        "Critical·High는 전수 검토했지만 Medium CWE-22는 191건 중 고정 난수 24건만 "
        "표본 추출했으며, 자격증명 유효성 검사와 실제 공격 실행은 수행하지 않았다.",
    )
    insert_paragraph_after(
        document,
        limitation,
        "또한 공개 DT 14개는 확률표본이 아니며 애플리케이션·데모·플랫폼·라이브러리, "
        "1,407~517,862 LOC의 규모 차이 및 관련 코드 계보를 포함한다. 취약 웹앱 비교군도 "
        "일반 운영 웹앱을 대표하지 않으므로 Fisher 검정은 탐색적 기술에 한정된다. 정책 "
        "가중치와 Critical 존재 시 0~40 제한은 전문가 순위나 배포 사고로 보정되지 않은 "
        "운영 매개변수이며, 16종 정적 정책은 상태 무결성·재전송·물리 제어 의미를 직접 "
        "검증하지 않는다.",
        "Body Text",
    )
    replace(
        document,
        "본 연구는 웹 기반 DT의 자동 정적 분석을",
        "본 연구는 범용 정적 분석기를 DT 전용 탐지기로 제안하지 않고, 그 경고를 웹 기반 "
        "DT 구성요소와 배포 문맥에서 판독하여 16종 CWE 정책, 정확 위치 중복 제거, 정책 "
        "기반 보조지수 및 환경 민감형 게이트로 연결하는 재현 가능한 실증 절차를 제시하였다. "
        "Benchmark의 정책 중첩 6개 CWE에서 현재 룰셋의 기준 성능은 정밀도 0.533, 재현율 "
        "0.772 및 F1-Score 0.630이었으며, CWE-327의 미탐 영역을 확인하였다. 공개 DT에서는 "
        "자동 정책 범위 274건이 정확 위치 220개로 축약되었고, Critical·High 고유 72개 "
        "위치 중 31개가 확인된 위험 패턴으로 분류되었다. 단일 판독자 검토 반영 판정은 "
        "PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개였다. 가중치 "
        "민감도 ρ=0.999는 순위 안정성만을 의미하며 가중치의 경험적 타당성으로 해석하지 않는다.",
    )
    appendix = replace(
        document,
        "표 A1은 분석한 공개 DT의 전체 커밋 SHA를 제시한다.",
        "표 A1은 분석한 공개 DT의 전체 커밋 SHA를 제시한다. 표 A2의 룰·설정·바이너리 "
        "해시와 experiment_output_sha256.csv의 70개 원시 산출물 해시를 이용해 실험 입력과 "
        "결과의 동일성을 확인할 수 있다. 재현성 자료는 본 원고와 함께 제출하는 보조자료 "
        "S1(웹기반DT_KCI_재현성자료.zip)에 포함하였다.",
    )
    insert_paragraph_after(
        document,
        appendix,
        "보조자료 S1에는 고정 룰 번들, Gitleaks 설정, 정책 카탈로그, 14개 DT의 판정 JSON "
        "및 비밀값·코드 스니펫을 제거한 정규화 경고, 원시 산출물 SHA-256 목록, "
        "Benchmark 정답표·비식별 탐지 결과, 수동 판독 CSV, 룰별 오차 집계 및 분석 "
        "스크립트가 포함된다. 연구 코드 저장소는 "
        "https://github.com/CapstoneLab/CICD-Engine이며, 최종 게재본에는 원고 버전과 "
        "대응하는 릴리스 태그 또는 영구 보관 DOI를 함께 명시한다.",
        "Body Text",
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
    print("validated=tables:15 figure:1 RQs:3 evidence_preserved:true")


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
