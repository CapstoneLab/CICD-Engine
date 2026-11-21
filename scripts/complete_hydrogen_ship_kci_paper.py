#!/usr/bin/env python3
"""Build the argument-flow revision of the hydrogen-ship DT CI/CD manuscript.

The user's Chapters 1 through 2.3 are retained, except for minimal terminology
normalization and completion of the explicitly unfinished contribution section.
Chapters 3 through 5 are written from the frozen experiment evidence and follow
the problem-gap-method-evidence-interpretation flow used in Korean KCI journals.
"""

from __future__ import annotations

import hashlib
import sys
import tempfile
import zipfile
from copy import deepcopy
from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt
from lxml import etree
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "수소추진선박 디지털트윈 CI_CD 논문.docx"
REFERENCE_DOC = ROOT / "웹 기반 디지털트윈_KCI_최종제출본_코드문맥검토.docx"
DEFAULT_DESTINATION = ROOT / "수소추진선박 디지털트윈 CI_CD 논문_KCI논증개정본.docx"
FIGURE_PATH = ROOT / "figures" / "SecuPipeline_코드문맥검토_프로세스.png"
FONT = "Noto Sans CJK KR"
FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc")
BOLD_FONT_PATH = Path("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc")


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


def set_run_font(run, size: float | None = None, bold: bool | None = None) -> None:
    run.font.name = FONT
    run._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), FONT)
    if size is not None:
        run.font.size = Pt(size)
    if bold is not None:
        run.bold = bold


def find_paragraph(document: Document, text: str, *, startswith: bool = False):
    if startswith:
        matches = [p for p in document.paragraphs if p.text.startswith(text)]
    else:
        matches = [p for p in document.paragraphs if p.text == text]
    if len(matches) != 1:
        raise ValueError(f"paragraph {text!r}: expected 1, found {len(matches)}")
    return matches[0]


def delete_paragraph(paragraph) -> None:
    element = paragraph._element
    parent = element.getparent()
    if parent is not None:
        parent.remove(element)
    paragraph._p = paragraph._element = None


def paragraph_index(document: Document, target) -> int:
    return next(
        index
        for index, paragraph in enumerate(document.paragraphs)
        if paragraph._p is target._p
    )


def insert_after(paragraph, text: str, style: str = "normal"):
    new_p = OxmlElement("w:p")
    paragraph._p.addnext(new_p)
    from docx.text.paragraph import Paragraph

    inserted = Paragraph(new_p, paragraph._parent)
    inserted.style = style
    clear_and_set(inserted, text)
    return inserted


def add_paragraph(
    document: Document,
    text: str,
    *,
    style: str = "normal",
    bold: bool = False,
    align=None,
):
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(text)
    set_run_font(run, bold=bold)
    if align is not None:
        paragraph.alignment = align
    return paragraph


def add_heading(document: Document, text: str, style: str):
    paragraph = document.add_paragraph(style=style)
    run = paragraph.add_run(text)
    set_run_font(run, bold=True)
    return paragraph


def add_caption(document: Document, text: str):
    paragraph = add_paragraph(
        document,
        text,
        style="normal",
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    for run in paragraph.runs:
        run.font.size = Pt(9)
    return paragraph


def append_reference_table(document: Document, reference: Document, index: int):
    anchor = document.add_paragraph()
    table_xml = deepcopy(reference.tables[index]._tbl)
    anchor._p.addprevious(table_xml)
    delete_paragraph(anchor)


def table_signature(table) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(cell.text for cell in row.cells)
        for row in table.rows
    )


def minimal_term_normalization(text: str) -> str:
    return (
        text.replace(
            "정량적 보안 점수와 배포 판정",
            "정책 기반 보조지수와 배포 제어 실행 상태",
        )
        .replace(
            "정량적 보안 점수 및 배포 판정",
            "정책 기반 보조지수 및 배포 제어 실행 상태",
        )
        .replace("정량적 보안 점수", "정책 기반 보조지수")
        .replace("배포 판정", "배포 제어 실행 상태")
        .replace("배포 제어 실행 상태으로", "배포 제어 실행 상태로")
        .replace("배포 제어 실행 상태을", "배포 제어 실행 상태를")
        .replace("F1-score", "F1-Score")
    )


def draw_centered_multiline(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: str,
    spacing: int = 12,
) -> None:
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing, align="center")
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    x = (box[0] + box[2] - width) / 2
    y = (box[1] + box[3] - height) / 2
    draw.multiline_text(
        (x, y),
        text,
        font=font,
        fill=fill,
        spacing=spacing,
        align="center",
    )


def draw_arrow(
    draw: ImageDraw.ImageDraw,
    start: tuple[int, int],
    end: tuple[int, int],
    color: str = "#465467",
    width: int = 9,
) -> None:
    draw.line((start, end), fill=color, width=width)
    ex, ey = end
    draw.polygon(
        [(ex, ey), (ex - 24, ey - 15), (ex - 24, ey + 15)],
        fill=color,
    )


