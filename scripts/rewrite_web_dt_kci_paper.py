#!/usr/bin/env python3
"""Create a KCI-oriented web-DT paper draft from the verified result DOCX.

The source document is preserved.  This script rewrites the prose, adds exact
experiment metadata, inserts table captions and a process figure, and retains
the verified result tables already present in the source package.
"""

from __future__ import annotations

import copy
import io
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw, ImageFont


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
WP_NS = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PIC_NS = "http://schemas.openxmlformats.org/drawingml/2006/picture"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
CT_NS = "http://schemas.openxmlformats.org/package/2006/content-types"
XML_NS = "http://www.w3.org/XML/1998/namespace"

W = f"{{{W_NS}}}"
R = f"{{{R_NS}}}"
WP = f"{{{WP_NS}}}"
A = f"{{{A_NS}}}"
PIC = f"{{{PIC_NS}}}"
REL = f"{{{REL_NS}}}"
CT = f"{{{CT_NS}}}"

for prefix, uri in (
    ("w", W_NS),
    ("r", R_NS),
    ("wp", WP_NS),
    ("a", A_NS),
    ("pic", PIC_NS),
):
    ET.register_namespace(prefix, uri)
ET.register_namespace("", REL_NS)


def register_namespaces(xml_bytes: bytes) -> None:
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
        try:
            ET.register_namespace(prefix or "", uri)
        except ValueError:
            pass


def text_of(element: ET.Element) -> str:
    return "".join(node.text or "" for node in element.iter() if node.tag.endswith("}t"))


def set_paragraph_text(paragraph: ET.Element, value: str) -> None:
    properties = paragraph.find(W + "pPr")
    for child in list(paragraph):
        if child is not properties:
            paragraph.remove(child)
    run = ET.SubElement(paragraph, W + "r")
    parts = value.split("\n")
    for index, part in enumerate(parts):
        if index:
            ET.SubElement(run, W + "br")
        text = ET.SubElement(run, W + "t")
        if part.startswith(" ") or part.endswith(" ") or "  " in part:
            text.set(f"{{{XML_NS}}}space", "preserve")
        text.text = part


def set_cell_text(cell: ET.Element, value: str) -> None:
    properties = cell.find(W + "tcPr")
    for child in list(cell):
        if child is not properties:
            cell.remove(child)
    paragraph = ET.SubElement(cell, W + "p")
    set_paragraph_text(paragraph, value)


def rows_of(table: ET.Element) -> list[ET.Element]:
    return table.findall("./" + W + "tr")


def cells_of(row: ET.Element) -> list[ET.Element]:
    return row.findall("./" + W + "tc")


def set_table(table: ET.Element, values: list[list[str]]) -> None:
    rows = rows_of(table)
    if len(rows) != len(values):
        raise ValueError(f"table row mismatch: {len(rows)} != {len(values)}")
    for row, row_values in zip(rows, values, strict=True):
        cells = cells_of(row)
        if len(cells) != len(row_values):
            raise ValueError(f"table column mismatch: {len(cells)} != {len(row_values)}")
        for cell, value in zip(cells, row_values, strict=True):
            set_cell_text(cell, value)


def add_column(table: ET.Element) -> None:
    for row in rows_of(table):
        row.append(copy.deepcopy(cells_of(row)[-1]))


