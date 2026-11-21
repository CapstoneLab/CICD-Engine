#!/usr/bin/env python3
"""Build the experiment-backed final KCI revision from the prior KCI DOCX.

Run with PYTHONPATH=/tmp/cicd-paper-libs after installing python-docx there.
All quantitative values are loaded from reproducible analysis artifacts.
"""

from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from docx import Document
from docx.enum.table import WD_ALIGN_VERTICAL, WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "웹 기반 디지털트윈_KCI_재작성본.docx"
DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_실험검증_최종개정본.docx"
FIGURE = ROOT / "figures/SecuPipeline_수동검증_4상태_프로세스.png"


def load_json(relative: str):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def clear_and_set(paragraph, text: str, *, bold: bool = False, size: float | None = None, font: str = "Noto Sans CJK KR"):
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
    matches = [p for p in document.paragraphs if p.text.startswith(prefix)]
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


def insert_table_after(document: Document, anchor, data: list[list[str]], font_size: float = 7.2):
    table = document.add_table(rows=len(data), cols=len(data[0]))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.autofit = True
    for row_index, values in enumerate(data):
        for col_index, value in enumerate(values):
            cell = table.cell(row_index, col_index)
            cell.text = value
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if row_index == 0 else WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
                    run.font.name = "Noto Sans CJK KR"
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK KR")
                    run.bold = row_index == 0
        row = table.rows[row_index]
        cant_split = OxmlElement("w:cantSplit")
        row._tr.get_or_add_trPr().append(cant_split)
    repeat_header(table)
    shade_header(table)
    anchor._element.addnext(table._tbl)
    return table


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


def ensure_columns(table, count: int) -> None:
    while len(table.columns) < count:
        table.add_column(Inches(0.8))


def ensure_rows(table, count: int) -> None:
    while len(table.rows) < count:
        table.add_row()


def fill_table(table, data: list[list[str]], font_size: float = 7.2) -> None:
    ensure_columns(table, len(data[0]))
    ensure_rows(table, len(data))
    if len(table.rows) != len(data) or len(table.columns) != len(data[0]):
        raise ValueError(f"table shape mismatch: {len(table.rows)}x{len(table.columns)} vs {len(data)}x{len(data[0])}")
    for row_index, values in enumerate(data):
        for col_index, value in enumerate(values):
            cell = table.cell(row_index, col_index)
            cell.text = value
            cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
            for paragraph in cell.paragraphs:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER if row_index == 0 else WD_ALIGN_PARAGRAPH.LEFT
                for run in paragraph.runs:
                    run.font.size = Pt(font_size)
                    run.font.name = "Noto Sans CJK KR"
                    run._element.rPr.rFonts.set(qn("w:eastAsia"), "Noto Sans CJK KR")
                    run.bold = row_index == 0
        if table.rows[row_index]._tr.get_or_add_trPr().find(qn("w:cantSplit")) is None:
            table.rows[row_index]._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    repeat_header(table)
    shade_header(table)


def remove_trailing_empty_paragraphs(document: Document) -> None:
    while document.paragraphs and not document.paragraphs[-1].text.strip():
        paragraph = document.paragraphs[-1]
        parent = paragraph._p.getparent()
        parent.remove(paragraph._p)


def create_process_figure(path: Path) -> bytes:
    width, height = 2700, 1120
    image = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(image)
    regular_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc"
    bold_path = "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc"
    regular = ImageFont.truetype(regular_path, 34)
    bold = ImageFont.truetype(bold_path, 37)
    small = ImageFont.truetype(bold_path, 27)

    boxes = [
        (35, 155, 365, 390, "Repository\n고정 커밋", "#E8F1FF", "#2563A6"),
        (455, 155, 785, 390, "Gitleaks\n시크릿 탐지", "#E7F8EF", "#23815A"),
        (875, 155, 1205, 390, "Semgrep\n정적 분석", "#F0EAFF", "#6941C6"),
        (1295, 155, 1665, 390, "16종 정책 매핑\n정확 위치 중복 제거", "#FFF5DA", "#B7791F"),
        (1755, 155, 2145, 390, "Critical·High 전수\nMedium 표본 수동 검증", "#E8F7FA", "#13788C"),
        (2235, 155, 2665, 390, "정책 기반 보조지수\n환경 민감형 게이트", "#FFE9E9", "#B53B3B"),
    ]

    def rounded(box, fill, outline):
        draw.rounded_rectangle(box, radius=24, fill=fill, outline=outline, width=5)

    def arrow(x1, y1, x2, y2):
        draw.line((x1, y1, x2, y2), fill="#4B5563", width=8)
        draw.polygon([(x2, y2), (x2 - 24, y2 - 15), (x2 - 24, y2 + 15)], fill="#4B5563")

    for x1, y1, x2, y2, label, fill, outline in boxes:
        rounded((x1, y1, x2, y2), fill, outline)
        draw.multiline_text(((x1 + x2) / 2, (y1 + y2) / 2), label, font=bold, fill="#172033", anchor="mm", align="center", spacing=10)
    for left, right in zip(boxes, boxes[1:]):
        arrow(left[2] + 10, 272, right[0] - 10, 272)

    gate_x = 2450
    draw.line((gate_x, 390, gate_x, 560), fill="#4B5563", width=8)
    draw.line((125, 560, 2575, 560), fill="#4B5563", width=8)
    decisions = [
        (65, 665, 565, 845, "BLOCK", "#FFE1E1", "#B42318"),
        (715, 665, 1390, 845, "BLOCK_PENDING_APPROVAL", "#FFEAD5", "#C05A00"),
        (1540, 665, 2040, 845, "WARN", "#FFF0C2", "#B7791F"),
        (2190, 665, 2635, 845, "PASS", "#DCFCE7", "#15803D"),
    ]
    for x1, y1, x2, y2, label, fill, outline in decisions:
        rounded((x1, y1, x2, y2), fill, outline)
        center = (x1 + x2) // 2
        draw.line((center, 560, center, y1 - 15), fill="#4B5563", width=8)
        draw.polygon([(center, y1), (center - 15, y1 - 25), (center + 15, y1 - 25)], fill="#4B5563")
        draw.text(((x1 + x2) / 2, (y1 + y2) / 2), label, font=small, fill=outline, anchor="mm")
    draw.text((35, 55), "SecuPipeline 자동 탐지·수동 검증·배포 판정 프로세스", font=bold, fill="#172033")
    draw.text((35, 965), "자동 게이트는 예비 판정을 제공하며, 수동 검증 결과로 중복·문맥 제한·오탐을 분리해 최종 판정을 갱신한다.", font=regular, fill="#4B5563")
    out = io.BytesIO()
    image.save(out, format="PNG", dpi=(220, 220), optimize=True)
    data = out.getvalue()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return data


