#!/usr/bin/env python3
"""Restructure the experiment-backed KCI paper without changing its evidence.

The source DOCX is preserved. Existing paragraphs, tables, figures, equations,
and result values are moved as XML elements. Only headings, cross-references,
table numbering affected by the move, and short transition labels are edited.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import zipfile
from collections import Counter
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_실험검증_최종개정본.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_실험검증_목차재구성본.docx"

W_P = qn("w:p")
W_TBL = qn("w:tbl")
W_SECT_PR = qn("w:sectPr")
W_BOOKMARK_START = qn("w:bookmarkStart")
W_BOOKMARK_END = qn("w:bookmarkEnd")
W_T = qn("w:t")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def text_of(element) -> str:
    if element.tag != W_P:
        return ""
    return "".join(node.text or "" for node in element.iter(W_T)).strip()


def style_of(paragraph) -> str:
    p_pr = paragraph.find(qn("w:pPr"))
    if p_pr is None:
        return ""
    p_style = p_pr.find(qn("w:pStyle"))
    return p_style.get(qn("w:val"), "") if p_style is not None else ""


def set_style(paragraph, style: str) -> None:
    p_pr = paragraph.find(qn("w:pPr"))
    if p_pr is None:
        p_pr = OxmlElement("w:pPr")
        paragraph.insert(0, p_pr)
    p_style = p_pr.find(qn("w:pStyle"))
    if p_style is None:
        p_style = OxmlElement("w:pStyle")
        p_pr.insert(0, p_style)
    p_style.set(qn("w:val"), style)


def set_paragraph_text(paragraph, value: str, *, bold: bool = False) -> None:
    p_pr = paragraph.find(qn("w:pPr"))
    for child in list(paragraph):
        if child is not p_pr:
            paragraph.remove(child)

    run = OxmlElement("w:r")
    if bold:
        r_pr = OxmlElement("w:rPr")
        r_pr.append(OxmlElement("w:b"))
        run.append(r_pr)

    for index, part in enumerate(value.split("\n")):
        if index:
            run.append(OxmlElement("w:br"))
        text = OxmlElement("w:t")
        if part.startswith(" ") or part.endswith(" ") or "  " in part:
            text.set(qn("xml:space"), "preserve")
        text.text = part
        run.append(text)
    paragraph.append(run)


def replace_text(paragraph, old: str, new: str) -> bool:
    current = text_of(paragraph)
    if old not in current:
        return False
    set_paragraph_text(paragraph, current.replace(old, new))
    return True


def clone_paragraph(template, text: str, *, style: str | None = None, bold: bool = False):
    paragraph = deepcopy(template)
    if style is not None:
        set_style(paragraph, style)
    set_paragraph_text(paragraph, text, bold=bold)
    return paragraph


def unique_index(nodes: list, exact_text: str) -> int:
    matches = [index for index, node in enumerate(nodes) if text_of(node) == exact_text]
    if len(matches) != 1:
        raise ValueError(f"expected one paragraph {exact_text!r}, found {len(matches)}")
    return matches[0]


def unique_startswith(nodes: list, prefix: str):
    matches = [node for node in nodes if text_of(node).startswith(prefix)]
    if len(matches) != 1:
        raise ValueError(f"expected one paragraph beginning {prefix!r}, found {len(matches)}")
    return matches[0]


def direct_tables(nodes: list) -> list:
    return [node for node in nodes if node.tag == W_TBL]


def table_signature(table) -> tuple[str, ...]:
    return tuple("".join(node.text or "" for node in cell.iter(W_T)).strip() for cell in table.iter(qn("w:tc")))


def body_paragraph_texts(document: Document) -> list[str]:
    return [text_of(node) for node in document._element.body if node.tag == W_P and text_of(node)]


def drawing_count(document: Document) -> int:
    return len(document._element.body.findall(".//" + qn("w:drawing")))


def validate(source: Path, destination: Path, source_hash: str) -> None:
    if sha256(source) != source_hash:
        raise AssertionError("source DOCX changed during restructuring")

    with zipfile.ZipFile(destination) as archive:
        if bad_member := archive.testzip():
            raise AssertionError(f"corrupt DOCX member: {bad_member}")
        document_xml = archive.read("word/document.xml").decode("utf-8")
        if 'w:type="page"' in document_xml:
            raise AssertionError("unexpected explicit page break")

    source_doc = Document(source)
    output_doc = Document(destination)
    source_tables = [table_signature(table._tbl) for table in source_doc.tables]
    output_tables = [table_signature(table._tbl) for table in output_doc.tables]

    if len(source_doc.tables) != 13 or len(output_doc.tables) != 13:
        raise AssertionError("the source and output must both contain 13 tables")
    if Counter(source_tables) != Counter(output_tables):
        raise AssertionError("table cell content changed")
    if drawing_count(source_doc) != 1 or drawing_count(output_doc) != 1:
        raise AssertionError("the process figure was not preserved")
    if len(output_doc.sections) != 1:
        raise AssertionError("unexpected section count")

    headings = [
        paragraph.text
        for paragraph in output_doc.paragraphs
        if paragraph.style.style_id == "Heading2"
    ]
    all_text = "\n".join(paragraph.text for paragraph in output_doc.paragraphs)
    all_text += "\n" + "\n".join(
        cell.text for table in output_doc.tables for row in table.rows for cell in row.cells
    )

    expected_headings = [
        "3. 웹 기반 디지털트윈을 위한 보안성 측정 기법",
        "3.1 개요",
        "3.2 상세 절차",
        "3.2.1 보안 취약점 탐지 단계",
        "3.2.2 탐지 결과 정규화 및 보안성 판정 단계",
        "4. 웹 기반 디지털트윈의 보안성 측정 사례 및 검증",
        "4.1 분석 대상 웹 기반 디지털트윈",
        "4.2 실험 환경 및 검증 방법",
        "4.3 취약점 탐지 결과 및 유형",
        "4.3.1 OWASP Benchmark v1.2 기반 탐지 정확도",
        "4.3.2 공개 디지털트윈의 취약점 탐지 결과",
        "4.3.3 수소추진선박 디지털트윈 적용 사례",
        "4.4 결과 분석 및 논의",
        "4.4.1 구성요소 제거 실험",
        "4.4.2 정책 기반 보조지수 민감도 분석",
        "4.4.3 DT와 검증용 취약 웹앱의 CWE 탐지 프로파일 비교",
        "4.4.4 타당성 위협 및 한계",
        "5. 결론 및 향후 연구",
    ]
    positions = []
    for heading in expected_headings:
        if headings.count(heading) != 1:
            raise AssertionError(f"missing or duplicate heading: {heading}")
        positions.append(headings.index(heading))
    if positions != sorted(positions):
        raise AssertionError("headings are out of order")

    for obsolete in (
        "3.2 보안 취약점 탐지",
        "3.3 탐지 결과 정량화 및 판정",
        "4. 실험 및 결과",
        "4.5 DT와 검증용 취약 웹앱의 저장소 단위 CWE 탐지 프로파일 비교",
    ):
        if obsolete in all_text:
            raise AssertionError(f"obsolete heading/reference remains: {obsolete}")

    for required in (
        "F1-Score 0.630",
        "Critical·High 77건",
        "정밀도 0.533",
        "재현율 0.772",
        "자동 정책 범위 274건",
        "정확 위치 220개",
        "ρ=0.999",
        "ρ=0.811",
        "1,074개 OSS 룰",
        "Gitleaks v8.21.2",
        "Semgrep v1.157.0",
        "BLOCK_PENDING_APPROVAL",
        "Table 8. In-scope findings in the hydrogen-powered ship digital twin",
        "Table 9. Ablation results for scanner combination, policy filtering, deduplication, and manual review",
        "Table 10. Sensitivity of repository ranking to score model and weights",
        "Table 11. Repository- and lineage-level Fisher exact comparisons of automated CWE profiles",
    ):
        if required not in all_text:
            raise AssertionError(f"required evidence missing: {required}")

    for stale_reference in ("제3.3절", "제3.3.2절", "제4.5절", "표 10의 축약 파일명"):
        if stale_reference in all_text:
            raise AssertionError(f"stale cross-reference remains: {stale_reference}")


def build(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    if not source.exists():
        raise FileNotFoundError(source)

    source_hash = sha256(source)
    document = Document(source)
    body = document._element.body
    nodes = [
        node
        for node in list(body)
        if node.tag not in (W_BOOKMARK_START, W_BOOKMARK_END)
    ]
    if nodes[-1].tag != W_SECT_PR:
        raise ValueError("document body does not end with sectPr")
    sect_pr = nodes[-1]
    nodes = nodes[:-1]

    indices = {
        text: unique_index(nodes, text)
        for text in (
            "3. 웹 기반 디지털트윈을 위한 보안성 측정 기법",
            "3.1 개요",
            "3.2 보안 취약점 탐지",
            "3.3 탐지 결과 정량화 및 판정",
            "3.3.1 보안 점수 산출",
            "3.3.2 환경 민감형 판정 모델",
            "4. 실험 및 결과",
            "4.1 실험 대상 및 환경",
            "4.2 OWASP Benchmark v1.2를 통한 탐지 정확도 검증",
            "4.3 디지털트윈 웹앱 보안성 측정 결과",
            "4.3.1 자동 탐지 결과의 수동 검증",
            "4.3.2 구성요소 제거 실험",
            "4.3.3 정책 기반 보조지수 민감도 분석",
            "4.4 수소추진선박 디지털트윈 심층 측정 사례",
            "4.4.1 아키텍처",
            "4.4.2 탐지 결과",
            "4.4.3 DT 문맥 해석",
            "4.5 DT와 검증용 취약 웹앱의 저장소 단위 CWE 탐지 프로파일 비교",
            "5. 결론 및 향후 연구",
            "부록 A. 고정 커밋 및 재현성 산출물",
        )
    }

    def section(start: str, end: str) -> list:
        return nodes[indices[start] : indices[end]]

    prefix = nodes[: indices["3. 웹 기반 디지털트윈을 위한 보안성 측정 기법"]]
    chapter3 = nodes[indices["3. 웹 기반 디지털트윈을 위한 보안성 측정 기법"]]
    section31 = section("3.1 개요", "3.2 보안 취약점 탐지")
    section32 = section("3.2 보안 취약점 탐지", "3.3 탐지 결과 정량화 및 판정")
    section33_parent = section("3.3 탐지 결과 정량화 및 판정", "3.3.1 보안 점수 산출")
    section331 = section("3.3.1 보안 점수 산출", "3.3.2 환경 민감형 판정 모델")
    section332 = section("3.3.2 환경 민감형 판정 모델", "4. 실험 및 결과")

    chapter4 = nodes[indices["4. 실험 및 결과"]]
    section41 = section("4.1 실험 대상 및 환경", "4.2 OWASP Benchmark v1.2를 통한 탐지 정확도 검증")
    section42 = section(
        "4.2 OWASP Benchmark v1.2를 통한 탐지 정확도 검증",
        "4.3 디지털트윈 웹앱 보안성 측정 결과",
    )
    section43_intro = section(
        "4.3 디지털트윈 웹앱 보안성 측정 결과",
        "4.3.1 자동 탐지 결과의 수동 검증",
    )
    section431 = section("4.3.1 자동 탐지 결과의 수동 검증", "4.3.2 구성요소 제거 실험")
    section432 = section("4.3.2 구성요소 제거 실험", "4.3.3 정책 기반 보조지수 민감도 분석")
    section433 = section(
        "4.3.3 정책 기반 보조지수 민감도 분석",
        "4.4 수소추진선박 디지털트윈 심층 측정 사례",
    )
    section44_parent = section(
        "4.4 수소추진선박 디지털트윈 심층 측정 사례",
        "4.4.1 아키텍처",
    )
    section441 = section("4.4.1 아키텍처", "4.4.2 탐지 결과")
    section442 = section("4.4.2 탐지 결과", "4.4.3 DT 문맥 해석")
    section443 = section(
        "4.4.3 DT 문맥 해석",
        "4.5 DT와 검증용 취약 웹앱의 저장소 단위 CWE 탐지 프로파일 비교",
    )
    section45 = section(
        "4.5 DT와 검증용 취약 웹앱의 저장소 단위 CWE 탐지 프로파일 비교",
        "5. 결론 및 향후 연구",
    )
    section5 = section("5. 결론 및 향후 연구", "부록 A. 고정 커밋 및 재현성 산출물")
    suffix = nodes[indices["부록 A. 고정 커밋 및 재현성 산출물"] :]

    heading_template = section331[0]
    heading_style = style_of(heading_template)
    body_template = unique_startswith(nodes, "전체 프로세스는 그림 1과 같다.")

    # Chapter 3: overview -> detailed detection -> normalization and decision.
    set_paragraph_text(section32[0], "3.2 상세 절차")
    heading321 = clone_paragraph(
        heading_template,
        "3.2.1 보안 취약점 탐지 단계",
        style=heading_style,
    )
    set_paragraph_text(section33_parent[0], "3.2.2 탐지 결과 정규화 및 보안성 판정 단계")
    set_paragraph_text(section331[0], "정책 기반 보조지수 산출.", bold=True)
    set_style(section331[0], "BodyText")
    set_paragraph_text(section332[0], "환경 민감형 배포 판정.", bold=True)
    set_style(section332[0], "BodyText")

    # Chapter 4.1: keep the same three datasets but foreground the DT systems.
    set_paragraph_text(chapter4, "4. 웹 기반 디지털트윈의 보안성 측정 사례 및 검증")
    set_paragraph_text(section41[0], "4.1 분석 대상 웹 기반 디지털트윈")
    target_intro = unique_startswith(section41, "실험 대상은 세 그룹으로 구성된다.")
    vulnerable_apps = unique_startswith(section41, "검증용 취약 웹앱(8개):")
    public_dt = unique_startswith(section41, "공개 DT 웹앱(14개):")
    hydrogen_dt = unique_startswith(section41, "수소추진선박 DT(1개):")
    environment = unique_startswith(section41, "실험은 Ubuntu")
    loc_method = unique_startswith(section41, "저장소당 프로그래밍 언어 비공백 LOC는")
    table4_caption = unique_startswith(section41, "Table 4.")
    table4 = direct_tables(section41)
    if len(table4) != 1:
        raise ValueError(f"section 4.1: expected one table, found {len(table4)}")
    set_paragraph_text(
        target_intro,
        "본 연구의 분석 대상은 공개 DT 웹앱 14개와 수소추진선박 DT 1개이며, "
        "탐지 정확도 평가와 CWE 프로파일 비교를 위해 검증용 취약 웹앱 8개를 함께 사용하였다.",
    )
    target_nodes = [
        section41[0],
        target_intro,
        public_dt,
        table4_caption,
        table4[0],
        hydrogen_dt,
        vulnerable_apps,
    ]

    # Chapter 4.2: environment and the validation design already used by the paper.
    heading42 = clone_paragraph(
        section42[0],
        "4.2 실험 환경 및 검증 방법",
        style=style_of(section42[0]),
    )
    validation_design = clone_paragraph(
        body_template,
        "검증 절차는 세 부분으로 구성하였다. 첫째, OWASP Benchmark v1.2와 정책이 중첩되는 "
        "6개 CWE에서 탐지 정확도를 평가하였다. 둘째, 공개 DT 14개에서 자동 탐지, 정확 위치 "
        "중복 제거 및 수동 판독 결과를 비교하였다. 셋째, 구성요소 제거, 보조지수 민감도 및 "
        "저장소·코드 계보 단위 프로파일 비교를 통해 결과의 안정성과 적용 범위를 분석하였다.",
        style="BodyText",
    )

    # Chapter 4.3: accuracy, public-DT results, and the deep DT case.
    set_paragraph_text(section43_intro[0], "4.3 취약점 탐지 결과 및 유형")
    set_paragraph_text(section42[0], "4.3.1 OWASP Benchmark v1.2 기반 탐지 정확도")
    set_paragraph_text(section431[0], "4.3.2 공개 디지털트윈의 취약점 탐지 결과")
    manual_label = clone_paragraph(
        body_template,
        "자동 탐지 결과의 수동 판독.",
        style="BodyText",
        bold=True,
    )
    set_paragraph_text(section44_parent[0], "4.3.3 수소추진선박 디지털트윈 적용 사례")
    for part, label in (
        (section441, "시스템 구성."),
        (section442, "탐지 결과."),
        (section443, "디지털트윈 문맥 해석."),
    ):
        set_paragraph_text(part[0], label, bold=True)
        set_style(part[0], "BodyText")

    # Chapter 4.4: move diagnostic experiments and limitations into Discussion.
    heading44 = clone_paragraph(
        heading_template,
        "4.4 결과 분석 및 논의",
        style=heading_style,
    )
    set_paragraph_text(section432[0], "4.4.1 구성요소 제거 실험")
    set_paragraph_text(section433[0], "4.4.2 정책 기반 보조지수 민감도 분석")
    set_paragraph_text(section45[0], "4.4.3 DT와 검증용 취약 웹앱의 CWE 탐지 프로파일 비교")
    heading444 = clone_paragraph(
        heading_template,
        "4.4.4 타당성 위협 및 한계",
        style=heading_style,
    )
    limitation = unique_startswith(section5, "결과의 적용 범위는 다음과 같다.")
    section5_without_limitation = [node for node in section5 if node is not limitation]

    # Cross-references affected only by the structural move.
    replacements = (
        ("제3.1절 및 제3.2절", "제3.1절 및 제3.2.1절"),
        ("제4.2절 및 제4.3절", "제4.3.1절 및 제4.3.2절"),
        ("제3.3절 및 제4.3.3절", "제3.2.2절 및 제4.4.2절"),
        ("제4.3절 및 제4.5절", "제4.3.2절 및 제4.4.3절"),
        ("제3.2절의 2단계 스캔 체계", "제3.2.1절의 2단계 스캔 체계"),
        ("제3.3절의 점수·판정 모델", "제3.2.2절의 점수·판정 모델"),
        ("제3.3.2절의 계층형 게이트", "본 절에서 후술하는 계층형 게이트"),
        ("제4.3.3절의 민감도 분석", "제4.4.2절의 민감도 분석"),
        ("제4.3.3절에서", "제4.4.2절에서"),
        ("제4.4절의 사례 분석", "제4.3.3절의 사례 분석"),
        ("제4.4절의 심층 사례 분석", "제4.3.3절의 심층 사례 분석"),
        ("제4.5절", "제4.4.3절"),
        ("표 7은 각 탐지의 정책 항목", "표 8은 각 탐지의 정책 항목"),
        ("표 10의 축약 파일명", "표 8의 축약 파일명"),
        (
            "Table 10. In-scope findings in the hydrogen-powered ship digital twin",
            "Table 8. In-scope findings in the hydrogen-powered ship digital twin",
        ),
        (
            "Table 8. Ablation results for scanner combination, policy filtering, deduplication, and manual review",
            "Table 9. Ablation results for scanner combination, policy filtering, deduplication, and manual review",
        ),
        (
            "Table 9. Sensitivity of repository ranking to score model and weights",
            "Table 10. Sensitivity of repository ranking to score model and weights",
        ),
    )
    for node in nodes:
        if node.tag != W_P:
            continue
        for old, new in replacements:
            replace_text(node, old, new)

    new_order = [
        *prefix,
        chapter3,
        *section31,
        section32[0],
        heading321,
        *section32[1:],
        section33_parent[0],
        *section331,
        *section332,
        chapter4,
        *target_nodes,
        heading42,
        environment,
        loc_method,
        validation_design,
        section43_intro[0],
        *section42,
        section431[0],
        *section43_intro[1:],
        manual_label,
        *section431[1:],
        section44_parent[0],
        *section441,
        *section442,
        *section443,
        heading44,
        *section432,
        *section433,
        *section45,
        heading444,
        limitation,
        *section5_without_limitation,
        *suffix,
        sect_pr,
    ]

    # Rebuild the body to make the order explicit and prevent accidental loss.
    for child in list(body):
        body.remove(child)
    for node in new_order:
        body.append(node)

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
    print("validated=tables:13 figure:1 sections:1 quantitative_evidence:preserved")


def main() -> None:
    source = Path(sys.argv[1]) if len(sys.argv) >= 2 else DEFAULT_SOURCE
    destination = Path(sys.argv[2]) if len(sys.argv) >= 3 else DEFAULT_DESTINATION
    if len(sys.argv) > 3:
        raise SystemExit(f"usage: {Path(sys.argv[0]).name} [SOURCE.docx] [DESTINATION.docx]")
    build(source, destination)


if __name__ == "__main__":
    main()