def build_process_figure(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    image = Image.new("RGB", (2900, 1050), "white")
    draw = ImageDraw.Draw(image)
    title_font = ImageFont.truetype(str(BOLD_FONT_PATH), 66)
    box_font = ImageFont.truetype(str(BOLD_FONT_PATH), 40)
    state_font = ImageFont.truetype(str(BOLD_FONT_PATH), 34)
    note_font = ImageFont.truetype(str(FONT_PATH), 31)

    draw.text(
        (55, 40),
        "SecuPipeline 기반 웹 DT 보안 측정 및 배포 제어 절차",
        font=title_font,
        fill="#14213d",
    )

    colors = [
        ("#e8f1ff", "#2b6cb0"),
        ("#e7f7ef", "#25855f"),
        ("#f0eaff", "#6b46c1"),
        ("#fff4d9", "#b7791f"),
        ("#e6f6fa", "#187b91"),
        ("#ffe8e8", "#b83232"),
    ]
    labels = [
        "Repository\n고정 커밋",
        "보안 취약점 탐지\nGitleaks·Semgrep",
        "CWE 정책 매핑\n정확 위치 중복 제거",
        "코드 문맥 검토",
        "정책 기반 보조지수\n취약점 의사결정",
        "배포 제어\n실행 상태",
    ]
    boxes = []
    x = 55
    y1, y2 = 190, 500
    widths = [330, 380, 430, 350, 450, 380]
    for width, label, (fill, outline) in zip(widths, labels, colors, strict=True):
        box = (x, y1, x + width, y2)
        boxes.append(box)
        draw.rounded_rectangle(box, radius=28, fill=fill, outline=outline, width=7)
        draw_centered_multiline(draw, box, label, box_font, "#172033")
        x += width + 65
    for first, second in zip(boxes, boxes[1:]):
        draw_arrow(
            draw,
            (first[2] + 10, (first[1] + first[3]) // 2),
            (second[0] - 10, (second[1] + second[3]) // 2),
        )

    states = [
        ("BLOCK\n즉시 차단", "#ffe1e1", "#c53030"),
        ("BLOCK_PENDING_APPROVAL\n승인 후 재개", "#ffe8d5", "#c05621"),
        ("WARN\n경고 후 계속", "#fff3c4", "#b7791f"),
        ("PASS\n배포 허용", "#dcfce7", "#168344"),
    ]
    state_y1, state_y2 = 670, 875
    sx = 190
    state_widths = [420, 650, 430, 390]
    state_centers = []
    cursor = sx
    for width in state_widths:
        state_centers.append(cursor + width // 2)
        cursor += width + 80
    hub_y = 590
    final_center_x = (boxes[-1][0] + boxes[-1][2]) // 2
    draw.line(
        (final_center_x, boxes[-1][3], final_center_x, hub_y),
        fill="#465467",
        width=9,
    )
    draw.line(
        (state_centers[0], hub_y, final_center_x, hub_y),
        fill="#465467",
        width=9,
    )
    for center_x in state_centers:
        draw.line(
            (center_x, hub_y, center_x, state_y1 - 12),
            fill="#465467",
            width=9,
        )
        draw.polygon(
            [
                (center_x, state_y1),
                (center_x - 15, state_y1 - 25),
                (center_x + 15, state_y1 - 25),
            ],
            fill="#465467",
        )
    for (label, fill, outline), width in zip(states, state_widths, strict=True):
        box = (sx, state_y1, sx + width, state_y2)
        draw.rounded_rectangle(box, radius=25, fill=fill, outline=outline, width=6)
        draw_centered_multiline(draw, box, label, state_font, outline)
        sx += width + 80

    draw.text(
        (60, 950),
        "CWE 기반 보안 등급을 즉시·선택적 배포 차단 유형과 네 가지 배포 제어 실행 상태로 연결한다.",
        font=note_font,
        fill="#465467",
    )
    image.save(path, format="PNG", optimize=True)


def strip_comments(source_docx: Path, destination_docx: Path) -> None:
    w_ns = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    rel_ns = "http://schemas.openxmlformats.org/package/2006/relationships"
    ct_ns = "http://schemas.openxmlformats.org/package/2006/content-types"
    with zipfile.ZipFile(source_docx) as source, zipfile.ZipFile(
        destination_docx, "w", zipfile.ZIP_DEFLATED
    ) as destination:
        for item in source.infolist():
            name = item.filename
            if name in {
                "word/comments.xml",
                "word/commentsExtended.xml",
                "word/commentsIds.xml",
            }:
                continue
            data = source.read(name)
            if name == "word/document.xml":
                root = etree.fromstring(data)
                for local_name in (
                    "commentRangeStart",
                    "commentRangeEnd",
                    "commentReference",
                ):
                    for node in root.xpath(
                        f"//*[local-name()='{local_name}' and namespace-uri()='{w_ns}']"
                    ):
                        parent = node.getparent()
                        if parent is not None:
                            parent.remove(node)
                data = etree.tostring(
                    root,
                    xml_declaration=True,
                    encoding="UTF-8",
                    standalone="yes",
                )
            elif name == "word/_rels/document.xml.rels":
                root = etree.fromstring(data)
                for relationship in root.findall(f"{{{rel_ns}}}Relationship"):
                    if relationship.get("Type", "").endswith("/comments"):
                        root.remove(relationship)
                data = etree.tostring(
                    root,
                    xml_declaration=True,
                    encoding="UTF-8",
                    standalone="yes",
                )
            elif name == "[Content_Types].xml":
                root = etree.fromstring(data)
                for override in root.findall(f"{{{ct_ns}}}Override"):
                    if "comments" in override.get("PartName", ""):
                        root.remove(override)
                data = etree.tostring(
                    root,
                    xml_declaration=True,
                    encoding="UTF-8",
                    standalone="yes",
                )
            destination.writestr(item, data)


def add_abstract(document: Document) -> None:
    anchor = find_paragraph(document, "1. 서론")
    blocks = [
        (
            "Static Security Measurement and CI/CD Deployment Control for "
            "Hydrogen-Powered Ship Digital Twin Software",
            "normal",
            True,
        ),
        ("초록", "Heading 2", True),
        (
            "웹 기반 디지털트윈(Digital Twin, DT)은 3D 시각화와 실시간 센서 통신을 "
            "통해 물리 시스템의 상태를 제공하지만, 정적 분석 도구가 생성한 경고를 실제 "
            "배포 제어로 연결하는 절차는 충분히 제시되지 않았다. 본 연구는 수소추진선박 "
            "DT 소프트웨어를 대상으로 Gitleaks와 Semgrep의 경고를 16종 CWE 보안 정책 "
            "카탈로그에 매핑하고, 정확 위치 중복 제거와 코드 문맥 검토를 거쳐 정책 기반 "
            "보조지수와 네 가지 배포 제어 실행 상태를 산출하는 CI/CD 보안 파이프라인을 "
            "제안한다. 제안 절차는 OWASP Benchmark v1.2, 공개 DT 저장소 14개 및 "
            "수소추진선박 DT의 세 단계로 평가하였다. Benchmark의 정책 중첩 6개 CWE에서 "
            "정밀도 0.533, 재현율 0.772 및 F1-Score 0.630이 산출되었으며, CWE-327 "
            "130건은 탐지하지 못하였다. 공개 DT에서는 정책 적용 대상 274건이 정확 위치 "
            "220개로 축약되었고, 코드 문맥 검토 후 배포 제어 실행 상태는 BLOCK 8개, "
            "BLOCK_PENDING_APPROVAL 1개, WARN 2개 및 PASS 3개로 결정되었다. "
            "수소추진선박 DT에서는 평문 WebSocket과 동적 데이터 렌더링 경계가 각각 "
            "CWE-319와 CWE-79로 식별되어 보조지수 94/100과 "
            "BLOCK_PENDING_APPROVAL이 산출되었다. 이 결과는 자동 경고의 탐지 성능과 "
            "코드 문맥을 함께 고려할 때 정적 분석 결과를 추적 가능한 배포 의사결정으로 "
            "변환할 수 있음을 보여준다.",
            "normal",
            False,
        ),
        (
            "주제어: 수소추진선박, 디지털트윈, CI/CD 보안, 정적 애플리케이션 보안 "
            "테스팅, CWE 기반 보안 등급, 배포 제어",
            "normal",
            False,
        ),
        ("Abstract", "Heading 2", True),
        (
            "Web-based digital twins (DTs) expose physical-system states through 3D "
            "visualization and real-time sensor communication, yet a procedure for "
            "translating static-analysis alerts into deployment control remains "
            "underdeveloped. This study proposes a CI/CD security pipeline for "
            "hydrogen-powered ship DT software. The pipeline maps Gitleaks and Semgrep "
            "alerts to a 16-CWE security policy catalogue, removes exact-location "
            "duplicates, performs code-context review, and produces an auxiliary policy "
            "index and four deployment-control states. The procedure was evaluated in "
            "three stages: OWASP Benchmark v1.2, 14 public DT repositories, and the "
            "hydrogen-powered ship DT. For six policy-overlapping CWEs in the Benchmark, "
            "the frozen ruleset achieved 0.533 precision, 0.772 recall, and an F1-Score "
            "of 0.630, while all 130 CWE-327 cases remained undetected. In the public DT "
            "repositories, 274 policy-applied alerts were reduced to 220 unique "
            "locations, and the reviewed deployment states were eight BLOCK, one "
            "BLOCK_PENDING_APPROVAL, two WARN, and three PASS. In the ship DT, plaintext "
            "WebSocket communication and a dynamic rendering boundary were identified as "
            "CWE-319 and CWE-79, yielding an auxiliary index of 94/100 and "
            "BLOCK_PENDING_APPROVAL. The results show that static-analysis output can be "
            "converted into traceable deployment decisions when tool performance and code "
            "context are considered together.",
            "normal",
            False,
        ),
        (
            "Keywords: hydrogen-powered ship, digital twin, CI/CD security, static "
            "application security testing, CWE-based security level, deployment control",
            "normal",
            False,
        ),
    ]
    for text, style, bold in blocks:
        paragraph = anchor.insert_paragraph_before(style=style)
        run = paragraph.add_run(text)
        set_run_font(run, bold=bold)
        if text.startswith("Static Security"):
            paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER


def complete_contributions(document: Document) -> None:
    placeholder = find_paragraph(document, "기여점은 마지막에 작성 예정", startswith=True)
    clear_and_set(
        placeholder,
        "본 연구의 목적은 웹 기반 DT 소프트웨어에서 생성되는 정적 분석 경고를 일관된 "
        "배포 제어 정보로 변환하는 CI/CD 보안 파이프라인을 설계하고, 이를 수소추진선박 "
        "DT에 적용하여 실효성과 적용 범위를 평가하는 데 있다. 이를 위해 탐지 도구의 "
        "출력과 조직의 취약점 의사결정을 분리하고, 두 영역을 CWE 기반 정규화와 코드 "
        "문맥으로 연결하였다. 연구의 기여는 다음과 같다.",
    )
    p1 = insert_after(
        placeholder,
        "첫째, Gitleaks와 Semgrep의 이질적인 경고를 16종 CWE 보안 정책 카탈로그로 "
        "정규화하고, 정확 위치 중복 제거와 코드 문맥 검토를 거쳐 취약점 의사결정으로 "
        "연결하는 재현 가능한 처리 절차를 제안하였다.",
    )
    p2 = insert_after(
        p1,
        "둘째, CWE 기반 보안 등급을 정책 기반 보조지수와 "
        "BLOCK·BLOCK_PENDING_APPROVAL·WARN·PASS의 실행 상태로 변환하여, "
        "개발과 운영 환경에서 동일한 탐지 결과를 일관되게 처리할 수 있는 환경 민감형 "
        "배포 제어 규칙을 제시하였다.",
    )
    p3 = insert_after(
        p2,
        "셋째, OWASP Benchmark v1.2로 현재 룰셋의 기준 성능을 확인하고, 공개 DT "
        "14개와 수소추진선박 DT에 순차적으로 적용함으로써 탐지·정규화·검토·배포 제어 "
        "각 단계가 최종 결과에 미치는 영향을 실증하였다.",
    )
    insert_after(
        p3,
        "논문의 구성은 다음과 같다. 제2장에서는 DT 보안과 SAST 평가 연구를 검토하고 "
        "문제를 정의한다. 제3장에서는 제안하는 보안성 측정 절차를 설명하며, 제4장에서는 "
        "Benchmark, 공개 DT 및 수소추진선박 DT의 적용 결과를 제시하고 분석한다. "
        "제5장에서는 연구 결과와 한계 및 향후 연구 방향을 정리한다.",
    )


def remove_draft_after_2_3(document: Document) -> None:
    start = find_paragraph(document, "3. 웹 디지털트윈을 위한 보안성 측정 기법")
    paragraphs = document.paragraphs
    start_index = paragraph_index(document, start)
    for paragraph in list(paragraphs[start_index:]):
        delete_paragraph(paragraph)


def add_chapter_3(document: Document, reference: Document) -> None:
    add_heading(document, "3. 웹 디지털트윈을 위한 보안성 측정 기법", "Heading 3")
    add_heading(document, "3.1 개요", "Heading 4")
    add_paragraph(
        document,
        "정적 분석 도구를 CI/CD에 연결하는 것만으로는 웹 기반 DT의 배포 안전성을 "
        "판단하기 어렵다. 도구마다 탐지 범위와 심각도 체계가 다르고, 동일한 코드 위치가 "
        "여러 룰에서 반복 보고되며, 테스트 코드나 생성 코드의 경고가 운영 코드의 경고와 "
        "같은 수준으로 제시될 수 있기 때문이다. 국내 DevSecOps 연구도 다수의 점검 도구와 "
        "보안 메트릭을 통합할 필요성을 제시하였으나 [22-24], DT 구성요소의 문맥과 배포 "
        "환경을 함께 반영하는 실행 규칙까지 구체화한 연구는 제한적이다. 제안 절차는 "
        "이러한 보안 검토를 개발 단계로 이동시키는 shift-left 운영과 연결된다 [21].",
    )
    add_paragraph(
        document,
        "본 연구는 이러한 문제를 해결하기 위해 세 가지 설계 원칙을 적용하였다. 첫째, "
        "보안 취약점 탐지와 취약점 의사결정을 분리하여 도구의 원시 심각도가 곧바로 배포 "
        "차단을 결정하지 않도록 하였다. 둘째, 범용 CWE를 실시간 센서 채널, 원격 제어 "
        "API, 3D 렌더링 및 Unity WebGL 생성 코드와 같은 DT 구성요소에 매핑하였다. "
        "셋째, 원시 경고에서 중복 제거, 코드 문맥 검토 및 최종 실행 상태까지의 변환 "
        "근거를 파일과 라인 단위로 추적하도록 하였다.",
    )
    add_paragraph(
        document,
        "그림 1과 같이 제안 절차는 고정 커밋 확보, 보안 취약점 탐지 단계(Security "
        "Scan Step), CWE 보안 정책 매핑, 정확 위치 중복 제거, 코드 문맥 검토, 정책 "
        "기반 보조지수 산출 및 취약점 의사결정(Vulnerability Decision-Making)의 순서로 "
        "진행된다. 앞 단계의 JSON 산출물이 다음 단계의 입력이 되며, 최종 결과는 BLOCK, "
        "BLOCK_PENDING_APPROVAL, WARN 및 PASS의 네 가지 배포 제어 실행 상태로 "
        "표현된다.",
    )
    picture_paragraph = document.add_paragraph()
    picture_paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    picture_paragraph.add_run().add_picture(str(FIGURE_PATH), width=Inches(6.8))
    add_caption(
        document,
        "Fig. 1. Security scan, code-context review, and four-state deployment-control process",
    )
    add_paragraph(
        document,
        "웹 기반 DT는 게임 엔진과 브라우저를 이용한 3D 표현, 실시간 모니터링 및 원격 "
        "제어 기능을 결합하는 형태로 구현된다 [25,26]. 이러한 구조에서는 동일한 웹 "
        "취약점이라도 센서 상태의 왜곡이나 제어 경계의 노출로 이어질 수 있으므로, "
        "구성요소별 보호 대상을 먼저 식별해야 한다. 이에 표 1은 DT 구성요소, 보안 검토 "
        "지점, 관련 CWE 및 배포 영향을 연결한다. 의료기기 DT 연구가 물리적 위해 가능성을 "
        "고려한 보안 요구사항의 선행 검사를 강조한 것과 같이 [29], 본 연구도 탐지 결과를 "
        "실제 DT 기능의 신뢰 경계에서 해석한다.",
    )
    add_caption(
        document,
        "Table 1. Mapping of DT components, security review points, policy coverage, and deployment impact",
    )
    append_reference_table(document, reference, 0)
    add_paragraph(
        document,
        "다만 이 매핑은 CWE를 DT 전용 취약점으로 재정의하는 것이 아니다. 현재 정책은 "
        "시크릿 노출, 입력 삽입, 권한, 전송 보호 및 출력 인코딩과 같이 소스 코드에서 "
        "확인할 수 있는 경계를 대상으로 한다. 반면 상태 동기화 무결성, 재전송 공격, "
        "센서 값의 의미적 타당성 및 물리 제어 안전성은 정적 분석만으로 확인할 수 없다. "
        "따라서 본 연구의 측정 결과는 선택한 정책 범위 안에서 검토 우선순위와 배포 "
        "제어를 지원하는 정보로 한정한다.",
    )

    add_heading(document, "3.2 상세 절차", "Heading 4")
    add_paragraph(
        document,
        "상세 절차는 탐지 항목을 생성하는 단계와 그 결과를 배포 제어 정보로 변환하는 "
        "단계로 구성된다. 제3.2.1절은 분석 대상을 고정하고 두 스캐너의 출력을 공통 "
        "스키마로 정규화하는 과정을 설명한다. 제3.2.2절은 정규화된 결과를 코드 문맥에서 "
        "검토하고, 정책 기반 보조지수와 배포 제어 실행 상태를 산출하는 과정을 설명한다.",
    )

    add_heading(document, "3.2.1 보안 취약점 탐지 단계", "Heading 5")
    add_paragraph(
        document,
        "분석의 첫 입력은 저장소 이름과 전체 커밋 SHA이다. 동일 저장소라도 시점에 따라 "
        "소스 코드와 의존성이 변하므로, 커밋을 고정한 뒤 스캐너 버전과 룰 번들의 "
        "해시값을 함께 기록하였다. 이 조건은 반복 실행에서 분석 대상과 탐지 규칙이 "
        "달라지는 것을 방지한다.",
    )
    add_paragraph(
        document,
        "보안 취약점 탐지 단계는 Gitleaks 기반 시크릿 탐지와 Semgrep 기반 정적 코드 "
        "분석으로 구성된다. Gitleaks v8.21.2 [19]는 API 키, 토큰, 비밀번호 및 개인키 패턴을 "
        "탐지하고, Semgrep v1.157.0은 고정된 1,074개 OSS 룰로 입력 흐름, 위험 함수 "
        "호출, 전송 설정 및 출력 경계를 분석한다. 여러 도구를 조합하면 탐지 범위를 "
        "보완할 수 있지만 [22], 도구별 CWE 지원 범위가 서로 다를 수 있으므로 [27] "
        "결과를 그대로 합산하지 않고 공통 스키마로 변환하였다.",
    )
    add_paragraph(
        document,
        "두 스캐너의 출력은 rule_id, CWE, file_path, line, scanner, "
        "policy_severity 및 in_scope 필드로 정규화한다. 이후 CWE 보안 정책 카탈로그와 "
        "대조하여 정책 적용 대상 탐지 항목과 정책 외 탐지 항목을 구분한다. 표 2의 "
        "카탈로그는 OWASP Top 10:2021 [17], CVSS v3.1 [18] 및 OWASP Risk Rating "
        "Methodology [20]의 질적 위험도 개념을 참고하였으며, Critical·High·Medium·Low "
        "각 4종으로 구성하였다. 여기서 CWE 기반 보안 등급은 도구가 부여한 심각도가 "
        "아니라 본 연구의 배포 정책에 따른 재분류 결과이다.",
    )
    add_caption(
        document,
        "Table 2. CWE-based security levels, scanners, observed rule IDs, and assignment basis",
    )
    append_reference_table(document, reference, 1)
    add_paragraph(
        document,
        "정규화 후에는 저장소·CWE·파일·라인의 조합을 정확 위치 키로 사용하여 서로 다른 "
        "룰이나 스캐너가 보고한 중복을 하나의 위치로 통합한다. 이때 테스트·예제·문서·생성 "
        "코드를 탐지 단계에서 제외하지 않는다. 사전 제외는 경고 수를 줄일 수 있지만, "
        "실제 배포 산출물에 포함되는 생성 코드나 예제 자격증명을 놓칠 수 있기 때문이다. "
        "대신 코드의 용도와 배포 관련성은 다음 단계에서 명시적으로 분류한다.",
    )

    add_heading(document, "3.2.2 취약점 탐지 결과 단계", "Heading 5")
    add_paragraph(
        document,
        "취약점 탐지 결과 단계는 정적 분석 경고를 최종 배포 제어 실행 상태로 변환하는 "
        "취약점 의사결정 단계이다. 정적 분석 도구의 성능은 규칙 지원 범위와 분석 방식에 "
        "따라 달라지므로 [27,28], 탐지 항목의 존재만으로 실제 취약점을 확정하지 않는다. "
        "정확 위치별 코드와 주변 호출 관계를 확인한 뒤 확인된 위험 패턴, 문맥 제한 패턴, "
        "오탐 및 중복의 네 범주로 분류한다. 동시에 production, CI/build, test, "
        "documentation/example 및 generated/tooling의 코드 문맥을 기록한다.",
    )
    add_paragraph(
        document,
        "확인된 위험 패턴은 위험 함수, 안전하지 않은 설정 또는 자격증명 내장 패턴이 "
        "코드에 존재하고 해당 위치가 실행·배포 경계와 연결됨을 의미한다. 문맥 제한 "
        "패턴은 테스트 토큰, 문서 예제 또는 고정 입력처럼 위험 구문은 존재하지만 현재 "
        "배포 문맥에서 영향이 제한되는 경우이다. 이 분류는 원격 악용 가능성이나 "
        "자격증명의 실제 유효성을 확정하는 절차가 아니라, 자동 경고가 배포 판단에 미치는 "
        "영향을 조정하는 절차이다.",
    )
    add_paragraph(
        document,
        "코드 문맥 검토 결과는 요약 지표와 실행 상태의 두 형태로 제시한다. 먼저 정책 "
        "기반 보조지수는 CWE 기반 보안 등급별 탐지 분포를 100점 형식으로 요약한다. "
        "보안 메트릭은 구현 단계의 결과를 유지보수 활동과 연결하는 관리 수단으로 활용할 "
        "수 있으나 [23], 단일 값이 소프트웨어의 절대적 보안 수준을 나타내지는 않는다. "
        "따라서 본 지수는 저장소 간 검토 우선순위를 보조하며 배포 허용 임계값으로 "
        "사용하지 않는다. 정확 위치 중복 제거 후 Critical, High, Medium 및 Low 건수를 "
        "각각 C_C, C_H, C_M 및 C_L로 두면 식 (1)과 식 (2)로 산출한다.",
    )
    add_paragraph(
        document,
        "D_H = min(5C_H, 19),   D_M = min(C_M, 4),   D_L = min(0.2C_L, 0.9)                     (1)",
        style="normal",
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    add_paragraph(
        document,
        "S = 100 − D_H − D_M − D_L  (C_C = 0);   "
        "S = max[0, min(40, 100 − 20C_C − D_H − D_M − D_L)]  (C_C ≥ 1)              (2)",
        style="normal",
        align=WD_ALIGN_PARAGRAPH.CENTER,
    )
    add_paragraph(
        document,
        "가중치 20·5·1·0.2와 상한 19·4·0.9는 상위 CWE 기반 보안 등급 한 건의 영향이 "
        "하위 등급의 누적에 의해 역전되지 않도록 설정하였다. 이 값은 실제 사고 손실이나 "
        "전문가 판단에서 추정한 위험값이 아니라 정책 운용을 위한 매개변수이다. 따라서 "
        "제4.4절에서는 가중치의 정답성을 주장하지 않고, 대안 가중치에서 저장소 순위와 "
        "배포 제어 결과가 얼마나 변하는지를 확인한다.",
    )
    add_caption(
        document,
        "Table 3. Severity weights, deduction caps, deployment-control types, and execution states",
    )
    append_reference_table(document, reference, 2)
    add_paragraph(
        document,
        "배포 여부는 보조지수와 분리하여 CWE 기반 보안 등급과 배포 환경으로 결정한다. "
        "Critical과 High는 즉시 배포 차단 유형으로, Medium과 Low는 선택적 배포 차단 "
        "유형으로 분류한다. 표 3은 등급별 감점과 차단 유형을 함께 제시하며, 표 4는 이를 "
        "네 가지 실행 상태로 구체화한다. BLOCK은 승인으로 해제할 수 없는 차단 상태이고, "
        "BLOCK_PENDING_APPROVAL은 파이프라인을 중단한 뒤 승인에 따라 재개할 수 있는 "
        "상태이다. WARN은 선택적 차단 조건이 현재 환경에서 활성화되지 않은 상태이며, "
        "PASS는 활성화된 차단 조건이 없는 상태이다.",
    )
    add_caption(
        document,
        "Table 4. Environment-sensitive deployment-control execution-state rules",
    )
    append_reference_table(document, reference, 3)
    add_paragraph(
        document,
        "본 실험 정책에서 Medium은 production·staging에서는 "
        "BLOCK_PENDING_APPROVAL, development·feature에서는 WARN으로 처리한다. Low는 "
        "선택적 배포 차단이 가능한 등급이지만 현재 정책에서는 차단 조건을 활성화하지 "
        "않아 보조지수에만 반영한다. 이러한 환경 분리는 CI/CD에서 자동화된 결과와 승인 "
        "절차를 연결하는 운영 구조 [30]를 보안 의사결정에 적용한 것이다.",
    )
    add_paragraph(
        document,
        "Algorithm 1. Environment-Sensitive Vulnerability Decision-Making and Deployment Control\n"
        "INPUT: C_C, C_H, C_M, C_L, C_H^approved, environment\n"
        "C_H^active ← max(0, C_H − C_H^approved)\n"
        "IF C_C ≥ 1 THEN BLOCK\n"
        "ELSE IF C_H^active ≥ 1 THEN BLOCK_PENDING_APPROVAL\n"
        "ELSE IF C_M ≥ 1 AND environment ∈ {production, staging} THEN BLOCK_PENDING_APPROVAL\n"
        "ELSE IF C_M ≥ 1 THEN WARN\n"
        "ELSE PASS",
    )
    add_paragraph(
        document,
        "Algorithm 1은 Critical, 승인되지 않은 High, 환경별 Medium의 순서로 실행 "
        "상태를 결정한다. 코드 문맥 검토 전에는 자동 탐지 건수로 예비 상태를 산출하고, "
        "검토 후에는 중복과 오탐을 제외한 활성 건수로 상태를 갱신한다. 이와 같이 탐지 "
        "결과, 요약 지표 및 배포 상태를 분리함으로써 보조지수가 높더라도 High가 남아 "
        "있으면 승인 전 배포를 중단하고, 반대로 다수의 중복 경고가 최종 판단을 과도하게 "
        "지배하지 않도록 하였다.",
    )


def add_chapter_4(document: Document, reference: Document) -> None:
    add_heading(document, "4. 웹 기반 디지털트윈의 보안성 측정 사례", "Heading 3")
    add_heading(document, "4.1 웹 기반 디지털트윈 소개", "Heading 4")
    add_paragraph(
        document,
        "제안 기법의 적용 대상은 액체수소 이송 시스템의 상태를 실시간으로 모니터링하는 "
        "수소추진선박 DT(hydrogen-ship-LBTS)이다. 프론트엔드는 React UI와 Unity "
        "WebGL 런타임으로 구성되며, Unity 런타임은 3D 선박 모델을 렌더링하고 "
        "WebSocket을 통해 센서 데이터를 송수신한다. 백엔드는 Node.js/Express API "
        "서버로 구성되고 Kubernetes 매니페스트를 통해 배포된다. 따라서 이 사례는 "
        "제3장에서 정의한 3D 렌더링, 실시간 통신, 데이터 표현 및 배포 구성의 보안 "
        "검토 지점을 모두 포함한다.",
    )
    add_paragraph(
        document,
        "평가는 세 단계로 구성하였다. 첫 번째 단계에서는 OWASP Benchmark v1.2로 현재 "
        "룰셋의 CWE별 기준 탐지 성능을 확인하였다. 두 번째 단계에서는 공개 DT 저장소 "
        "14개에 동일한 절차를 적용하여 정책 필터링, 정확 위치 중복 제거 및 코드 문맥 "
        "검토가 탐지량과 배포 제어 실행 상태를 어떻게 바꾸는지 분석하였다. 세 번째 "
        "단계에서는 수소추진선박 DT의 실제 코드 위치를 중심으로 탐지 결과와 개선 방향을 "
        "해석하였다. 이와 같은 구성은 도구 성능, 절차의 동작 및 실제 사례 적용을 서로 "
        "분리하여 평가하기 위한 것이다.",
    )
    add_paragraph(
        document,
        "공개 DT 14개는 웹 기반 DT 코드가 확인되는 저장소를 목적표본으로 선정하였다. "
        "표본에는 애플리케이션, 데모, 플랫폼 및 라이브러리가 포함되며, 분석 규모는 "
        "1,407~517,862 LOC로 차이가 크다. 표 5에는 이러한 이질성을 결과 해석에 반영할 "
        "수 있도록 저장소 유형, 주 언어, LOC 및 코드 계보를 함께 제시하였다.",
    )
    add_caption(
        document,
        "Table 5. Repository type, analyzed code size, primary language, and code lineage",
    )
    append_reference_table(document, reference, 4)
    add_paragraph(
        document,
        "추가로 취약 웹앱 8개는 자동 CWE 탐지 프로파일의 차이를 탐색하기 위한 보조 "
        "집합으로 사용하였다. 이 집합은 의도적으로 취약하게 제작되었으므로 일반 웹 "
        "애플리케이션의 대표 표본으로 보지 않았으며, DT와 일반 웹앱의 보안 수준을 "
        "비교하는 핵심 검증 자료로 사용하지 않았다.",
    )

    add_heading(document, "4.2 실험 환경", "Heading 4")
    add_paragraph(
        document,
        "실험은 Ubuntu 26.04 LTS, Intel N95 4코어(최대 3.40 GHz) 및 메모리 7 GiB "
        "환경에서 수행하였다. 분석 도구는 Semgrep v1.157.0과 Gitleaks v8.21.2이며, "
        "공개 DT 14개에는 동일한 16개 CWE 정책과 development 환경을 적용하였다. "
        "Semgrep core 룰 번들의 SHA-256은 574df0e5…a669e이고 Gitleaks 설정의 "
        "SHA-256은 2ce9d818…430bb이다. 전체 커밋과 도구 식별자는 부록 A에 제시하였다.",
    )
    add_paragraph(
        document,
        "분석 범위에는 테스트, 예제 및 생성 코드를 포함하였고 명시적 제외 경로는 두지 "
        "않았다. 다만 집계 과정에서는 파이프라인 엔진이 삽입한 "
        ".localci/workflow.yml을 제외하였다. LOC는 Semgrep이 실제로 분석한 "
        "프로그래밍 언어 파일의 비공백 행으로 계산하였으며 JSON, YAML 및 데이터 파일은 "
        "제외하였다. 저장소 규모가 탐지량에 미치는 영향을 확인한 결과, 14개 DT의 LOC와 "
        "정책 적용 대상 자동 탐지 항목 수의 Spearman 상관은 ρ=0.811이었다.",
    )
    add_paragraph(
        document,
        "Benchmark 평가는 정답표와 정책이 중첩되는 CWE-22, CWE-78, CWE-79, CWE-89, "
        "CWE-327 및 CWE-614를 대상으로 하였다. 테스트 케이스 ID와 CWE가 모두 일치할 "
        "때 TP로 집계하고, TP·FP·FN으로 정밀도, 재현율 및 F1-Score를 산출하였다. "
        "정적 분석 도구의 규칙별 성능 차이를 평가할 때 이러한 혼동행렬 기반 지표를 "
        "사용할 수 있다 [28]. 공개 DT에서는 Critical 69건과 High 8건을 모두 "
        "검토하였다. Medium은 CWE-79 6건 전체와 CWE-22 191건 중 난수 시드 "
        "20260723으로 비복원 추출한 24건을 검토하였다.",
    )

    add_heading(document, "4.3 취약점 탐지 유형", "Heading 4")
    add_paragraph(document, "OWASP Benchmark 기준 성능.", bold=True)
    add_paragraph(
        document,
        "표 6과 같이 정책 중첩 6개 CWE의 마이크로 합계는 TP 728, FP 639, FN 215로 "
        "집계되었다. 이에 따른 정밀도는 0.533, 재현율은 0.772, F1-Score는 0.630이다. "
        "따라서 현재 룰셋은 실제 취약 사례의 약 77%를 탐지했지만, 경고 가운데 정답과 "
        "일치한 비율은 약 53%였다. 이 값은 다른 도구와의 우열이 아니라 이후 DT 분석 "
        "결과를 해석하기 위한 기준 성능이다.",
    )
    add_caption(document, "Table 6. Detection accuracy on OWASP Benchmark v1.2")
    append_reference_table(document, reference, 5)
    add_paragraph(
        document,
        "CWE별 결과에는 큰 차이가 있었다. CWE-22, CWE-78 및 CWE-89의 재현율은 각각 "
        "0.902, 0.929 및 0.930이었고 CWE-614는 정밀도와 재현율이 모두 1.000이었다. "
        "반면 CWE-327은 TP=0, FN=130으로 실제 취약 사례를 하나도 탐지하지 못하였다. "
        "표 7의 룰 단위 분석에서도 광범위한 데이터 흐름 조건과 여러 룰의 중복 보고가 "
        "FP를 증가시키는 원인으로 확인되었다. 즉 정책 카탈로그에 CWE가 포함되어 있다는 "
        "사실과 해당 CWE를 충분히 탐지할 수 있다는 사실은 구분해야 한다.",
    )
    add_caption(
        document,
        "Table 7. Rule-level diagnostic analysis of OWASP Benchmark detections",
    )
    append_reference_table(document, reference, 6)

    add_paragraph(document, "공개 디지털트윈 탐지 유형.", bold=True)
    add_paragraph(
        document,
        "공개 DT 14개에서는 원시 탐지 482건이 생성되었다. 정책 카탈로그와의 매핑 후 "
        "274건은 정책 적용 대상 탐지 항목으로, 208건은 정책 외 탐지 항목으로 "
        "분리되었다. 정책 적용 대상의 자동 CWE 기반 보안 등급은 Critical 69건, High "
        "8건 및 Medium 197건이었으며, 정확 위치 중복 제거 후에는 220개 위치가 남았다. "
        "이 결과는 정책 필터링이 분석 범위를 정하고, 중복 제거가 동일 위치의 반복 경고를 "
        "줄이는 역할을 수행했음을 보여준다.",
    )
    add_caption(
        document,
        "Table 8. Automatic, deduplicated, and code-context-review-adjusted DT results",
    )
    append_reference_table(document, reference, 7)
    add_paragraph(
        document,
        "정확 위치 기준으로 Critical·High 72개, CWE-79 6개 및 CWE-22 표본 23개 등 "
        "총 101개 위치를 코드 문맥에서 검토하였다. Critical·High 72개 중 확인된 위험 "
        "패턴은 31개(43.1%)였고, 확인된 위험 패턴과 문맥 제한 패턴을 합하면 "
        "53개(73.6%)였다. 테스트 토큰, 문서 예제, 고정 명령, 안전한 spawn 인자 배열 "
        "및 binary Buffer 응답은 문맥 제한 또는 오탐으로 분류되었다. 그 결과 자동 실행 "
        "상태 PASS 3개, WARN 1개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 9개는 코드 "
        "문맥 검토 후 PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개로 "
        "변경되었다.",
    )
    add_caption(document, "Table 9. Code-context review of automated DT findings")
    append_reference_table(document, reference, 8)

    add_paragraph(document, "수소추진선박 디지털트윈 탐지 유형.", bold=True)
    add_paragraph(
        document,
        "수소추진선박 DT의 development 환경 분석에서는 정책 적용 대상 탐지 항목으로 "
        "Unity WebGL 생성 코드의 평문 WebSocket(CWE-319)과 React 구성요소의 "
        "dangerouslySetInnerHTML 사용(CWE-79)이 식별되었다. 두 항목을 정책에 적용한 "
        "결과 정책 기반 보조지수 94/100이 산출되었으나 High 등급인 CWE-319가 "
        "존재하므로 배포 제어 "
        "실행 상태는 BLOCK_PENDING_APPROVAL로 결정되었다. 이는 보조지수와 배포 제어를 "
        "분리한 설계가 실제 사례에서 어떻게 작동하는지를 보여준다.",
    )
    add_caption(
        document,
        "Table 10. Policy-applied findings in the hydrogen-powered ship digital twin",
    )
    append_reference_table(document, reference, 9)
    add_paragraph(
        document,
        "CWE-319는 BuildWeb.framework.js의 ws:// 연결 문자열에서 확인되었다. 이 "
        "파일은 Unity가 생성한 산출물이므로 파일을 직접 수정하기보다 Unity 빌드 설정과 "
        "리버스 프록시에서 wss://를 강제하고 센서 채널의 인증서와 전송 보호를 적용해야 "
        "한다. CWE-79는 FuelEmission.tsx가 연료 배출량 데이터를 "
        "dangerouslySetInnerHTML로 렌더링하는 위치에서 확인되었다. 센서 데이터의 신뢰 "
        "경계를 정의하고 DOM 정제 또는 안전한 텍스트 렌더링으로 변경할 필요가 있다.",
    )
    add_paragraph(
        document,
        "정책 외 탐지 항목으로는 Subresource Integrity 누락(CWE-353), 정규표현식 "
        "DoS(CWE-1333), runAsNonRoot 설정(CWE-250), Kubernetes 권한 설정(CWE-732) "
        "및 CSRF 미들웨어(CWE-352) 관련 5건이 별도로 식별되었다. 이 항목은 현재 "
        "16종 정책의 배포 차단 조건에는 사용하지 않았지만, 파이프라인이 정책 범위 밖의 "
        "경고를 폐기하지 않고 후속 인프라·런타임 검토 대상으로 보존함을 보여준다.",
    )

    add_heading(document, "4.4 분석", "Heading 4")
    add_paragraph(
        document,
        "첫째, Benchmark 결과는 자동 탐지와 취약점 의사결정 사이에 검토 단계가 필요한 "
        "이유를 보여준다. 재현율 0.772는 고정 룰셋이 정책 중첩 취약 사례의 상당 부분을 "
        "탐지했음을 의미하지만, 정밀도 0.533은 자동 경고의 약 절반만 정답과 "
        "일치하였음을 나타낸다. 더욱이 CWE-327은 130건을 모두 놓쳤다. 따라서 자동 "
        "탐지 건수를 곧바로 취약점 수로 해석하면 오탐과 미탐을 동시에 간과하게 된다. "
        "제안 절차는 기준 성능을 먼저 제시하고 코드 문맥 검토 후 실행 상태를 갱신함으로써 "
        "이 문제를 완화한다.",
    )
    add_paragraph(
        document,
        "둘째, 구성요소 제거 실험은 각 처리 단계의 기능이 서로 다름을 보여준다. "
        "Gitleaks를 결합하자 Semgrep 단독 분석보다 자동 BLOCK 저장소가 5개에서 9개로 "
        "증가하여 시크릿 탐지의 보완 효과가 나타났다. 16종 정책 필터는 원시 탐지 "
        "482건을 274건으로 줄여 배포 정책의 관심 범위를 형성하였다. 정확 위치 중복 "
        "제거는 다시 54건을 줄였지만 저장소별 실행 상태는 바꾸지 않았다. 반면 코드 문맥 "
        "검토는 DT6의 상태를 BLOCK에서 WARN으로 변경하였다. 즉 스캐너 결합은 탐지 "
        "범위를 넓히고, 정책과 중복 제거는 검토량을 조정하며, 코드 문맥 검토는 실제 배포 "
        "의사결정을 교정하는 역할을 수행하였다.",
    )
    add_caption(
        document,
        "Table 11. Ablation results for scanner combination, policy filtering, deduplication, "
        "and deployment-control execution states after code-context review",
    )
    append_reference_table(document, reference, 10)
    add_paragraph(
        document,
        "셋째, 정책 기반 보조지수는 제한된 범위에서 순위 안정성을 보였다. 상한 제거, "
        "단순 고유 위치 건수, CVSS 질적 구간 중앙값 및 두 가지 대안 가중치와 비교한 "
        "결과, 세 계층형 가중치 조합의 저장소 순위상관은 ρ=0.999였고 14개 저장소의 "
        "실행 상태도 변하지 않았다. 이는 20·5·1·0.2를 소폭 변경해도 이번 표본의 "
        "우선순위가 유지된다는 의미이다. 그러나 이 결과는 해당 가중치가 실제 위험의 "
        "크기를 정확히 나타낸다는 증거가 아니므로, 보조지수를 절대적 보안 점수로 "
        "해석해서는 안 된다.",
    )
    add_caption(
        document,
        "Table 12. Sensitivity of repository ranking to score model and weights",
    )
    append_reference_table(document, reference, 11)
    add_paragraph(
        document,
        "넷째, 수소추진선박 사례는 제안 기법의 DT 적용성이 탐지 도구 자체보다 결과 해석 "
        "계층에서 형성됨을 보여준다. 평문 WebSocket은 실시간 센서 채널의 전송 보호 "
        "문제로, 동적 HTML 렌더링은 센서 데이터가 DOM에 도달하는 출력 경계의 문제로 "
        "해석되었다. 이는 일반 웹 CWE를 단순 집계한 결과보다 DT 구성요소와 코드 위치를 "
        "연결한 정보가 개선 조치를 결정하는 데 유용함을 의미한다. 다만 현재 기법은 "
        "상태 동기화 무결성이나 물리 제어 명령의 안전 조건을 직접 검사하지 않으므로, "
        "DT 전용 보안 검증 전체를 대체하지는 않는다.",
    )
    add_paragraph(
        document,
        "취약 웹앱 8개와 공개 DT 14개의 CWE 프로파일 비교는 이러한 적용 범위를 "
        "탐색적으로 확인하기 위한 분석이다. DT 저장소를 10개 코드 계보로 축약한 결과도 "
        "함께 제시하였으나, 표 13의 Fisher 정확 검정과 Odds Ratio는 의도적으로 취약한 "
        "비교군과 코드 규모·언어·저장소 유형의 차이를 제거하지 못한다. 따라서 이를 DT와 "
        "일반 웹 애플리케이션 모집단의 차이로 일반화하지 않고, 후속 매칭 연구에서 검증할 "
        "가설 후보로 해석한다.",
    )
    add_caption(
        document,
        "Table 13. Repository- and lineage-level Fisher exact comparisons of automated CWE profiles",
    )
    append_reference_table(document, reference, 12)
    add_paragraph(
        document,
        "분석 결과를 해석할 때에는 다음의 한계를 고려해야 한다. Benchmark 평가는 정책과 "
        "중첩되는 6개 CWE에 한정되며, Medium CWE-22는 191건 중 24건만 표본으로 "
        "검토하였다. 자격증명의 유효성 확인과 실제 공격 재현은 수행하지 않았다. 공개 DT "
        "14개는 확률표본이 아니고 저장소 유형과 코드 규모가 이질적이다. 또한 정적 분석은 "
        "런타임 도달 가능성, 재전송 공격, 센서 값의 의미적 타당성 및 물리 제어 안전성을 "
        "직접 검증하지 못한다. 그러므로 본 결과는 코드 수준의 배포 보조 정보이며 "
        "수소추진 시스템의 기능 안전성 보증으로 일반화할 수 없다.",
    )


def add_chapter_5_and_appendix(document: Document, reference: Document) -> None:
    add_heading(document, "5. 결론 및 향후 연구", "Heading 3")
    add_paragraph(
        document,
        "본 연구는 웹 기반 DT 소프트웨어의 정적 분석 경고를 실제 CI/CD 배포 제어로 "
        "연결하기 위해 탐지와 취약점 의사결정을 분리한 보안성 측정 절차를 제안하였다. "
        "Gitleaks와 Semgrep의 결과를 16종 CWE 보안 정책 카탈로그로 정규화하고, 정확 "
        "위치 중복 제거와 코드 문맥 검토를 거쳐 정책 기반 보조지수 및 네 가지 배포 제어 "
        "실행 상태를 산출하였다. 이 과정에서 DT의 특성은 별도의 전용 스캐너가 아니라 "
        "실시간 센서 채널, 데이터 렌더링, 원격 제어 및 생성 코드와 CWE를 연결하는 해석 "
        "계층에 반영하였다.",
    )
    add_paragraph(
        document,
        "평가 결과, OWASP Benchmark의 정책 중첩 6개 CWE에서 정밀도 0.533, 재현율 "
        "0.772 및 F1-Score 0.630이 산출되었고 CWE-327의 미탐 영역이 확인되었다. "
        "공개 DT 14개에서는 원시 경고 482건이 정책 적용 대상 274건과 정확 위치 "
        "220개로 단계적으로 정리되었으며, 코드 문맥 검토 후 실행 상태는 BLOCK 8개, "
        "BLOCK_PENDING_APPROVAL 1개, WARN 2개 및 PASS 3개로 결정되었다. 이 결과는 "
        "정책과 중복 제거가 검토 범위를 줄이고, 코드 문맥 검토가 배포 의사결정을 "
        "교정한다는 점을 보여준다.",
    )
    add_paragraph(
        document,
        "수소추진선박 DT에서는 Unity WebGL 생성 코드의 평문 WebSocket과 React의 "
        "동적 데이터 렌더링 경계가 각각 CWE-319와 CWE-79로 식별되었다. 보조지수는 "
        "94/100이었지만 High 항목이 존재하므로 실행 상태는 "
        "BLOCK_PENDING_APPROVAL로 결정되었다. 이는 단일 점수만으로 배포 여부를 "
        "판단하지 않고, 심각도·환경·코드 문맥을 함께 사용하는 제안 절차의 운용적 의미를 "
        "보여준다.",
    )
    add_paragraph(
        document,
        "향후 연구에서는 첫째, 현재 표본 검토에 그친 Medium 항목 전체를 분석하고 "
        "자격증명 유효성 및 생성 코드의 런타임 도달 가능성을 확인할 필요가 있다. 둘째, "
        "SCA, DAST, 컨테이너 이미지 및 Kubernetes 구성 검사를 결합하여 정적 분석의 "
        "미탐 영역과 DT의 상태 동기화·재전송·물리 제어 경계를 보완해야 한다. 셋째, DT와 "
        "일반 운영 웹 애플리케이션을 언어, 코드 규모 및 저장소 유형별로 매칭하여 외적 "
        "타당성을 검증해야 한다. 마지막으로 정책 가중치는 전문가 위험 순위와 수정 전후의 "
        "배포 결과를 이용해 보정하여 정책 기반 보조지수의 해석 근거를 강화할 필요가 있다.",
    )

    add_heading(document, "부록 A. 고정 커밋 및 재현성 조건", "Heading 3")
    add_paragraph(
        document,
        "표 A1은 공개 DT 14개의 전체 커밋 SHA를 제시하고, 표 A2는 고정한 룰·설정·"
        "바이너리의 버전과 SHA-256 식별자를 제시한다. 본문의 실행 환경, 분석 범위 및 "
        "집계 기준과 함께 사용하면 동일한 공개 커밋을 대상으로 절차 수준의 반복 실험을 "
        "구성할 수 있다.",
    )
    add_paragraph(
        document,
        "원시 Gitleaks 보고서와 코드 문맥 파일은 후보 자격증명 및 코드 스니펫을 포함할 "
        "수 있어 별도 보조자료로 제공하지 않는다. 논문에는 집계 결과, 검토 기준, 대표 룰 "
        "및 재현성 조건만 제시하므로 비트 단위 원시 산출물의 독립 검증에는 제한이 있다.",
    )
    add_caption(document, "Table A1. Full commit SHA of the 14 public DT repositories")
    append_reference_table(document, reference, 13)
    add_caption(document, "Table A2. Frozen scanner artifacts and SHA-256 identifiers")
    append_reference_table(document, reference, 14)


REFERENCES = [
    'C. Alcaraz and J. López, "Digital Twin: A Comprehensive Survey of Security Threats," IEEE Commun. Surveys Tuts., vol. 24, no. 3, pp. 1475–1503, 2022.',
    'S. Choi, J. Woo, J. Kim, W. Choi, and J. Kim, "A Survey and Analysis of Research on Digital Twin in Korea," Korean J. Comput. Des. Eng., vol. 26, no. 2, pp. 131–143, 2021.',
    'J. Autiosalo, J. Väisänen, and K. Tammi, "Twinbase: Open-Source Server Software for the Digital Twin Web," IEEE Access, vol. 9, pp. 77719–77730, 2021.',
    'J. Voas, P. Mell, P. Laplante, and V. Piroumian, "Security and Trust Considerations for Digital Twin Technology," NIST Interagency/Internal Report 8356, Feb. 2025, doi: 10.6028/NIST.IR.8356.',
    'S. Suhail, R. Jurdak, and R. Hussain, "Security Attacks and Solutions for Digital Twins," arXiv preprint arXiv:2202.12501, 2022.',
    'H. Mun, K. Han, E. Damiani, H. K. Yeun, T.-Y. Kim, L. Martino, and C. Y. Yeun, "A Comprehensive Survey on Digital Twin: Focusing on Security Threats and Requirements," IEEE Access, vol. 13, pp. 73362–73390, 2025, doi: 10.1109/ACCESS.2025.3563621.',
    'B. Airehenbuwa et al., "Advancing Security with Digital Twins: A Comprehensive Survey," arXiv preprint arXiv:2505.17310, 2025.',
    'A. Qureshi et al., "A Survey on Security Enhancing Digital Twins: Models, Applications and Tools," Comput. Commun., vol. 238, 2025.',
    'M. Eckhart, A. Ekelhart, D. Allison, M. Almgren, K. Ceesay-Seitz, H. Janicke, S. Nadjm-Tehrani, A. Rashid, and M. Yampolskiy, "Security-Enhancing Digital Twins: Characteristics, Indicators, and Future Perspectives," IEEE Security & Privacy, vol. 21, no. 3, pp. 32–41, 2023.',
    'C. Gehrmann and M. Gunnarsson, "A Digital Twin Based Industrial Automation and Control System Security Architecture," IEEE Trans. Ind. Inform., vol. 16, no. 1, pp. 633–643, 2020.',
    'M. Dietz, L. Hageman, C. von Hornung, and G. Pernul, "Employing Digital Twins for Security-by-Design System Testing," in Proc. 2022 ACM Workshop on Secure and Trustworthy Cyber-Physical Systems, pp. 97–106, 2022.',
    'M. Alazmi and D. de Leon, "A Systematic Literature Review on the Characteristics and Effectiveness of Web Application Vulnerability Scanners," IEEE Access, vol. 10, pp. 97397–97416, 2022.',
    'Center for Assured Software, "CAS Static Analysis Tool Study Methodology," National Security Agency (NSA), 2012.',
    'S. Qadir, S. Jehan, A. Khanum, and W. Emam, "Comparative Evaluation of Approaches & Tools for Effective Security Testing of Web Applications," PeerJ Comput. Sci., vol. 11, e2821, 2025.',
    'M. Albahar, "An Empirical Comparison of Pen-Testing Tools for Detecting Web App Vulnerabilities," Electronics, vol. 11, no. 19, p. 2991, 2022.',
    'J. Moon and S. Cho, "웹 애플리케이션의 취약점 분석 및 보안 위협 완화," 한국컴퓨터정보학회 논문지, vol. 17, no. 2, pp. 127–135, 2012.',
    'OWASP, "OWASP Top 10:2021 – The Ten Most Critical Web Application Security Risks," OWASP Foundation, 2021. [Online]. Available: https://owasp.org/Top10/',
    'FIRST, "Common Vulnerability Scoring System Version 3.1: Specification Document," Forum of Incident Response and Security Teams (FIRST), 2019. [Online]. Available: https://www.first.org/cvss/v3.1/specification-document',
    'Z. Rice, "Gitleaks," GitHub, 2024. [Online]. Available: https://github.com/gitleaks/gitleaks',
    'OWASP, "OWASP Risk Rating Methodology," OWASP Foundation. [Online]. Available: https://owasp.org/www-community/OWASP_Risk_Rating_Methodology',
    'A. Mohsin, H. Janicke, S. Nepal, and D. Holmes, "Digital Twins and the Future of Their Use Enabling Shift Left and Shift Right Cybersecurity Operations," in Proc. IEEE Int. Conf. Trust, Privacy and Security in Intelligent Systems and Applications (TPS-ISA), 2023.',
    '최영해, 노형준, 조성윤, 강한승, 김동완, 박수현, 조민재, 이주형, "오픈소스 취약점 점검 도구 및 종합 보안 메트릭 설계를 통한 DevSecOps 구축방안 연구," 정보보호학회논문지, vol. 33, no. 4, pp. 699–707, 2023, doi: 10.13089/JKIISC.2023.33.4.699.',
    '서동수, "소프트웨어 개발보안 활동을 위한 보안메트릭 정의," 인터넷정보학회논문지, vol. 17, no. 4, pp. 79–86, 2016.',
    '홍진근, "Component Analysis of DevOps and DevSecOps," 한국융합학회논문지, vol. 10, no. 9, pp. 47–53, 2019, doi: 10.15207/JKCS.2019.10.9.047.',
    '박용근, 김수종, 엄주명, "디지털 트윈을 활용한 Plug-n-Play 머신텐딩 자동화 시스템 개발," 한국디지털산업학회지, vol. 25, no. 4, pp. 143–154, 2020, doi: 10.7838/jsebs.2020.25.4.143.',
    '이영찬, 이상훈, 현창택, 김승권, "웹 서비스를 고려한 스마트시티 디지털 트윈 모델 경량화 및 시스템 구축방안," 한국CDE학회 논문집, vol. 26, no. 3, pp. 193–207, 2021, doi: 10.7315/CDE.2021.193.',
    '정지인, 이재혁, 이경률, "정적 분석 도구 성능 비교 및 분석: 오픈소스의 보안 취약점을 기반으로," 한국통신학회논문지, vol. 47, no. 4, pp. 679–689, 2022, doi: 10.7840/kics.2022.47.4.679.',
    '하동휘, "MISRA C 코딩 규칙 준수를 위한 상용 및 공개 소프트웨어 정적분석 도구 성능 비교 연구," 한국컴퓨터정보학회논문지, vol. 30, no. 8, pp. 11–19, 2025, doi: 10.9708/jksci.2025.30.08.011.',
    '서병석, 구지현, 손선영, 고광만, "디지털 트윈 환경에서 의료기기 사이버 보안 평가를 위한 요구사항 설계에 관한 연구," 전자공학회논문지, vol. 61, no. 10, pp. 103–108, 2024, doi: 10.5573/ieie.2024.61.10.103.',
    '박성현, 최지훈, "DevOps 기반의 이슈 트래킹 시스템 구현에 관한 연구," 한국컴퓨터정보학회논문지, vol. 27, no. 1, pp. 91–96, 2022, doi: 10.9708/jksci.2022.27.01.091.',
]


def add_references(document: Document) -> None:
    add_heading(document, "참고문헌", "Heading 3")
    for index, reference in enumerate(REFERENCES, start=1):
        add_paragraph(document, f"[{index}] {reference}", style="normal")


def style_tables(document: Document) -> None:
    for table in document.tables:
        table.autofit = True
        header = table.rows[0]
        tr_pr = header._tr.get_or_add_trPr()
        if tr_pr.find(qn("w:tblHeader")) is None:
            tr_pr.append(OxmlElement("w:tblHeader"))
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    for run in paragraph.runs:
                        set_run_font(run, size=8)


def build(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    source_hash = sha256(source)
    reference_hash = sha256(REFERENCE_DOC)
    document = Document(source)
    reference = Document(REFERENCE_DOC)

    draft_note = find_paragraph(document, "(제목은 숮", startswith=True)
    delete_paragraph(draft_note)
    add_abstract(document)

    chapter_3 = find_paragraph(document, "3. 웹 디지털트윈을 위한 보안성 측정 기법")
    chapter_3_index = paragraph_index(document, chapter_3)
    for paragraph in document.paragraphs[:chapter_3_index]:
        revised = minimal_term_normalization(paragraph.text)
        if revised != paragraph.text:
            clear_and_set(paragraph, revised)

    complete_contributions(document)
    remove_draft_after_2_3(document)
    build_process_figure(FIGURE_PATH)
    add_chapter_3(document, reference)
    add_chapter_4(document, reference)
    add_chapter_5_and_appendix(document, reference)
    add_references(document)
    style_tables(document)

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".with-comments.docx",
        delete=False,
    ) as handle:
        temp_with_comments = Path(handle.name)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent,
        prefix=destination.name + ".",
        suffix=".clean.docx",
        delete=False,
    ) as handle:
        temp_clean = Path(handle.name)
    try:
        document.save(temp_with_comments)
        strip_comments(temp_with_comments, temp_clean)
        temp_clean.replace(destination)
    finally:
        if temp_with_comments.exists():
            temp_with_comments.unlink()
        if temp_clean.exists():
            temp_clean.unlink()

    validate(source, destination, source_hash, reference_hash)
    print(f"source={source}")
    print(f"source_sha256={source_hash}")
    print(f"reference_sha256={reference_hash}")
    print(f"output={destination}")
    print(f"output_sha256={sha256(destination)}")
    print(
        "validated=kci_complete:true user_ch1_ch2_preserved:true tables:15 "
        "figure:1 comments_removed:true terminology:true evidence:true"
    )


def validate(
    source: Path,
    destination: Path,
    source_hash: str,
    reference_hash: str,
) -> None:
    if sha256(source) != source_hash:
        raise AssertionError("source manuscript changed")
    if sha256(REFERENCE_DOC) != reference_hash:
        raise AssertionError("reference evidence document changed")
    with zipfile.ZipFile(destination) as archive:
        if bad_member := archive.testzip():
            raise AssertionError(f"corrupt DOCX member: {bad_member}")
        names = set(archive.namelist())
        if any("comments" in name for name in names):
            raise AssertionError("Word comments remain")
        xml = archive.read("word/document.xml")
        if b"commentRange" in xml or b"commentReference" in xml:
            raise AssertionError("comment markup remains")

    original = Document(source)
    output = Document(destination)
    reference = Document(REFERENCE_DOC)
    if len(output.tables) != 15:
        raise AssertionError("expected 15 tables")
    for index, table in enumerate(output.tables):
        if table_signature(table) != table_signature(reference.tables[index]):
            raise AssertionError(f"Table {index + 1} evidence changed")
    if len(output.inline_shapes) != 1:
        raise AssertionError("expected one process figure")
    if len(output.sections) != 1:
        raise AssertionError("section count changed")

    original_start = paragraph_index(original, find_paragraph(original, "1. 서론"))
    original_end = paragraph_index(
        original,
        find_paragraph(original, "3. 웹 디지털트윈을 위한 보안성 측정 기법"),
    )
    output_start = paragraph_index(output, find_paragraph(output, "1. 서론"))
    output_end = paragraph_index(
        output,
        find_paragraph(output, "3. 웹 디지털트윈을 위한 보안성 측정 기법"),
    )
    original_required = []
    for paragraph in original.paragraphs[original_start:original_end]:
        if paragraph.text.startswith("기여점은 마지막에 작성 예정"):
            continue
        original_required.append(minimal_term_normalization(paragraph.text))
    output_section = [p.text for p in output.paragraphs[output_start:output_end]]
    for paragraph_text in original_required:
        if paragraph_text not in output_section:
            raise AssertionError(
                "user-authored Chapter 1–2.3 paragraph missing: "
                + paragraph_text[:80]
            )

    text = "\n".join(p.text for p in output.paragraphs)
    text += "\n" + "\n".join(
        cell.text
        for table in output.tables
        for row in table.rows
        for cell in row.cells
    )
    for heading in (
        "3. 웹 디지털트윈을 위한 보안성 측정 기법",
        "3.1 개요",
        "3.2 상세 절차",
        "3.2.1 보안 취약점 탐지 단계",
        "3.2.2 취약점 탐지 결과 단계",
        "4. 웹 기반 디지털트윈의 보안성 측정 사례",
        "4.1 웹 기반 디지털트윈 소개",
        "4.2 실험 환경",
        "4.3 취약점 탐지 유형",
        "4.4 분석",
        "5. 결론 및 향후 연구",
    ):
        if heading not in text:
            raise AssertionError(f"required heading missing: {heading}")
    for required in (
        "보안 취약점 탐지 단계(Security Scan Step)",
        "취약점 의사결정(Vulnerability Decision-Making)",
        "CWE 보안 정책 카탈로그",
        "CWE 기반 보안 등급",
        "정책 적용 대상 탐지 항목",
        "정책 외 탐지 항목",
        "코드 문맥 검토",
        "정책 기반 보조지수",
        "즉시 배포 차단",
        "선택적 배포 차단",
        "BLOCK_PENDING_APPROVAL",
        "정밀도 0.533",
        "재현율 0.772",
        "F1-Score 0.630",
        "TP 728, FP 639, FN 215",
        "CWE-327은 TP=0, FN=130",
        "정책 기반 보조지수 94/100",
        "BLOCK 8개, BLOCK_PENDING_APPROVAL 1개, WARN 2개 및 PASS 3개",
        "D_H = min(5C_H, 19)",
        "Algorithm 1. Environment-Sensitive Vulnerability Decision-Making and Deployment Control",
    ):
        if required not in text:
            raise AssertionError(f"required technical content missing: {required}")
    for forbidden in (
        "(제목은 숮",
        "기여점은 마지막에 작성 예정",
        "정량적 보안 점수",
        "배포 판정",
        "수동 판독",
        "수동 검증",
        "single-reviewer",
        "Cohen",
        "RQ1",
        "RQ2",
        "RQ3",
        "보조자료 S1",
        "analysis/",
    ):
        if forbidden.lower() in text.lower():
            raise AssertionError(f"forbidden text remains: {forbidden}")
    if sum(1 for p in output.paragraphs if p.text.startswith("[")) != 30:
        raise AssertionError("reference count is not 30")


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