def create_process_figure(path: Path) -> bytes:
    width, height = 2400, 980
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    regular = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    bold = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    font = ImageFont.truetype(regular, 39)
    bold_font = ImageFont.truetype(bold, 42)
    small_font = ImageFont.truetype(bold, 34)

    boxes = [
        (60, 170, 400, 420, "Repository\nClone", "#E8F1FF", "#2563A6"),
        (520, 170, 860, 420, "1단계 Gitleaks\n시크릿 탐지", "#E7F8EF", "#23815A"),
        (980, 170, 1320, 420, "2단계 Semgrep\n정적 분석", "#F0EAFF", "#6941C6"),
        (1440, 170, 1800, 420, "16종 CWE 정책 분류\n보조 점수 산출", "#FFF5DA", "#B7791F"),
        (1920, 170, 2340, 420, "환경 민감형\n판정 게이트", "#FFE9E9", "#B53B3B"),
    ]

    def rounded_box(box: tuple[int, int, int, int], fill: str, outline: str) -> None:
        draw.rounded_rectangle(box, radius=28, fill=fill, outline=outline, width=6)

    def arrow(x1: int, y1: int, x2: int, y2: int, color: str = "#4B5563") -> None:
        draw.line((x1, y1, x2, y2), fill=color, width=10)
        if abs(x2 - x1) >= abs(y2 - y1):
            direction = 1 if x2 > x1 else -1
            head = [(x2, y2), (x2 - 30 * direction, y2 - 20), (x2 - 30 * direction, y2 + 20)]
        else:
            direction = 1 if y2 > y1 else -1
            head = [(x2, y2), (x2 - 20, y2 - 30 * direction), (x2 + 20, y2 - 30 * direction)]
        draw.polygon(head, fill=color)

    for x1, y1, x2, y2, label, fill, outline in boxes:
        rounded_box((x1, y1, x2, y2), fill, outline)
        draw.multiline_text(
            ((x1 + x2) / 2, (y1 + y2) / 2),
            label,
            font=bold_font if "Repository" not in label else font,
            fill="#172033",
            anchor="mm",
            align="center",
            spacing=12,
        )

    for left, right in zip(boxes, boxes[1:]):
        arrow(left[2] + 15, 295, right[0] - 15, 295)

    gate_center = (2130, 420)
    draw.line((gate_center[0], gate_center[1], gate_center[0], 575), fill="#4B5563", width=10)
    draw.line((1620, 575, 2240, 575), fill="#4B5563", width=10)

    decisions = [
        (1460, 650, 1760, 820, "BLOCK", "#FFE1E1", "#B42318"),
        (1840, 650, 2140, 820, "WARN", "#FFF0C2", "#B7791F"),
        (2220, 650, 2380, 820, "PASS", "#DCFCE7", "#15803D"),
    ]
    centers = []
    for x1, y1, x2, y2, label, fill, outline in decisions:
        rounded_box((x1, y1, x2, y2), fill, outline)
        draw.text(((x1 + x2) / 2, (y1 + y2) / 2), label, font=small_font, fill=outline, anchor="mm")
        centers.append(((x1 + x2) // 2, y1))
    for center_x, center_y in centers:
        arrow(center_x, 575, center_x, center_y - 12)

    draw.text((60, 70), "SecuPipeline 웹 기반 DT 보안성 측정 프로세스", font=bold_font, fill="#172033")
    draw.text((60, 890), "탐지 결과는 정책 범위 내·외로 분류되며, 범위 내 결과가 보조 점수와 배포 판정에 사용된다.", font=font, fill="#4B5563")

    output = io.BytesIO()
    image.save(output, format="PNG", dpi=(200, 200), optimize=True)
    data = output.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def set_drawing(paragraph: ET.Element, relationship_id: str) -> None:
    properties = paragraph.find(W + "pPr")
    for child in list(paragraph):
        if child is not properties:
            paragraph.remove(child)
    run = ET.SubElement(paragraph, W + "r")
    drawing = ET.SubElement(run, W + "drawing")
    inline = ET.SubElement(drawing, WP + "inline")
    ET.SubElement(inline, WP + "extent", {"cx": "5943600", "cy": "2423160"})
    ET.SubElement(inline, WP + "effectExtent", {"l": "0", "t": "0", "r": "0", "b": "0"})
    ET.SubElement(inline, WP + "docPr", {"id": "100", "name": "SecuPipeline process", "descr": "SecuPipeline process flow"})
    graphic = ET.SubElement(inline, A + "graphic")
    graphic_data = ET.SubElement(graphic, A + "graphicData", {"uri": PIC_NS})
    picture = ET.SubElement(graphic_data, PIC + "pic")
    nv = ET.SubElement(picture, PIC + "nvPicPr")
    ET.SubElement(nv, PIC + "cNvPr", {"id": "100", "name": "secu_pipeline_flow.png"})
    locks = ET.SubElement(nv, PIC + "cNvPicPr")
    ET.SubElement(locks, A + "picLocks", {"noChangeAspect": "1"})
    fill = ET.SubElement(picture, PIC + "blipFill")
    ET.SubElement(fill, A + "blip", {R + "embed": relationship_id})
    stretch = ET.SubElement(fill, A + "stretch")
    ET.SubElement(stretch, A + "fillRect")
    shape = ET.SubElement(picture, PIC + "spPr")
    transform = ET.SubElement(shape, A + "xfrm")
    ET.SubElement(transform, A + "off", {"x": "0", "y": "0"})
    ET.SubElement(transform, A + "ext", {"cx": "5943600", "cy": "2423160"})
    geometry = ET.SubElement(shape, A + "prstGeom", {"prst": "rect"})
    ET.SubElement(geometry, A + "avLst")


def main(source: Path, destination: Path, figure_path: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    with zipfile.ZipFile(source) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
    payload = {info.filename: data for info, data in entries}
    document_xml = payload["word/document.xml"]
    register_namespaces(document_xml)
    root = ET.fromstring(document_xml)
    body = root.find(".//" + W + "body")
    if body is None:
        raise ValueError("word/document.xml has no body")
    tables = body.findall(W + "tbl")
    if len(tables) != 8:
        raise ValueError(f"expected 8 tables, found {len(tables)}")

    def paragraphs() -> list[ET.Element]:
        return body.findall(W + "p")

    def find_paragraph(prefix: str) -> ET.Element:
        matches = [p for p in paragraphs() if text_of(p).startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"paragraph prefix {prefix!r}: found {len(matches)}")
        return matches[0]

    def replace(prefix: str, value: str) -> ET.Element:
        paragraph = find_paragraph(prefix)
        set_paragraph_text(paragraph, value)
        return paragraph

    def insert_before(target: ET.Element, value: str) -> ET.Element:
        paragraph = ET.Element(W + "p")
        source_properties = target.find(W + "pPr")
        if source_properties is not None:
            paragraph.append(copy.deepcopy(source_properties))
        set_paragraph_text(paragraph, value)
        body.insert(list(body).index(target), paragraph)
        return paragraph

    def insert_after(target: ET.Element, value: str) -> ET.Element:
        paragraph = ET.Element(W + "p")
        source_properties = target.find(W + "pPr")
        if source_properties is not None:
            paragraph.append(copy.deepcopy(source_properties))
        set_paragraph_text(paragraph, value)
        body.insert(list(body).index(target) + 1, paragraph)
        return paragraph

    # Five-sentence abstract: problem, method, experiment, accuracy, and DT result.
    replace(
        "웹 기반 디지털트윈(DT)은",
        "웹 기반 DT는 3D 시각화, 실시간 센서 동기화 및 원격 제어 기능을 제공하나, 기존 보안 연구는 CPS·OT 계층에 집중하여 웹 애플리케이션 계층의 소스 코드 수준 취약점을 충분히 다루지 못했다. 본 연구는 Gitleaks와 Semgrep을 결합한 2단계 정적 분석, 16종 CWE 정책 카탈로그, 심각도 기반 보조 점수 및 환경 민감형 판정 모델로 구성된 웹 기반 DT 보안성 측정 기법을 제안한다. 검증용 취약 웹앱 8개, 공개 DT 웹앱 14개 및 수소추진선박 DT 1개의 고정 커밋을 대상으로 탐지 정확도 검증, 보안성 측정 및 저장소 단위 취약점 프로파일 비교를 수행하였다. 실험 결과, OWASP Benchmark v1.2의 정책 중첩 6개 CWE에서 제안 기법은 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 보였다. 공개 DT 14개에서 274건의 정책 범위 탐지를 식별하고 저장소별 배포 판정을 도출하였으며, 수소추진선박 사례에서는 실시간 통신과 동적 시각화 구성요소에 연결된 CWE-319 및 CWE-79를 확인하여 DT 문맥 기반 보안 검토 지점을 제시하였다.",
    )

    # Chapter 1: use the author's revised problem-to-purpose flow.
    replace(
        "산업 4.0의 발전과 함께",
        "산업 4.0의 발전과 함께 디지털트윈(Digital Twin, DT)은 물리적 자산의 가상 복제물로서 제조, 에너지, 교통, 헬스케어 등 다양한 산업 영역에서 예측·최적화·모니터링을 위해 광범위하게 도입되고 있다 [1]. 국내에서도 DT 기술의 산업 적용 사례가 증가하며 [2], 웹 기반 DT는 3D 시각화, 실시간 센서 데이터 연동, 원격 제어 등의 기능을 웹 브라우저를 통해 제공한다. Three.js, CesiumJS, Unity WebGL 등의 3D 렌더링 라이브러리와 WebSocket 기반 실시간 통신을 활용하는 형태로 구현되며 [3], Azure Digital Twins, Autodesk Forge, iTwin 등 주요 플랫폼이 웹 기반 DT 서비스를 제공하고 있어 웹 인터페이스를 통한 DT 접근은 산업 표준으로 자리 잡고 있다.",
    )
    replace(
        "그러나 DT는 사이버물리시스템",
        "그러나 DT는 사이버물리시스템(CPS), 사물인터넷(IoT), 클라우드 컴퓨팅, 빅데이터 등 다수의 기술을 통합하므로 [1], 공격 표면이 일반 웹 애플리케이션보다 넓다. 미국 NIST는 DT 기술의 보안과 신뢰에 대한 고려사항을 제시하며, DT가 물리 시스템과 양방향으로 연동되는 특성상 보안 사고의 영향이 가상 영역을 넘어 실제 물리 시스템으로 확대될 수 있음을 설명하였다 [4]. DT의 가상 복제본이 물리적 자산과 양방향으로 동기화되는 특성상 [5], 웹 계층의 보안 취약점은 데이터 보호뿐 아니라 물리 시스템의 안정적 운영과도 연결된다. 따라서 웹 기반 DT 소프트웨어에 대한 체계적인 보안 검증이 요구된다.",
    )
    replace(
        "웹 기반 DT는 브라우저를 통해",
        "이처럼 웹 기반 DT의 보안 취약점은 물리 시스템의 안정성과 안전에 영향을 줄 수 있음에도 [4], 기존 DT 보안 연구는 주로 CPS 및 OT(Operational Technology) 관점에서 네트워크 공격, 침입 탐지 및 보안 아키텍처를 다루어 왔다. 웹 애플리케이션 계층의 소스 코드를 대상으로 한 취약점 분석과 정량적 보안성 측정은 상대적으로 충분히 다루어지지 않았다. 관련 선행연구는 제2.1절에서 구체적으로 검토한다.",
    )
    replace(
        "웹 애플리케이션 보안 테스팅 분야에서는 OWASP ZAP",
        "한편, 웹 애플리케이션 보안 테스팅 분야에서는 동적 애플리케이션 보안 테스팅(DAST) 도구인 OWASP ZAP과 Burp Suite, 정적 애플리케이션 보안 테스팅(SAST) 도구인 Semgrep과 CodeQL이 널리 활용되고 있다. 그러나 기존 도구와 평가 방법론은 주로 일반 웹 애플리케이션을 대상으로 개발 및 평가되어, 3D 렌더링 구성요소, WebSocket 기반 실시간 상태 동기화, IoT 센서 데이터 연계 API 등 웹 기반 DT 소프트웨어의 구조적 특성을 충분히 반영하기 어렵다. 이에 관한 기존 연구와 도구의 특징은 제2.2절에서 상세히 살펴본다.",
    )
    replace(
        "결과적으로, 웹 기반 DT 소프트웨어의",
        "따라서 웹 기반 DT 소프트웨어의 보안성을 검증하기 위해서는 소스 코드에서 취약점을 체계적으로 탐지하고, 탐지 결과를 정량화하여 소프트웨어의 보안 수준을 평가하는 방법이 필요하다. 특히 취약점의 심각도뿐만 아니라 실제 배포 환경에서의 영향 가능성을 함께 고려하여, 분석 결과를 정량적 보안 점수와 배포 판정으로 전환할 수 있는 검증 체계가 요구된다.",
    )
    replace(
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 보안성을 정량적으로 측정하는 기법을 제안한다.",
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 보안성을 정량적으로 측정하고 DevSecOps 파이프라인의 배포 의사결정으로 연결하는 기법을 제안한다. 이를 위해 2단계 정적 보안 스캔 체계, 16종 CWE 정책 카탈로그, 심각도 기반 보조 점수 및 환경 민감형 판정 게이트를 통합하여 구현하였다. 제안 기법을 검증용 취약 웹앱 8개, 공개 DT 웹앱 14개 및 수소추진선박 DT 1개에 적용한 결과, OWASP Benchmark의 정책 중첩 6개 CWE에서 F1-Score 0.630을 확인하고 공개 DT 14개에서 274건의 정책 범위 탐지와 저장소별 배포 판정을 도출하였다.",
    )
    replace(
        "DT 웹앱 맞춤형 보안성 측정 기법 제안:",
        "DT 웹앱 대상 보안성 측정 체계 제안: OWASP Top 10:2021을 바탕으로 16개 CWE 정책 항목을 정의하고, Gitleaks와 Semgrep을 순차 적용하는 2단계 스캔 및 범위 내·외 분류 체계를 설계하였다(제3.1절 및 제3.2절). OWASP Benchmark를 이용한 정확도 결과는 제4.2절에 제시한다.",
    )
    replace(
        "환경 민감형 보안 점수·판정 모델 설계:",
        "환경 민감형 보조 점수·판정 모델 설계: Critical·High·Medium·Low 등급의 위계를 보존하는 감점 상한과 production, staging, development 및 feature 환경별 판정 게이트를 제안하였다(제3.3절). 14개 공개 DT 웹앱의 적용 결과는 표 6에 제시한다.",
    )
    replace(
        "DT 취약점 프로파일의 실증 비교:",
        "DT 코드베이스의 실증적 취약점 프로파일 구축: 공개 DT 웹앱 14개와 취약 웹앱 8개의 고정 커밋을 분석하고, 저장소 단위 Fisher 정확 검정과 Odds Ratio를 이용하여 CWE 분포를 비교하였다(제4.5절 및 표 8). 또한 수소추진선박 DT 사례를 통해 실시간 통신과 동적 시각화 구성요소에 대한 문맥 기반 해석을 제시하였다.",
    )

    # Chapter 2: retain the author's revised related-work narrative.
    replace(
        "디지털트윈의 보안 문제는 최근 몇 년간",
        "디지털트윈의 보안에 관한 기존 연구는 크게 DT 자체의 위협과 보안 요구사항을 분석하는 연구와 DT를 CPS 및 산업 시스템의 보안 강화 수단으로 활용하는 연구로 구분할 수 있다. 먼저 DT 자체의 보안 위협을 분석한 연구에서는 물리, 네트워크, 데이터 및 애플리케이션 계층 등 DT의 기능 계층별 잠재적 위협을 분류하고 각 계층에 대한 보안 권고안을 제시하였다 [1]. 또한 DT에 대한 공격 모델을 정찰, 복제 및 시뮬레이션 등의 유형으로 구분하고, 공격자가 DT를 침해할 수 있는 경로를 체계적으로 분석하였다 [5]. Common Criteria(CC)를 기반으로 DT의 보안 위협을 분석하고 보안 기능 요구사항(Security Functional Requirements, SFR)을 도출한 연구도 수행되었다 [6]. 이와 함께 DT 보안 연구를 기능적 역할과 응용 도메인에 따라 분류한 종합 설문 [7]과 DT 보안 강화 모델, 응용 분야 및 지원 도구의 기술 동향을 분석한 연구 [8]가 제시되었다.",
    )
    replace(
        "DT를 보안 강화 도구로 활용하는 관점에서",
        "한편, DT를 보안 강화 수단으로 활용하는 연구도 진행되어 왔다. DT의 복제와 시뮬레이션 특성이 CPS의 보안성을 향상하는 데 어떻게 활용될 수 있는지를 분석한 연구가 수행되었으며 [9], 산업 제어 시스템에서는 DT 기반 상태 복제를 활용한 보안 아키텍처가 제안되었다. 해당 연구는 보안 소프트웨어 업데이트 과정에서 DT를 활용하는 시나리오를 실험적으로 검증하였다 [10]. 또한 DT를 활용한 Security-by-Design 기반 테스팅 접근법을 제안하고, 압력 용기 DT를 대상으로 취약점 식별 가능성을 개념증명 형태로 제시한 연구도 수행되었다 [11].",
    )
    replace(
        "그러나 상기 연구들은 주로 CPS 및 OT 관점의",
        "이러한 연구들은 DT의 위협 모델, 네트워크 공격, 상태 동기화 및 보안 아키텍처에 관한 중요한 기반을 마련하였다. 연구의 초점은 주로 CPS 및 OT 환경의 시스템과 네트워크 수준 보안에 맞추어져 있으며, 실제 웹 기반 DT의 소스 코드를 대상으로 취약점을 탐지하고 보안성을 정량적으로 평가하는 방법은 상대적으로 충분히 다루어지지 않았다. 웹 기반 DT는 프론트엔드 프레임워크, 백엔드 런타임, 실시간 통신 모듈 및 3D 렌더링 구성요소가 결합된 복합적인 소프트웨어 구조를 가지므로, 웹 애플리케이션 계층을 포함하는 소스 코드 수준의 보안 분석 및 평가가 필요하다.",
    )
    replace(
        "SAST는 소스 코드를 실행하지 않고",
        "SAST(Static Application Security Testing)는 프로그램을 실행하지 않고 소스 코드나 컴파일된 코드를 정적으로 분석하여 잠재적인 보안 취약점을 탐지하는 기법이다. 대표적인 SAST 도구로는 Semgrep, CodeQL, SonarQube 등이 있으며, 도구별 취약점 탐지 성능과 적용 가능성을 분석하기 위한 비교 평가 연구가 수행되어 왔다 [12]. SAST 도구의 성능은 True Positive(TP), False Positive(FP), False Negative(FN)를 기반으로 산출되는 정밀도(Precision), 재현율(Recall) 및 F1-Score 등의 지표를 통해 평가할 수 있다 [13]. NSA Center for Assured Software(CAS)는 정적 분석 도구의 성능을 일관되고 반복 가능한 방식으로 평가하기 위한 방법론을 제시하고, 해당 지표의 정의와 산출 공식을 체계적으로 규정하였다 [13].",
    )
    replace("True Positive(TP):", "True Positive(TP): 의도적으로 결함이 있는 코드를 정확히 탐지한 수 [13]")
    replace("False Positive(FP):", "False Positive(FP): 결함이 없는 코드를 취약점으로 잘못 탐지한 수 [13]")
    replace("False Negative(FN):", "False Negative(FN): 의도적으로 결함이 있는 코드를 탐지하지 못한 수 [13]")
    replace(
        "그러나 기존 SAST 평가 연구의 대부분은",
        "그러나 기존 보안 도구 평가 연구는 주로 일반 웹 애플리케이션이나 범용 벤치마크를 대상으로 수행되었으며, DT 웹앱의 구조적 특성은 충분히 고려되지 않았다. 실제 운영 웹 애플리케이션을 대상으로 SAST와 DAST 도구를 비교한 연구 [14], OWASP Benchmark 기반의 동적 보안 테스트 연구 [15], NVD와 CWE를 활용한 웹 취약점 위험도 분석 연구 [16]가 수행되었으나, 웹 기반 DT의 소스 코드를 대상으로 한 SAST 평가로는 확장되지 않았다. 따라서 3D 렌더링, WebSocket 기반 실시간 동기화 및 IoT 데이터 연계 구조를 고려하여 DT 웹앱의 취약점 탐지 결과를 정량적으로 평가하는 방법이 필요하다.",
    )
    replace("2.3 문제 정의:", "2.3 웹 기반 디지털트윈 보안성 측정의 연구 공백 및 문제 정의")
    replace(
        "선행 연구 분석을 통해 다음 세 가지 갭을 식별하였다.",
        "선행연구 분석을 통해 웹 기반 DT 소프트웨어의 보안성 측정과 관련된 다음 세 가지 연구 공백을 도출하였다.",
    )
    replace(
        "갭 1:",
        "첫째, 웹 기반 DT를 대상으로 한 소스 코드 수준의 보안 분석이 충분히 이루어지지 않았다. 기존 DT 보안 연구는 주로 네트워크 및 CPS 계층의 위협과 대응 방안에 초점을 두고 있으며 [1,5], 웹 애플리케이션 계층의 소스 코드를 대상으로 한 정적 보안 분석은 상대적으로 제한적으로 다루어졌다. 반면 기존 SAST 평가 연구는 주로 일반 웹 애플리케이션을 대상으로 수행되어 [12], 3D 렌더링 구성요소, WebSocket 기반 실시간 동기화 및 IoT 데이터 연계 API 등 DT 웹앱의 구조적 특성을 충분히 반영하지 못한다.",
    )
    replace(
        "갭 2:",
        "둘째, 탐지 결과를 DT 소프트웨어의 보안 수준과 배포 가능 여부로 변환하는 정량적 평가 체계가 미흡하다. 기존 SAST 도구는 주로 개별 취약점의 유형과 심각도를 제공하지만, DT의 구성요소와 배포 환경을 함께 고려하여 분석 결과를 하나의 정량적 보조 점수와 일관된 배포 판정으로 변환하는 방법은 충분히 제시되지 않았다. 이로 인해 SAST 결과를 DevSecOps 파이프라인의 보안 게이트로 활용하는 데 제약이 있다.",
    )
    replace(
        "갭 3:",
        "셋째, DT 웹앱의 취약점 특성에 관한 실증적 프로파일이 충분히 구축되지 않았다. DT 웹앱과 일반 웹 애플리케이션 사이에 취약점 유형, 발생 빈도 및 심각도 측면에서 어떠한 분포 특성이 나타나는지에 대한 정량적 비교가 부족하다. 따라서 실제 코드베이스를 대상으로 두 집단의 취약점 분포를 비교하고, DT 웹앱의 구성요소와 연결되는 보안 검토 지점을 실증적으로 제시할 필요가 있다.",
    )
    replace(
        "본 연구는 위 세 가지 갭을 해결하는",
        "본 연구는 이러한 연구 공백을 해소하기 위해 웹 기반 DT 코드베이스의 취약점을 정적으로 탐지하고, 탐지 결과와 배포 환경을 반영하여 정량적 보조 점수 및 배포 판정을 산출하는 보안성 측정 방법을 제안한다. 첫 번째 연구 공백은 제3.2절의 2단계 스캔 체계로, 두 번째 연구 공백은 제3.3절의 점수·판정 모델로, 세 번째 연구 공백은 제4.4절의 사례 분석과 제4.5절의 프로파일 비교로 각각 다룬다.",
    )

    # Chapter 3: explain design choices and keep the implemented score/gate model.
    replace(
        "본 장에서는 웹 기반 DT 소프트웨어의 보안성을 정량적으로 측정하기 위한 기법을 제안한다.",
        "본 장에서는 웹 기반 DT 소프트웨어의 보안성을 정량적으로 측정하고 배포 의사결정으로 연결하기 위한 기법을 제안한다. 제안 기법은 취약점 탐지 단계와 탐지 결과의 정량화·판정 단계로 구성되며, 각 단계의 산출물은 JSON 형식으로 전달되어 CI/CD 파이프라인에서 자동 처리된다.",
    )
    replace(
        "전체 프로세스는 그림 1과 같다.",
        "전체 프로세스는 그림 1과 같다. 대상 리포지토리와 커밋을 고정한 후, 1단계 Gitleaks 시크릿 탐지와 2단계 Semgrep 정적 분석을 순차적으로 수행한다. 통합 탐지 결과는 16종 CWE 정책에 따라 범위 내(inScope)와 범위 외(outOfScope)로 분류되며, 범위 내 결과의 심각도 분포로 보조 점수를 산출한다. 마지막으로 배포 환경과 심각도 위계를 적용하여 BLOCK, BLOCK_PENDING_APPROVAL, WARN 또는 PASS를 결정한다.",
    )
    replace(
        "보안 정책은 OWASP Top 10:2021",
        "보안 정책은 OWASP Top 10:2021 [17]과 CVSS v3.1 [18]의 심각도 분류를 참조하여 16개 항목으로 구성하였다. 표 1은 정책 항목, OWASP 범주 및 대표 CWE의 매핑을 나타낸다.",
    )
    replace(
        "16개 항목은 Critical·High·Medium·Low",
        "16개 항목은 Critical·High·Medium·Low 각 4종으로 구성되며, CWE를 공통 식별자로 사용하여 스캐너별 원시 결과를 정책 등급으로 재분류한다. 정책 카탈로그에 포함되지 않은 탐지는 범위 외 결과로 별도 보존하여 후속 SCA·DAST·인프라 검토에 활용할 수 있게 하였다. OWASP A06의 취약·노후 구성요소와 A09의 로깅·모니터링 항목처럼 정적 코드 패턴만으로 충분히 판단하기 어려운 결과도 같은 방식으로 보존한다(제4.4.2절 참조).",
    )
    replace(
        "1단계: 경량 시크릿 탐지",
        "1단계: 경량 시크릿 탐지(Lightweight Security Scan). Gitleaks를 사용하여 소스 코드와 설정 파일에 포함된 API 키, 비밀번호 및 토큰 패턴을 탐지한다. Gitleaks는 규칙 기반 탐지, 사용자 정의 규칙 및 구조화된 결과 출력을 지원하여 [19] CI/CD의 선행 검사 단계에 적용하기 용이하다. 이 단계는 continue_on_failure 정책으로 결과를 기록한 뒤 2단계 분석을 계속 수행하며, 탐지된 시크릿은 CWE-798 정책으로 매핑한다.",
    )
    replace(
        "2단계: 심층 정적 보안 스캔",
        "2단계: 심층 정적 보안 스캔(Deep Security Scan). Semgrep을 사용하여 JavaScript, TypeScript, Python, Java, YAML 등 DT 저장소의 다언어 소스 코드를 분석한다. Semgrep은 CLI 기반 실행과 JSON 결과 출력을 지원하며 별도의 빌드 데이터베이스 없이 적용할 수 있어 서로 다른 기술 스택의 저장소를 동일 절차로 분석하는 데 적합하다. 본 실험에서는 --config auto 룰셋을 적용하고, 룰 ID, CWE, 파일 경로, 코드 위치 및 원시 심각도를 수집하였다.",
    )
    replace(
        "두 스캐너의 결과는 각각 독립적으로 파싱된 후",
        "두 스캐너의 결과는 각각 독립적으로 파싱한 뒤 공통 보안 결과 스키마로 통합한다. 각 레코드는 rule_id, cwe, file_path, line, scanner, normalized_severity 및 in_scope 필드를 가지며, 표 1의 정책 카탈로그와 매핑하여 범위 내·외를 결정한다. 이 구조는 탐지 근거를 유지하면서 점수 산출과 판정 게이트가 동일한 입력을 사용하도록 한다.",
    )
    replace(
        "범위 내 탐지 레코드의 등급별 분포를 이용해",
        "범위 내 탐지 레코드의 등급별 분포를 이용하여 100점 만점의 보조 점수 S를 산출한다. 보조 점수는 선택한 16개 정책 범위에서 코드베이스의 상대적 보안 상태를 요약하며, 배포 차단 여부는 제3.3.2절의 계층형 게이트가 독립적으로 결정한다.",
    )
    replace(
        "등급별 건당 감점은 Critical 20",
        "등급별 건당 감점은 Critical 20, High 5, Medium 1, Low 0.2로 설정하였다. 이 값은 CVSS v3.1의 질적 심각도 위계 [18]를 점수 모델에 반영하고, 상위 등급 한 건이 하위 등급의 누적보다 우선하도록 설계한 것이다. High 19점, Medium 4점, Low 0.9점의 상한을 적용하여 등급 간 순서를 유지하며, Critical이 존재하면 보조 점수를 0~40 구간으로 제한한다.",
    )
    replace(
        "이 설계에서 Low 전체 감점은",
        "이 설계에서 Low 전체 감점은 Medium 1건의 감점보다 작고, Medium 전체 감점은 High 1건보다 작으며, High 전체 감점은 Critical 1건보다 작다. 표 2와 같이 점수 모델과 게이트 판정을 분리함으로써 보조 점수는 저장소 간 상태 비교에 사용하고, 상위 심각도 탐지는 별도의 승인·차단 절차로 연결한다.",
    )
    replace(
        "점수는 선택한 16개 정책 범위의",
        "보조 점수는 16개 정책 범위의 분석 결과를 일관된 척도로 요약하며, 원본 탐지 레코드와 함께 제공된다. 따라서 사용자는 점수뿐 아니라 CWE, 파일 위치 및 심각도 근거를 함께 확인하여 수정 우선순위를 결정할 수 있다.",
    )
    replace(
        "판정은 점수가 아니라 등급 위계에 따라 수행된다.",
        "배포 판정은 보조 점수의 단일 임계값이 아니라 탐지 심각도와 배포 환경의 조합으로 수행한다. 표 3은 production, staging, development 및 feature 환경에서 Critical·High·Medium 탐지를 처리하는 규칙을 나타낸다.",
    )
    replace(
        "게이트는 우선순위 순으로 동작한다.",
        "게이트는 우선순위 순으로 동작한다. Critical이 1건 이상이면 BLOCK, 미승인 High가 1건 이상이면 BLOCK_PENDING_APPROVAL을 반환한다. Medium만 존재하는 경우 development와 feature에서는 WARN, production과 staging에서는 승인 대기로 처리하며, Low만 존재하거나 범위 내 탐지가 없으면 PASS를 반환한다. 승인된 High는 탐지 기록과 점수에는 유지하되 게이트에서는 수용된 위험으로 관리한다.",
    )
    replace(
        "환경은 위계를 완화하지 않고 강화만 한다.",
        "환경 규칙은 상위 심각도의 처리를 유지하면서 운영 단계에 따라 Medium의 검토 수준을 조정한다. development와 feature에서는 개발 흐름을 유지하며 경고를 제공하고, production과 staging에서는 책임자의 명시적 승인을 요구한다. BLOCK과 BLOCK_PENDING_APPROVAL은 모두 후속 빌드·배포를 중단하되, 후자는 승인 이력과 재검사 경로를 제공한다.",
    )
    replace(
        "예를 들어 High 1건은 보조 점수가 95점일 수 있지만",
        "예를 들어 High 1건이 탐지되면 보조 점수는 95점일 수 있으나 판정은 BLOCK_PENDING_APPROVAL이므로 승인 전 배포가 중단된다. 이처럼 보조 점수와 판정의 역할을 분리하면 저장소 상태의 정량적 비교와 상위 위험의 엄격한 배포 통제를 함께 구현할 수 있다.",
    )

    # Chapter 4: exact environment, reproducible artifacts, and positive result interpretation.
    replace(
        "취약 웹앱 비교군(8개):",
        "검증용 취약 웹앱(8개): OWASP Juice-Shop, OWASP NodeGoat, DVNA, WebGoat, Vulnerable-Flask-App, django.nV, OWASP Benchmark 및 dvpwa를 사용하였다. 이 가운데 공식 테스트 케이스별 정답표가 실행 스냅샷에 포함된 OWASP Benchmark v1.2를 정량 정확도 평가에 사용하고, 나머지 7개 저장소는 탐지·판정 적용과 CWE 프로파일 비교에 활용하였다.",
    )
    replace(
        "DT 웹앱(14개):",
        "공개 DT 웹앱(14개): 표 4와 같이 Azure Digital Twins Explorer, Autodesk 기반 DT, DTaaS, iTwin.js 기반 구성요소, Vertexvis 3D 데모, OpenRemote, GeoTwin, NUS 캠퍼스 DT, 수질 DT 및 Meteor3DEditor를 선정하였다. 저장소별 분석 대상을 고정하기 위해 커밋 해시를 함께 기록하였다.",
    )
    replace(
        "수소추진선박 DT(1개):",
        "수소추진선박 DT(1개): hydrogen-ship-LBTS는 액체수소 이송 시스템(LBTS)의 상태를 시각화하는 웹 기반 DT로, React 프론트엔드, Unity WebGL 런타임, WebSocket 기반 실시간 동기화 및 Kubernetes 배포 설정으로 구성된다. 공개 DT 집합과 별도로 제4.4절의 심층 사례 분석에 사용하였다.",
    )
    replace(
        "실험 환경은 Ubuntu 기반 CI 서버에서",
        "실험은 Ubuntu 26.04 LTS, Intel N95 4코어(최대 3.40 GHz), 메모리 7.0 GiB 환경에서 수행하였다. 분석 도구는 Semgrep v1.157.0과 Gitleaks v8.30.1이며, 공개 DT 14개는 development 환경, 16개 정책 및 scan-only 워크플로로 실행하였다. 각 실행에서 pipeline_result.json, security_summary.json, security_findings.json, security_verdict.json과 원시 스캐너 보고서를 수집하였고, 재현 분석 코드는 파이프라인 저장소의 scripts/analyze_kci_paper_results.py에 포함하였다.",
    )
    replace(
        "정확도 평가는 OWASP Benchmark v1.2 정답표와",
        "정확도 평가는 OWASP Benchmark v1.2 정답표와 16종 정책이 공통으로 포함하는 CWE-22, CWE-78, CWE-79, CWE-89, CWE-327 및 CWE-614를 대상으로 수행하였다. 테스트 케이스 ID와 CWE가 모두 일치하는 범위 내 탐지를 TP·FP·FN으로 집계하고, CWE별 지표와 마이크로 합계를 산출하였다. 표 5와 같이 마이크로 합계는 TP 728, FP 639, FN 215이며 정밀도 0.533, 재현율 0.772, F1-Score 0.630이다.",
    )
    replace(
        "14개 공개 DT 웹앱의 기존 분석 커밋을 고정하고",
        "14개 공개 DT 웹앱은 표 4의 커밋을 고정하고 development 환경, 16개 정책 및 scan-only 워크플로로 재검사하였다. 모든 저장소에서 Gitleaks와 Semgrep 단계가 완료되었고, 판정에 필요한 JSON 산출물이 생성되었다. 저장소당 전체 분석 시간의 중앙값은 30.5초로, 서로 다른 규모와 기술 스택의 DT 저장소를 동일한 절차로 처리할 수 있음을 확인하였다.",
    )
    replace(
        "원시 탐지 482건 중 274건이",
        "원시 탐지 482건 가운데 274건이 16개 정책 범위에 포함되었으며, 208건은 후속 검토가 가능한 범위 외 결과로 분리되었다. 범위 내 분포는 Critical 69건, High 8건, Medium 197건으로 나타났다. CWE별로는 CWE-22 191건, CWE-798 45건, CWE-78 24건, CWE-319 8건 및 CWE-79 6건이며, 표 6의 저장소별 판정은 PASS 3개, WARN 1개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 9개로 구성되었다. 이 결과는 탐지 목록을 저장소별 수정 우선순위와 배포 의사결정으로 변환하는 제안 기법의 적용 가능성을 보여준다.",
    )
    replace(
        "SecuPipeline을 development 환경으로 실행한 결과",
        "SecuPipeline을 development 환경으로 실행한 결과, 보조 점수 94/100과 판정 BLOCK_PENDING_APPROVAL이 도출되었다. High 등급 CWE-319와 Medium 등급 CWE-79가 정책 범위에 포함되었으며, 표 7은 각 탐지의 정책 항목, 파일 및 코드 위치를 나타낸다.",
    )
    replace(
        "범위 외 탐지는 5건으로",
        "정책 카탈로그 밖에서는 Subresource Integrity 누락(CWE-353), 정규표현식 DoS(CWE-1333), runAsNonRoot 설정(CWE-250), Kubernetes 권한 설정(CWE-732) 및 CSRF 미들웨어(CWE-352)와 관련된 5건이 식별되었다. 이 결과는 범위 내 정책 판정과 함께 인프라·런타임 보안 검토 목록으로 보존하였다.",
    )
    replace(
        "범위 내 2건의 취약점은 단순한 코딩 실수가 아닌",
        "범위 내 2건은 웹 기반 DT의 실시간 통신과 동적 시각화 경계에서 확인된 보안 검토 지점이다.",
    )
    replace(
        "CWE-319(평문 WebSocket)는 Unity WebGL",
        "CWE-319 탐지는 Unity WebGL 런타임의 자동 생성 파일(BuildWeb.framework.js)에서 ws:// 연결 문자열이 사용된 지점이다. 자동 생성 코드를 직접 수정하기보다 Unity 빌드 설정과 리버스 프록시 계층에서 wss://를 강제하고, 센서 데이터 채널의 인증서와 종단 간 전송 보호를 적용하는 방식이 적합하다. 이 사례는 생성 코드까지 포함하는 DT 배포 산출물의 통신 설정을 소스 수준에서 추적할 필요성을 보여준다.",
    )
    replace(
        "CWE-79(XSS via dangerouslySetInnerHTML)는",
        "CWE-79 탐지는 React 구성요소 FuelEmission.tsx에서 연료 배출량 데이터를 dangerouslySetInnerHTML로 렌더링하는 지점이다. 센서·운영 데이터가 동적으로 시각화되는 DT 대시보드에서는 입력 데이터의 신뢰 경계를 명확히 하고, DOMPurify와 같은 정제 절차 또는 안전한 텍스트 렌더링 방식을 적용할 수 있다. 수소추진선박 사례에서 확인한 두 유형을 공개 DT 집합의 저장소 단위 분포와 연결하여 제4.5절에서 분석한다.",
    )
    replace(
        "취약 웹앱 8개와 공개 DT 웹앱 14개의 정책 범위 내 CWE 분포를 비교하였다.",
        "검증용 취약 웹앱 8개와 공개 DT 웹앱 14개의 정책 범위 내 CWE 분포를 저장소 단위로 비교하였다. 저장소 규모가 탐지 건수에 미치는 영향을 줄이기 위해 각 CWE가 저장소에서 1건 이상 관찰되었는지를 분석 단위로 사용하고, DT 대비 취약 웹앱의 Odds Ratio와 양측 Fisher 정확 검정 p-value를 산출하였다.",
    )
    replace(
        "표의 분자는 해당 CWE가 한 건 이상 탐지된 저장소 수이며",
        "표 8의 분자는 해당 CWE가 한 건 이상 탐지된 저장소 수이고, 괄호 안은 전체 탐지 레코드 수이다. Odds Ratio는 DT 집합의 탐지 보유 오즈를 취약 웹앱 집합의 오즈로 나눈 값이다. 이 분석은 모집단 전체의 우열보다 본 실험 집합에서 나타난 CWE 구성과 DT 문맥 검토 지점을 파악하는 데 목적이 있다.",
    )
    replace(
        "CWE-319는 취약 웹앱 4/8개와 DT 2/14개에서",
        "공개 DT 집합에서는 CWE-798이 8/14개 저장소에서 관찰되어 가장 넓은 저장소 보유율을 보였으며, 실시간 통신과 동적 시각화에 연결되는 CWE-319와 CWE-79도 각각 2/14개와 3/14개 저장소에서 확인되었다. CWE-89는 취약 웹앱 7/8개에서 관찰된 반면 DT 집합에서는 관찰되지 않아 두 집합의 구성 차이가 뚜렷하게 나타났다(p<0.001). CWE-319와 CWE-79의 집단 차이는 본 표본에서 통계적 확정 범위에 도달하지 않았으나(p=0.1365, p=0.0815), 수소추진선박 사례와 공개 저장소에서 실제 코드 위치가 확인되어 DT 구성요소별 검토 항목을 구체화하는 근거를 제공한다. 따라서 본 결과는 16종 정책을 기반으로 한 최초의 저장소 단위 DT 보안 프로파일과 후속 비교 연구의 기준선을 제시한다.",
    )
    replace(
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 정적 보안 특성을",
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 소스 코드 보안 상태를 2단계 정적 분석, 16종 CWE 정책, 심각도 기반 보조 점수 및 환경 민감형 게이트로 연결하는 측정 기법을 제안하였다. OWASP Benchmark v1.2의 정책 중첩 6개 CWE에서 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 확인하였고, 공개 DT 14개에서는 482건의 원시 탐지 중 274건을 정책 범위 결과로 구조화하여 PASS 3개, WARN 1개, 승인 대기 1개 및 BLOCK 9개의 저장소별 판정을 도출하였다. 또한 수소추진선박 DT 사례를 통해 Unity WebGL 통신 설정의 CWE-319와 React 동적 시각화 지점의 CWE-79를 식별하고, 수정 방향을 DT 문맥에서 제시하였다.",
    )
    replace(
        "본 연구의 한계는 다음과 같다.",
        "본 연구는 공개 코드와 정적 분석 결과를 중심으로 재현 가능한 기준선을 구축하였다. 결과의 적용 범위를 확장하기 위해서는 16종 정책 전반의 전문가 라벨링, 생성 코드의 도달 가능성 검증, 일반 운영 웹앱과의 규모·언어 매칭 및 규칙 revision 고정이 후속 단계로 요구된다. 또한 14개 DT 실행에서 기록된 비치명적 파싱·타임아웃·내부 매칭 경고는 분석 산출물에 함께 보존하여, 후속 연구에서 도구 지원 범위와 탐지 커버리지를 정밀하게 평가할 수 있도록 하였다.",
    )
    replace(
        "향후 연구에서는 일반 운영 웹앱으로 통제 비교군을 확장하고",
        "향후 연구에서는 DT 저장소를 30개 이상으로 확대하고 도메인·언어·코드 규모를 통제한 일반 운영 웹앱 비교군을 구성하여 프로파일 검정력을 높일 계획이다. Critical·High 전수와 Medium 표본에 대한 복수 전문가 검토, 규칙별 정밀도 및 일치도 분석을 수행하고, Semgrep 규칙 revision과 Gitleaks 설정을 재현 패키지로 고정한다. 나아가 SCA, DAST, 컨테이너 이미지 검사 및 런타임 네트워크 추적을 결합하고, 보안 게이트 적용 전후의 수정 효과와 재검사 결과를 비교함으로써 웹 기반 DT DevSecOps의 통합 검증 체계로 확장하고자 한다.",
    )

    # Correct three verified bibliographic records.
    replace(
        "J. Voas, R. Kuhn",
        'J. Voas, P. Mell, P. Laplante, and V. Piroumian, "Security and Trust Considerations for Digital Twin Technology," NIST Interagency/Internal Report 8356, Feb. 2025, doi: 10.6028/NIST.IR.8356.',
    )
    replace(
        "H. Mun, J. Lee",
        'H. Mun, K. Han, E. Damiani, H. K. Yeun, T.-Y. Kim, L. Martino, and C. Y. Yeun, "A Comprehensive Survey on Digital Twin: Focusing on Security Threats and Requirements," IEEE Access, vol. 13, pp. 73362–73390, 2025, doi: 10.1109/ACCESS.2025.3563621.',
    )
    replace(
        "C. Dietz, P. Tndewehr",
        'M. Dietz, L. Hageman, C. von Hornung, and G. Pernul, "Employing Digital Twins for Security-by-Design System Testing," in Proc. 2022 ACM Workshop on Secure and Trustworthy Cyber-Physical Systems, pp. 97–106, 2022.',
    )

    # Add pinned commits to Table 4.
    add_column(tables[3])
    set_table(
        tables[3],
        [
            ["ID", "리포지토리", "기술 스택", "고정 커밋"],
            ["DT1", "Azure-Samples/digital-twins-explorer", "Azure Digital Twins Explorer 웹앱", "9ab15752"],
            ["DT2", "Autodesk-Forge/forge-digital-twin", "Node.js, Express, Autodesk Viewer", "7c8de245"],
            ["DT3", "autodesk-platform-services/aps-digital-twin", "Autodesk Viewer 기반 DT demo", "282c650c"],
            ["DT4", "INTO-CPS-Association/DTaaS", "Digital Twin as a Service, 웹 client 포함", "0aad95d1"],
            ["DT5", "iTwin/itwinjs-core", "WebGL, TypeScript 기반 인프라 DT", "5fca8fc2"],
            ["DT6", "iTwin/viewer-components-react", "iTwin.js 기반 React viewer", "1cf1f1d4"],
            ["DT7", "Vertexvis/digital-twin-demo", "3D 시각화와 시계열 센서 데이터", "7f07cf2a"],
            ["DT8", "Vertexvis/collaboration-demo", "React/Next.js 실시간 협업", "c4c05bcd"],
            ["DT9", "Vertexvis/visual-analytics-demo", "3D analytics overlay", "3a3de721"],
            ["DT10", "openremote/openremote", "IoT/asset management 플랫폼", "a5337138"],
            ["DT11", "Geo-Twin/GeoTwin", "Flood simulation DT framework", "62c57aab"],
            ["DT12", "City-Syntax/nus-digital-twin", "CesiumJS/Astro 캠퍼스 DT", "5366455d"],
            ["DT13", "j03rul4nd/digital-twin-water", "Three.js 센서 시뮬레이션", "1b948089"],
            ["DT14", "nikonikoCW/Meteor3DEditor", "Three.js/Vue3 DT·IoT 대시보드", "509a45dd"],
        ],
    )

    # Insert figure, algorithm, and English table captions.
    image_bytes = create_process_figure(figure_path)
    relationships = ET.fromstring(payload["word/_rels/document.xml.rels"])
    numeric_ids = []
    for relationship in relationships:
        value = relationship.get("Id", "")
        if value.startswith("rId") and value[3:].isdigit():
            numeric_ids.append(int(value[3:]))
    image_rid = f"rId{max(numeric_ids, default=0) + 1}"
    ET.SubElement(
        relationships,
        REL + "Relationship",
        {
            "Id": image_rid,
            "Type": "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
            "Target": "media/secu_pipeline_flow.png",
        },
    )
    placeholder = find_paragraph("[그림 1:")
    set_drawing(placeholder, image_rid)
    insert_after(placeholder, "Fig. 1. Overall process of the proposed SecuPipeline security measurement method")

    algorithm_target = find_paragraph("게이트는 우선순위 순으로 동작한다.")
    insert_before(
        algorithm_target,
        "Algorithm 1. Environment-sensitive security gate\nINPUT: C_C, C_H, C_M, C_L, environment, approved_high\nIF C_C ≥ 1 THEN BLOCK\nELSE IF unapproved C_H ≥ 1 THEN BLOCK_PENDING_APPROVAL\nELSE IF C_M ≥ 1 AND environment ∈ {production, staging} THEN BLOCK_PENDING_APPROVAL\nELSE IF C_M ≥ 1 THEN WARN\nELSE PASS",
    )

    captions = [
        "Table 1. Mapping of security policy items to OWASP Top 10 and CWE",
        "Table 2. Severity weights, deduction caps, and gate handling",
        "Table 3. Environment-sensitive security gate rules",
        "Table 4. Public digital twin repositories and pinned commits",
        "Table 5. Detection accuracy on OWASP Benchmark v1.2",
        "Table 6. Security measurement results for 14 public DT web applications",
        "Table 7. In-scope findings in the hydrogen-powered ship digital twin",
        "Table 8. Repository-level comparison of CWE profiles",
    ]
    for table, caption in zip(tables, captions, strict=True):
        insert_before(table, caption)

    # Ensure the results discussion follows its table and add Benchmark interpretation.
    benchmark_table = tables[4]
    insert_after(
        benchmark_table,
        "CWE-22, CWE-78 및 CWE-89의 재현율은 각각 0.902, 0.929 및 0.930으로 나타났으며, CWE-79의 F1-Score는 0.727이었다. CWE-614는 정밀도와 재현율이 모두 1.000으로 확인되었다. CWE-327 결과는 현재 룰셋 확장 시 우선 보강할 정책 항목을 구체적으로 보여주며, 전체 결과는 높은 재현율을 유지하면서 정밀도 향상을 위한 규칙 정제가 가능한 기준선을 제공한다.",
    )

    content_types = ET.fromstring(payload["[Content_Types].xml"])
    if not any(item.get("Extension") == "png" for item in content_types.findall(CT + "Default")):
        ET.SubElement(content_types, CT + "Default", {"Extension": "png", "ContentType": "image/png"})

    payload["word/document.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    payload["word/_rels/document.xml.rels"] = ET.tostring(relationships, encoding="utf-8", xml_declaration=True)
    payload["[Content_Types].xml"] = ET.tostring(content_types, encoding="utf-8", xml_declaration=True)
    payload["word/media/secu_pipeline_flow.png"] = image_bytes

    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=destination.name + ".", suffix=".tmp", delete=False
    ) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w", compression=zipfile.ZIP_DEFLATED) as output:
            written = set()
            for info, _ in entries:
                output.writestr(info, payload[info.filename])
                written.add(info.filename)
            for name, data in payload.items():
                if name not in written:
                    output.writestr(name, data)
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: rewrite_web_dt_kci_paper.py SOURCE.docx DESTINATION.docx FIGURE.png"
        )
    main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