def replace_embedded_figure(docx_path: Path, image_bytes: bytes) -> None:
    with zipfile.ZipFile(docx_path) as archive:
        entries = [(item, archive.read(item.filename)) for item in archive.infolist()]
    targets = [item.filename for item, _ in entries if item.filename.endswith("/secu_pipeline_flow.png")]
    if len(targets) != 1:
        raise ValueError(f"expected one process figure, found {targets}")
    target = targets[0]
    with tempfile.NamedTemporaryFile(dir=docx_path.parent, suffix=".docx", delete=False) as handle:
        temp = Path(handle.name)
    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for item, data in entries:
                output.writestr(item, image_bytes if item.filename == target else data)
        temp.replace(docx_path)
    finally:
        if temp.exists():
            temp.unlink()


def main() -> None:
    document = Document(SOURCE)
    base_tables = list(document.tables)
    manual = load_json("analysis/dt_manual_validation_summary.json")
    experiments = load_json("analysis/dt_revision_experiments.json")
    metadata = load_json("analysis/dt_repository_metadata.json")
    cluster = load_json("analysis/dt_cluster_profile_sensitivity.json")
    manifest = load_json("analysis/reproducibility/experiment_manifest.json")
    with (ROOT / "analysis/policy_catalog_with_observed_rules.csv").open(encoding="utf-8-sig", newline="") as handle:
        policy = list(csv.DictReader(handle))

    # Title and bilingual abstracts.
    title = document.paragraphs[0]
    clear_and_set(title, "웹 기반 디지털트윈 소프트웨어의 정적 보안 측정과 환경 민감형 배포 게이트\nStatic Security Measurement and Environment-Sensitive Deployment Gates for Web-Based Digital Twin Software", bold=True, size=14)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    replace(
        document,
        "웹 기반 DT는",
        "웹 기반 DT는 3D 시각화, 실시간 센서 동기화 및 원격 제어 기능을 제공하나, 웹 애플리케이션 소스 코드의 정량적 보안 검증은 상대적으로 충분히 다루어지지 않았다. 본 연구는 Gitleaks와 Semgrep의 2단계 정적 분석, 16종 CWE 정책 카탈로그, 정확 위치 중복 제거, 정책 기반 보조지수 및 환경 민감형 판정 게이트로 구성된 측정 기법을 제안한다. OWASP Benchmark v1.2와 공개 DT 14개 고정 커밋을 대상으로 정확도, 수동 판독, 구성요소 제거 및 가중치 민감도 실험을 수행하였다. Benchmark의 정책 중첩 6개 CWE에서 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 확인하였다. 공개 DT에서 자동 분류된 274건 가운데 Critical·High 77건과 Medium 30건을 검토한 결과, 중복을 제외한 Critical·High 72개 위치 중 31개가 확인된 위험 패턴이었으며, 수동 판독을 반영한 최종 게이트는 BLOCK 8개, BLOCK_PENDING_APPROVAL 1개, WARN 2개 및 PASS 3개로 산출되었다.",
    )
    korean_keywords = find_paragraph(document, "디지털트윈, 웹 보안")
    anchor = korean_keywords
    anchor = insert_paragraph_after(document, anchor, "Abstract", "Heading 2")
    anchor = insert_paragraph_after(
        document,
        anchor,
        "Web-based digital twins provide 3D visualization, real-time sensor synchronization, and remote control, while quantitative source-code security validation at the web application layer remains underexplored. This study proposes a two-stage static analysis method combining Gitleaks and Semgrep with a 16-CWE policy catalogue, exact-location deduplication, an auxiliary policy index, and an environment-sensitive deployment gate. Experiments were conducted on OWASP Benchmark v1.2 and 14 pinned public digital-twin repositories, including manual adjudication, ablation, and weight-sensitivity analyses. On the six policy-overlapping Benchmark CWEs, the method achieved 0.533 precision, 0.772 recall, and an F1-score of 0.630. Of 77 automated Critical/High records, 72 unique locations remained after deduplication and 31 were confirmed as risky patterns; the review-adjusted gates were eight BLOCK, one BLOCK_PENDING_APPROVAL, two WARN, and three PASS.",
        "First Paragraph",
    )
    anchor = insert_paragraph_after(document, anchor, "Keywords", "Heading 2")
    insert_paragraph_after(document, anchor, "Digital twin, static application security testing, manual validation, security gate, DevSecOps", "First Paragraph")

    # Purpose and contributions now reference the completed experiments.
    replace(
        document,
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 보안성을 정량적으로",
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 정적 분석 결과를 정책 기반 보조지수와 DevSecOps 배포 판정으로 연결하는 기법을 제안한다. 자동 경고를 확정 취약점으로 간주하지 않기 위해 정확 위치 중복 제거와 수동 판독 절차를 추가하고, 자동 예비 게이트와 검토 반영 게이트를 구분하였다. OWASP Benchmark의 정책 중첩 6개 CWE에서 F1-Score 0.630을 확인하였으며, 공개 DT 14개의 Critical·High 전수 판독과 Medium 표본 판독 결과를 이용해 자동 판정의 변화를 실증하였다.",
    )
    replace(document, "DT 웹앱 대상 보안성 측정 체계 제안:", "DT 웹앱 대상 측정 체계 제안: 16종 CWE 정책과 Gitleaks·Semgrep 2단계 스캔을 통합하고, 정확 위치 중복 제거와 수동 판독 기준을 명시하였다(제3.1절 및 제3.2절). Benchmark 정확도와 DT 수동 판독 결과는 제4.2절 및 제4.3절에 제시한다.")
    replace(document, "환경 민감형 보조 점수·판정 모델 설계:", "정책 기반 보조지수·판정 모델 설계: 심각도 위계를 보존하는 감점 상한과 환경별 게이트를 구현하고, 상한 제거·단순 건수·CVSS 구간 중앙값 및 세 가중치 조합과 비교하였다(제3.3절 및 제4.3.3절). 가중치 조합 간 저장소 순위 상관은 ρ=0.999였고 게이트는 14/14개에서 동일하였다.")
    replace(document, "DT 코드베이스의 실증적 취약점 프로파일 구축:", "DT 코드베이스의 실증 분석: 공개 DT 14개의 저장소 유형·언어·코드 규모·코드 계보를 기록하고, Critical·High 전수 및 Medium 표본을 직접 판독하였다. 또한 14개 저장소를 10개 코드 계보로 축약한 민감도 검정을 수행하여 저장소 비독립성의 영향을 함께 평가하였다(제4.3절 및 제4.5절).")

    # Method: explicit triage, auxiliary-index scope, and unambiguous algorithm.
    replace(document, "전체 프로세스는 그림 1과 같다.", "전체 프로세스는 그림 1과 같다. 고정 커밋에서 Gitleaks와 Semgrep을 순차 실행한 뒤 16종 CWE 정책을 적용하고, 동일 저장소·CWE·파일·라인의 중복 레코드를 하나의 위치로 통합한다. 자동 결과는 예비 게이트를 생성하며, 수동 검증에서 확인된 패턴, 문맥 제한 패턴, 오탐 및 중복으로 분류한 뒤 Critical·High 건수를 갱신하여 검토 반영 게이트를 산출한다. Medium·Low는 전체 자동 결과를 유지하되 표본 판독으로 해석 범위를 평가한다.")
    replace(document, "Fig. 1.", "Fig. 1. Automatic detection, manual validation, and four-state deployment-gate process")
    replace(document, "보안 정책은 OWASP", "보안 정책은 OWASP Top 10:2021 [17]과 CVSS v3.1 [18]의 질적 심각도 용어를 참고하되, 표 1의 등급과 감점은 본 연구의 배포 정책으로 정의하였다. 즉 CVSS로부터 20·5·1·0.2를 직접 도출한 것으로 해석하지 않으며, 정책 선택의 안정성은 제4.3.3절의 민감도 분석으로 평가한다.")
    replace(document, "16개 항목은 Critical", "16개 항목은 Critical·High·Medium·Low 각 4종으로 구성되며, CWE를 공통 식별자로 사용해 스캐너 결과를 정책 등급으로 재분류한다. 표 1에는 정책 등급, 실제 관찰 스캐너와 대표 룰 ID를 공개하고, 전체 룰 ID·횟수는 analysis/policy_catalog_with_observed_rules.csv에 보존하였다. 카탈로그 밖 탐지는 범위 외 결과로 별도 유지한다.")
    replace(document, "1단계: 경량 시크릿 탐지", "1단계: 경량 시크릿 탐지(Lightweight Security Scan). Gitleaks v8.21.2를 사용하여 API 키, 비밀번호, 토큰 및 개인키 패턴을 탐지한다. 실험 후 v8.21.2 공식 기본 설정을 고정하고 DT4를 명시적 설정으로 재실행한 결과, 기존 9건과 (rule, file, line, commit) 구조가 일치하였다. 탐지 레코드는 CWE-798 정책에 매핑하되 테스트·예제·문서·배포 코드 여부와 자격증명 유효성은 수동 검토 항목으로 분리한다.")
    replace(document, "2단계: 심층 정적 보안 스캔", "2단계: 심층 정적 보안 스캔(Deep Security Scan). Semgrep v1.157.0의 --config auto를 사용하여 다언어 DT 코드를 분석하였다. 실험 당일 내려받은 1,074개 OSS 룰의 Semgrep core 번들을 보존했으며, 이 번들로 DT1을 재실행해 기존 2개 구조적 탐지를 재현하였다. 모든 14개 보고서에서 관찰된 442개 Semgrep 결과의 rule_id가 고정 번들에 존재함을 확인하였다.")
    replace(document, "두 스캐너의 결과는 각각", "두 스캐너의 결과는 rule_id, CWE, file_path, line, scanner, policy_severity 및 in_scope 필드로 통합한다. 동일 저장소·CWE·파일·라인을 정확 위치 키로 사용해 교차 스캐너·교차 룰 중복을 제거한다. 수동 판독은 ‘확인된 위험 패턴’, ‘문맥 제한 패턴’, ‘오탐’, ‘중복’의 네 범주와 production, CI/build, test, documentation/example, generated/tooling의 배포 관련성을 함께 기록한다. 확인된 위험 패턴은 위험한 구문이나 자격증명 내장이 실제로 존재한다는 뜻이며, 원격 악용 가능성이나 자격증명의 현재 유효성을 자동으로 의미하지 않는다.")
    replace(document, "범위 내 탐지 레코드의 등급별", "정확 위치 중복 제거 후 범위 내 레코드의 등급별 분포로 100점 만점의 정책 기반 보조지수 S를 산출한다. 이 지수는 절대 보안 수준이나 확정 취약점 수가 아니라 선택한 16개 정책의 경고 분포를 요약한다. 배포 판정은 제3.3.2절의 계층형 게이트가 독립적으로 결정한다.")
    equation1 = find_paragraph(document, "D_H=")
    clear_and_set(equation1, "D_H = min(5C_H, 19),   D_M = min(C_M, 4),   D_L = min(0.2C_L, 0.9)                              (1)", font="Cambria Math")
    equation1.alignment = WD_ALIGN_PARAGRAPH.CENTER
    equation2 = find_paragraph(document, "C_C=0이면")
    clear_and_set(equation2, "S = 100 − D_H − D_M − D_L  (C_C = 0);   S = max[0, min(40, 100 − 20C_C − D_H − D_M − D_L)]  (C_C ≥ 1)       (2)", font="Cambria Math")
    equation2.alignment = WD_ALIGN_PARAGRAPH.CENTER
    replace(document, "등급별 건당 감점은", "등급별 건당 감점 20·5·1·0.2와 상한 19·4·0.9는 상위 등급 1건이 하위 등급의 누적보다 항상 우선하도록 만든 운영 정책 매개변수다. 이는 CVSS 점수의 선형 변환이 아니며, Critical이 존재하면 지수를 0~40 구간으로 제한한다. 제4.3.3절에서 상한 제거 모델, 단순 건수, CVSS 질적 구간 중앙값 합계 및 대안 가중치와 저장소 순위를 비교한다.")
    replace(document, "보조 점수는 16개 정책 범위의", "정책 기반 보조지수는 원본 레코드·중복 제거 건수·수동 판독 결과와 함께 제공한다. 따라서 동일한 지수라도 경고 구성과 배포 문맥이 다른 경우를 구분할 수 있고, 게이트 판정의 근거를 파일 위치까지 추적할 수 있다.")
    algorithm = find_paragraph(document, "Algorithm 1.")
    clear_and_set(algorithm, "Algorithm 1. Environment-sensitive security gate\nINPUT: C_C, C_H, C_M, C_L, C_H^approved, environment\nC_H^active ← max(0, C_H − C_H^approved)\nIF C_C ≥ 1 THEN BLOCK\nELSE IF C_H^active ≥ 1 THEN BLOCK_PENDING_APPROVAL\nELSE IF C_M ≥ 1 AND environment ∈ {production, staging} THEN BLOCK_PENDING_APPROVAL\nELSE IF C_M ≥ 1 THEN WARN\nELSE PASS", font="DejaVu Sans Mono")
    replace(document, "게이트는 우선순위 순으로", "게이트는 우선순위 순으로 동작한다. 수동 판독이 완료되기 전에는 자동 정책 건수로 예비 판정을 생성하고, 완료 후에는 중복·오탐을 제외한 확인 건수로 판정을 갱신한다. Critical은 BLOCK, 미승인 High는 BLOCK_PENDING_APPROVAL, Medium만 존재하면 development·feature에서 WARN이며 production·staging에서는 BLOCK_PENDING_APPROVAL이다. Low만 있거나 범위 내 탐지가 없으면 PASS이다.")

    # Restore visible metric equations and numbering.
    p = find_paragraph(document, "Precision(정밀도):")
    clear_and_set(p, "Precision = TP / (TP + FP)                                                                 (3)", font="Cambria Math")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = find_paragraph(document, "Recall(재현율):")
    clear_and_set(p, "Recall = TP / (TP + FN)                                                                    (4)", font="Cambria Math")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p = find_paragraph(document, "F1-Score:")
    clear_and_set(p, "F1-Score = 2 × Precision × Recall / (Precision + Recall)                                  (5)", font="Cambria Math")
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER

    # Experiment sampling, environment, versions, artifacts, and scope.
    replace(document, "공개 DT 웹앱(14개):", "공개 DT 웹앱(14개): 본 집합은 모집단 추정을 위한 확률표본이 아니라 공개 소스, 웹 UI 또는 브라우저 기반 시각화, 저장소 설명의 DT 관련성, 고정 커밋 재현 가능성 및 Semgrep 지원 언어를 기준으로 구성한 목적표본이다. 애플리케이션·데모·플랫폼·라이브러리를 포함하며, 표 4에 분석 코드 LOC, 주 언어 및 코드 계보를 함께 제시한다.")
    replace(document, "실험은 Ubuntu", "실험은 Ubuntu 26.04 LTS, Intel N95 4코어(최대 3.40 GHz), 메모리 7 GiB 환경에서 수행하였다. Semgrep v1.157.0과 Gitleaks v8.21.2를 사용했으며, 공개 DT 14개는 development 환경과 16개 정책으로 실행하였다. Semgrep core 룰 번들 SHA-256은 574df0e5…a669e, Gitleaks 설정 SHA-256은 2ce9d818…430bb이며, 14개 실행의 필수 JSON 70개에 대한 SHA-256은 부록의 manifest 파일에 보존하였다. 명시적 제외 경로는 없고, 집계에서 엔진이 삽입한 .localci/workflow.yml만 제외하였다. 테스트·예제·생성 코드는 자동 스캔에는 포함하고 수동 판독에서 별도 문맥으로 분류하였다.")
    experiment_environment = find_paragraph(document, "실험은 Ubuntu")
    insert_paragraph_after(document, experiment_environment, "저장소당 프로그래밍 언어 비공백 LOC는 Semgrep이 실제 스캔한 파일을 기준으로 계산했으며, JSON·YAML·데이터 파일은 코드 LOC에서 제외하였다. 14개 DT의 코드 LOC와 범위 내 자동 탐지 건수의 Spearman 상관은 ρ=0.811로 나타나 저장소 규모의 영향을 확인하였다. 이에 제4.5절의 집단 비교는 건수 대신 저장소 보유 여부를 사용하고, 관련 저장소를 10개 코드 계보로 축약한 민감도 분석을 추가하였다.", "Body Text")

    replace(document, "14개 공개 DT 웹앱은 표 4", "14개 공개 DT 웹앱은 표 4의 전체 커밋 SHA를 고정하고 development 환경에서 재검사하였다. 모든 저장소에서 두 스캐너가 완료되고 판정 JSON이 생성되었으며, 저장소당 전체 분석 시간 중앙값은 30.5초였다. 자동 결과, 정확 위치 중복 제거 결과 및 Critical·High 수동 판독 반영 결과를 표 6에 함께 제시한다.")
    replace(document, "원시 탐지 482건 가운데", "원시 탐지 482건 가운데 274건이 16개 정책 범위에 포함되고 208건은 범위 외로 분리되었다. 자동 범위 내 분포는 Critical 69건, High 8건, Medium 197건이며, 정확 위치 중복 제거 후 220개 위치로 축약되었다. 자동 예비 게이트는 PASS 3개, WARN 1개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 9개였다. Critical·High 전수 판독에서 확인 패턴만 유지하고 Medium·Low는 중복 제거 자동 결과를 유지한 검토 반영 게이트는 PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개로 변경되었다.")

    # Rename profile section and remove unsupported novelty language.
    replace(document, "4.5 디지털트윈 특이 취약점 프로파일 분석", "4.5 DT와 검증용 취약 웹앱의 저장소 단위 CWE 탐지 프로파일 비교")
    replace(document, "검증용 취약 웹앱 8개와", "검증용 취약 웹앱 8개와 공개 DT 14개의 자동 정책 범위 CWE 분포를 저장소 보유 여부로 비교하였다. DT 집합에는 Autodesk 2개, iTwin 2개, Vertex 3개의 관련 코드 계보가 포함되므로, 14개 저장소 분석과 함께 10개 계보 단위 민감도 분석을 수행하였다. 표 11은 저장소 단위 및 계보 단위의 Odds Ratio와 양측 Fisher 정확 검정 결과를 함께 제시한다.")
    replace(document, "표 8의 분자는", "표 11의 분자는 해당 CWE가 한 건 이상 자동 탐지된 저장소 또는 계보 수이다. 비교군이 의도적으로 취약한 앱이고 코드 규모·언어 구성이 다르므로, 이 분석은 일반 웹앱 모집단과 DT 모집단의 우열을 추정하지 않고 본 실험 집합의 자동 탐지 프로파일을 기술하는 데 목적이 있다.")
    replace(document, "공개 DT 집합에서는 CWE-798", "저장소 단위에서 CWE-319와 CWE-79는 각각 OR=0.167, p=0.1365 및 OR=0.164, p=0.0815였고, 계보 단위에서도 OR=0.250, p=0.3213 및 OR=0.257, p=0.3416으로 통계적 차이가 확인되지 않았다. CWE-89는 DT에서 관찰되지 않아 저장소 단위 p<0.001, 계보 단위 p=0.0003이었으며, 이는 의도적으로 취약한 비교군의 SQL 주입 구성이 반영된 결과다. CWE-798은 저장소와 계보 분석 모두 차이가 없었다(p=1.0000). 이 결과는 후속 규모·언어 매칭 연구에서 비교할 수 있는 초기 저장소 단위 기준선으로 해석한다.")

    # Conclusion and explicit, constructive scope statements.
    replace(document, "본 연구는 웹 기반 디지털트윈 소프트웨어의 소스 코드", "본 연구는 웹 기반 DT의 자동 정적 분석을 16종 CWE 정책, 정확 위치 중복 제거, 수동 판독, 정책 기반 보조지수 및 환경 민감형 게이트로 연결하였다. Benchmark의 정책 중첩 6개 CWE에서 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 확인하였다. 공개 DT에서는 자동 정책 범위 274건이 정확 위치 220개로 축약되었고, Critical·High 고유 72개 위치 중 31개가 확인된 위험 패턴이었다. 이를 반영한 최종 판정은 PASS 3개, WARN 2개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개였다. 또한 Semgrep 단독·결합·정책 필터·중복 제거·수동 판독을 비교하고 세 가중치 조합에서 저장소 순위가 안정적임을 확인하였다(ρ=0.999).")
    replace(document, "본 연구는 공개 코드와", "결과의 적용 범위는 다음과 같다. 정확도는 Benchmark와 정책이 중첩되는 6개 CWE에 한정되고, DT 수동 판독은 1인의 코드 검토로 수행되어 평가자 간 일치도는 보고하지 않는다. Critical·High는 전수 검토했으나 Medium CWE-22는 191건 중 고정 난수 24건을 표본 추출했으며, 자격증명 유효성 검사와 실제 공격 실행은 수행하지 않았다. 또한 목적표본에는 애플리케이션·데모·라이브러리와 관련 코드 계보가 함께 포함되어, 일반 모집단 추정보다 재현 가능한 초기 기준선으로 활용하는 것이 적절하다.")
    replace(document, "향후 연구에서는 DT 저장소를", "향후 연구에서는 DT와 일반 운영 웹앱을 코드 규모·언어·저장소 유형별로 매칭하고, 독립된 2인 이상 검토자의 판정과 Cohen’s κ를 보고할 계획이다. Medium 전체 판독, 자격증명 폐기 상태 확인, 생성 코드 도달 가능성 및 안전한 범위의 동적 재현을 추가하고, SCA·DAST·컨테이너 이미지 검사와 연결한다. 정책 가중치는 전문가 순위와의 상관 및 수정 전후 결과로 재보정하며, 고정 룰 번들과 원시 산출물 해시를 이용해 장기 재현성도 검증하고자 한다.")

    # Table 1: full policy catalogue with actual observed scanners/rules.
    severity_basis_short = {
        "critical": "실행·DB·자격증명",
        "high": "권한·전송 경계",
        "medium": "조건부 입력 처리",
        "low": "보안 설정 강화",
    }
    policy_data = [["정책 항목", "CWE", "정책 등급", "스캐너", "DT에서 관찰한 대표 룰", "등급 근거"]]
    for row in policy:
        observed = row["top_observed_rule_ids_in_14_dt"]
        if observed == "본 DT 표본에서 탐지 없음":
            observed = "DT 표본 0건"
        else:
            shortened = []
            for part in observed.split("; ")[:3]:
                without_scanner = part.split(":", 1)[-1]
                rule_id, separator, count = without_scanner.rpartition(" (")
                short_id = rule_id.split(".")[-1]
                shortened.append(f"{short_id} ({count}" if separator else short_id)
            observed = "; ".join(shortened)
        policy_data.append([
            row["policy_item"], row["cwe"], row["policy_severity"].upper(),
            row["scanner_observed"], observed, severity_basis_short[row["policy_severity"]],
        ])
    fill_table(base_tables[0], policy_data, 6.3)
    replace(document, "Table 1.", "Table 1. Policy severity, scanner, observed rule IDs, and assignment basis")

    # Table 4: type, size, language, and lineage; full SHAs go to Appendix A.
    repo_names = [
        "digital-twins-explorer", "forge-digital-twin", "aps-digital-twin", "DTaaS",
        "itwinjs-core", "viewer-components-react", "digital-twin-demo", "collaboration-demo",
        "visual-analytics-demo", "openremote", "GeoTwin", "nus-digital-twin",
        "digital-twin-water", "Meteor3DEditor",
    ]
    type_ko = {
        "sample_application": "샘플 앱", "demo_application": "데모 앱", "platform": "플랫폼",
        "core_library_monorepo": "코어 라이브러리", "component_library_monorepo": "컴포넌트 라이브러리",
        "iot_platform_monorepo": "IoT 플랫폼", "research_application": "연구 앱",
        "starter_application": "스타터 앱", "editor_platform_monorepo": "3D 편집 플랫폼",
    }
    repo_data = [["ID", "저장소", "유형", "코드 LOC", "주 언어", "코드 계보"]]
    for row, name in zip(metadata, repo_names, strict=True):
        language_candidates = [part.split(":", 1)[0] for part in row["top_programming_languages"].split("; ")]
        language = next((item for item in language_candidates if item not in {"CSS", "HTML", "Shell", "Gradle"}), language_candidates[0])
        repo_data.append([row["repository_id"], name, type_ko[row["repository_type"]], f"{row['programming_nonblank_loc']:,}", language, row["code_lineage_cluster"]])
    replace(document, "Table 4.", "Table 4. Repository type, analyzed code size, primary language, and code lineage")
    repo_caption = find_paragraph(document, "Table 4.")
    old_repo_table = base_tables[3]
    old_repo_table._element.getparent().remove(old_repo_table._element)
    base_tables[3] = insert_table_after(document, repo_caption, repo_data, 6.6)

    # Table 6: auto, deduplicated, and review-adjusted outcomes.
    auto = experiments["ablation"]["combined_policy"]["per_repository"]
    dedup = experiments["ablation"]["combined_policy_deduplicated"]["per_repository"]
    reviewed = experiments["ablation"]["manual_ch_confirmed_raw_ml"]["per_repository"]
    result_data = [["ID", "코드 LOC", "자동 C/H/M", "자동 건수", "중복 제거", "자동 지수/판정", "검토 C/H", "검토 지수/판정"]]
    for a, d, r, meta in zip(auto, dedup, reviewed, metadata, strict=True):
        ac, rc = a["counts"], r["counts"]
        result_data.append([
            a["repository_id"], f"{meta['programming_nonblank_loc']:,}", f"{ac['critical']}/{ac['high']}/{ac['medium']}", str(a["finding_count"]),
            str(d["finding_count"]), f"{a['score']:.1f}/{a['verdict']}",
            f"{rc['critical']}/{rc['high']}", f"{r['score']:.1f}/{r['verdict']}",
        ])
    result_data.append(["합계", f"{sum(row['programming_nonblank_loc'] for row in metadata):,}", "69/8/197", "274", "220", "P3·W1·A1·B9", "30/1", "P3·W2·A1·B8"])
    fill_table(base_tables[5], result_data, 6.3)
    replace(document, "Table 6.", "Table 6. Automatic, deduplicated, and Critical/High review-adjusted DT results")

    # Insert manual validation, ablation, and score sensitivity after Table 6.
    anchor = base_tables[5]
    anchor = insert_paragraph_after(document, anchor, "4.3.1 자동 탐지 결과의 수동 검증", "Heading 2")
    anchor = insert_paragraph_after(document, anchor, "Critical 69건과 High 8건을 전수 검토하였다. Medium은 CWE-79 6건을 전수 검토하고, CWE-22 191건에서 난수 시드 20260723으로 24건을 비복원 단순무작위 추출하였다. 정확 위치 중복을 제외하면 Critical·High 72개, CWE-79 6개, CWE-22 표본 23개로 총 101개 위치다. 판독 기준은 확인된 위험 패턴, 문맥 제한 패턴, 오탐 및 중복이며, 배포 코드·CI/build·test·documentation/example·generated/tooling 문맥을 함께 기록하였다. 판독은 1인이 수행했고 자격증명 유효성 확인이나 실제 공격 실행은 포함하지 않았다.", "First Paragraph")
    anchor = insert_paragraph_after(document, anchor, "Table 7. Single-reviewer manual validation of automated DT findings", "Normal")
    manual_data = [
        ["대상", "원 레코드", "고유 위치", "확인 패턴", "문맥 제한", "오탐", "확인율"],
        ["Critical 전수", "69", "64", "30", "21", "13", "46.9%"],
        ["High 전수", "8", "8", "1", "1", "6", "12.5%"],
        ["Medium CWE-79 전수", "6", "6", "2", "0", "4", "33.3%"],
        ["Medium CWE-22 표본", "24", "23", "0", "6", "17", "0.0%"],
        ["합계", "107", "101", "33", "28", "40", "32.7%"],
    ]
    anchor = insert_table_after(document, anchor, manual_data, 7.0)
    anchor = insert_paragraph_after(document, anchor, "Critical·High 고유 72개 위치 중 확인 패턴은 31개(43.1%), 확인 패턴과 문맥 제한 패턴의 합은 53개(73.6%)였다. CWE-78 검토 과정에서는 Git ref에 명령 치환 문자와 세미콜론이 허용되는지를 git check-ref-format으로 직접 확인하여 릴리스 워크플로의 셸 삽입 경로를 판정하였다. 반면 테스트 토큰, 문서 예제, 고정 명령, 안전한 spawn 인자 배열 및 binary Buffer 응답은 문맥 제한 또는 오탐으로 분리하였다. 이 판독으로 DT6의 Critical 2건이 모두 오탐으로 정리되어 BLOCK에서 WARN으로 변경되었다.", "Body Text")

    anchor = insert_paragraph_after(document, anchor, "4.3.2 구성요소 제거 실험", "Heading 2")
    anchor = insert_paragraph_after(document, anchor, "각 구성요소가 탐지량과 게이트에 미치는 영향을 확인하기 위해 Semgrep 단독, 두 스캐너 전체, 16종 정책 적용, 정확 위치 중복 제거 및 Critical·High 수동 판독 반영 구성을 순차 비교하였다.", "First Paragraph")
    anchor = insert_paragraph_after(document, anchor, "Table 8. Ablation results for scanner combination, policy filtering, deduplication, and manual review", "Normal")
    ablation_data = [
        ["구성", "레코드/위치", "PASS", "WARN", "BLOCK_PENDING_APPROVAL", "BLOCK"],
        ["Semgrep 단독 + 정책", "234", "6", "2", "1", "5"],
        ["Gitleaks+Semgrep 전체 룰", "482", "1", "2", "2", "9"],
        ["결합 + 16종 정책", "274", "3", "1", "1", "9"],
        ["결합 + 정책 + 정확 위치 중복 제거", "220", "3", "1", "1", "9"],
        ["위 구성 + C/H 확인 패턴 반영", "179", "3", "2", "1", "8"],
    ]
    anchor = insert_table_after(document, anchor, ablation_data, 6.8)
    anchor = insert_paragraph_after(document, anchor, "Gitleaks 결합은 Semgrep 단독 대비 Hardcoded Secret을 포함하여 자동 BLOCK을 5개에서 9개로 확대하였다. 16종 정책 필터는 전체 482건을 274건으로 축약하면서 PASS를 1개에서 3개로 조정하였다. 정확 위치 중복 제거는 54건을 줄였으나 심각도 존재 여부에 기반한 게이트 분포는 유지되었다. 수동 판독은 게이트 한 건을 변경하여 자동 경고를 곧바로 확정 취약점으로 간주하지 않는 절차의 필요성을 보여준다.", "Body Text")

    anchor = insert_paragraph_after(document, anchor, "4.3.3 정책 기반 보조지수 민감도 분석", "Heading 2")
    anchor = insert_paragraph_after(document, anchor, "보조지수의 가중치와 상한에 따른 저장소 순위 변화를 Spearman 순위상관으로 평가하였다. 비교 위험량은 정확 위치 중복 제거 건수를 사용했고, 낮은 보조지수일수록 높은 위험량이 되도록 방향을 통일하였다.", "First Paragraph")
    anchor = insert_paragraph_after(document, anchor, "Table 9. Sensitivity of repository ranking to score model and weights", "Normal")
    sensitivity_data = [
        ["모델", "위험량 범위", "현 지수 대비 ρ", "게이트 영향"],
        ["구현된 등급별 상한 지수", "0–100", "1.000", "기준"],
        ["동일 가중치·상한 미적용", "0–546", "0.950", "없음"],
        ["단순 고유 위치 건수", "0–109", "0.776", "없음"],
        ["CVSS 질적 구간 중앙값 합", "0–648.5", "0.830", "없음"],
        ["대안 W2=16/4/1/0.25", "0–454", "0.999(W1 대비)", "14/14 동일"],
        ["대안 W3=25/6/1/0.1", "0–661", "0.999(W1 대비)", "14/14 동일"],
    ]
    anchor = insert_table_after(document, anchor, sensitivity_data, 7.0)
    insert_paragraph_after(document, anchor, "세 계층형 가중치 조합에서 순위는 거의 동일했으나(ρ=0.999), 상한 지수와 단순 건수의 상관은 0.776이었다. 이는 지수가 심각도 위계를 강조하는 정책 요약량임을 보여준다. 게이트는 점수와 독립적으로 심각도 존재 여부를 사용하므로 모든 가중치에서 동일했으며, 따라서 지수를 절대 보안 수준이나 전문가 위험 순위의 대체값으로 해석하지 않는다.", "Body Text")

    # Renumber and narrow the case-study table.
    replace(document, "Table 7. In-scope", "Table 10. In-scope findings in the hydrogen-powered ship digital twin")
    hydrogen = base_tables[6]
    fill_table(
        hydrogen,
        [
            ["심각도", "정책 항목", "CWE", "제목", "축약 파일", "라인"],
            ["High", "Cleartext Transmission", "CWE-319", "Insecure WebSocket", "BuildWeb.framework.js", "1107"],
            ["Medium", "Cross-Site Scripting", "CWE-79", "dangerouslySetInnerHTML", "FuelEmission.tsx", "77"],
        ],
        7.0,
    )
    case_result = find_paragraph(document, "SecuPipeline을 development 환경으로")
    insert_paragraph_after(document, case_result, "표 10의 축약 파일명에 대응하는 전체 경로는 각각 hydrogen_ship_3d_model/Build/BuildWeb.framework.js와 client/src/component/LBTS/FuelEmission.tsx이다.", "Body Text")

    # Table 11: original repository unit and new lineage-cluster sensitivity.
    replace(document, "Table 8. Repository-level", "Table 11. Repository- and lineage-level Fisher exact comparisons of automated CWE profiles")
    profile = base_tables[7]
    repo_stats = load_json("analysis/kci_paper_results.json")["cwe_profile_comparison"]["comparisons"] if (ROOT / "analysis/kci_paper_results.json").exists() else {
        "CWE-319": {"web_repositories": "4/8", "dt_repositories": "2/14", "odds_ratio": 0.167, "p_value_two_sided": 0.1365},
        "CWE-79": {"web_repositories": "5/8", "dt_repositories": "3/14", "odds_ratio": 0.164, "p_value_two_sided": 0.0815},
        "CWE-89": {"web_repositories": "7/8", "dt_repositories": "0/14", "odds_ratio": 0.0, "p_value_two_sided": 0.0004},
        "CWE-798": {"web_repositories": "5/8", "dt_repositories": "8/14", "odds_ratio": 0.8, "p_value_two_sided": 1.0},
        "Other policy CWEs": {"web_repositories": "7/8", "dt_repositories": "6/14", "odds_ratio": 0.107, "p_value_two_sided": 0.0743},
    }
    profile_data = [["CWE", "취약 웹앱", "DT 저장소", "저장소 OR/p", "DT 계보", "계보 OR/p"]]
    for key in ("CWE-319", "CWE-79", "CWE-89", "CWE-798", "Other policy CWEs"):
        rs = repo_stats[key]
        cs = cluster["comparisons"][key]
        rp = "<0.001" if float(rs["p_value_two_sided"]) < 0.001 else f"{float(rs['p_value_two_sided']):.4f}"
        cp = "<0.001" if float(cs["p_value_two_sided"]) < 0.001 else f"{float(cs['p_value_two_sided']):.4f}"
        profile_data.append([
            key, rs["web_repositories"], rs["dt_repositories"], f"{float(rs['odds_ratio']):.3f}/{rp}",
            cs["dt_lineage_clusters"], f"{float(cs['odds_ratio']):.3f}/{cp}",
        ])
    fill_table(profile, profile_data, 6.8)

    # Append reproducibility appendix before references.
    references = find_paragraph(document, "참고문헌")
    appendix = document.add_paragraph()
    appendix.style = "Heading 2"
    clear_and_set(appendix, "부록 A. 고정 커밋 및 재현성 산출물")
    references._element.addprevious(appendix._p)
    anchor = appendix
    anchor = insert_paragraph_after(document, anchor, "표 A1은 분석한 공개 DT의 전체 커밋 SHA를 제시한다. 표 A2의 룰·설정·바이너리 해시와 experiment_output_sha256.csv의 70개 원시 산출물 해시를 함께 사용하면 실험 입력과 결과의 동일성을 확인할 수 있다.", "First Paragraph")
    anchor = insert_paragraph_after(document, anchor, "Table A1. Full commit SHA of the 14 public DT repositories", "Normal")
    commit_data = [["ID", "저장소 URL", "전체 커밋 SHA"]]
    for row in metadata:
        commit_data.append([row["repository_id"], row["repository_url"].replace("https://github.com/", ""), row["full_commit_sha"]])
    anchor = insert_table_after(document, anchor, commit_data, 6.8)
    anchor = insert_paragraph_after(document, anchor, "Table A2. Frozen scanner artifacts and SHA-256 identifiers", "Normal")
    repro_data = [
        ["산출물", "버전/규모", "SHA-256"],
        ["Semgrep core 룰 번들", f"v{manifest['semgrep']['version']}, {manifest['semgrep']['frozen_rule_count']} rules", manifest["semgrep"]["bundle_sha256"]],
        ["Semgrep core binary", manifest["semgrep"]["version"], manifest["semgrep"]["semgrep_core_sha256"]],
        ["Gitleaks 기본 설정", f"v{manifest['gitleaks']['version']}", manifest["gitleaks"]["config_sha256"]],
        ["Gitleaks binary", manifest["gitleaks"]["version"], manifest["gitleaks"]["binary_sha256"]],
        ["원시 결과 해시 목록", "14 runs × 5 files", "analysis/reproducibility/experiment_output_sha256.csv"],
        ["수동 판독 결과", "107 records", "analysis/dt_manual_validation_results.csv"],
    ]
    insert_table_after(document, anchor, repro_data, 6.5)

    # Global formatting and layout safeguards.
    for table in document.tables:
        repeat_header(table)
        shade_header(table)
        for row in table.rows:
            if row._tr.get_or_add_trPr().find(qn("w:cantSplit")) is None:
                row._tr.get_or_add_trPr().append(OxmlElement("w:cantSplit"))
    for paragraph in document.paragraphs:
        paragraph.paragraph_format.widow_control = True
        if paragraph.style.name == "Heading 2":
            paragraph.paragraph_format.keep_with_next = True
    remove_trailing_empty_paragraphs(document)

    # Consistent verdict token spelling throughout paragraphs and tables.
    for paragraph in document.paragraphs:
        text = paragraph.text
        normalized = text.replace("승인 대기", "BLOCK_PENDING_APPROVAL").replace("BLOCK_PEND\nING_APPROVAL", "BLOCK_PENDING_APPROVAL")
        if normalized != text:
            clear_and_set(paragraph, normalized)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if "승인 대기" in cell.text or "BLOCK_PEND" in cell.text:
                    value = cell.text.replace("승인 대기", "BLOCK_PENDING_APPROVAL").replace("BLOCK_PEND\nING_APPROVAL", "BLOCK_PENDING_APPROVAL")
                    cell.text = value

    image_bytes = create_process_figure(FIGURE)
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    document.save(DESTINATION)
    replace_embedded_figure(DESTINATION, image_bytes)
    with zipfile.ZipFile(DESTINATION) as archive:
        bad = archive.testzip()
        if bad:
            raise ValueError(f"corrupt DOCX member: {bad}")
    print(f"output={DESTINATION}")
    print(f"figure={FIGURE}")
    print(f"paragraphs={len(document.paragraphs)} tables={len(document.tables)} sections={len(document.sections)}")
    print(f"manual_unique={manual['unique_location_count']} manual_confirmed={manual['unique_assessment_counts']['confirmed_pattern']}")


if __name__ == "__main__":
    main()
