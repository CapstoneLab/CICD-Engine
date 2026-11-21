#!/usr/bin/env python3
"""Populate the web-DT paper DOCX with verified local experiment results.

The source DOCX is kept unchanged. The script edits only word/document.xml in
a copied package so equations, relationships, references, and package metadata
outside the main document are preserved.
"""

from __future__ import annotations

import copy
import io
import sys
import tempfile
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
W = f"{{{W_NS}}}"


def register_namespaces(xml_bytes: bytes) -> None:
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(xml_bytes), events=("start-ns",)):
        try:
            ET.register_namespace(prefix or "", uri)
        except ValueError:
            pass


def text_of(element: ET.Element) -> str:
    return "".join(
        node.text or "" for node in element.iter() if node.tag.endswith("}t")
    )


def set_paragraph_text(paragraph: ET.Element, value: str) -> None:
    properties = paragraph.find(W + "pPr")
    for child in list(paragraph):
        if child is not properties:
            paragraph.remove(child)
    run = ET.SubElement(paragraph, W + "r")
    text = ET.SubElement(run, W + "t")
    if value.startswith(" ") or value.endswith(" ") or "  " in value:
        text.set(f"{{{XML_NS}}}space", "preserve")
    text.text = value


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


def main(source: Path, destination: Path) -> None:
    if source.resolve() == destination.resolve():
        raise ValueError("source and destination must differ")
    with zipfile.ZipFile(source) as archive:
        document_xml = archive.read("word/document.xml")
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]

    register_namespaces(document_xml)
    root = ET.fromstring(document_xml)
    paragraphs = list(root.iter(W + "p"))
    tables = list(root.iter(W + "tbl"))
    if len(tables) != 8:
        raise ValueError(f"expected 8 tables, found {len(tables)}")

    def find_paragraph(prefix: str) -> ET.Element:
        matches = [p for p in paragraphs if text_of(p).startswith(prefix)]
        if len(matches) != 1:
            raise ValueError(f"paragraph prefix {prefix!r}: found {len(matches)}")
        return matches[0]

    def replace(prefix: str, value: str) -> ET.Element:
        paragraph = find_paragraph(prefix)
        set_paragraph_text(paragraph, value)
        return paragraph

    replace(
        "웹 기반 디지털트윈(DT)은",
        "웹 기반 디지털트윈(DT)은 3D 시각화, 실시간 센서 동기화 및 원격 제어를 웹 브라우저로 제공하지만, 기존 연구는 CPS·OT 계층에 집중하여 웹 애플리케이션 소스 코드 수준의 정량적 보안성 측정을 충분히 다루지 못했다. 본 연구는 Gitleaks와 Semgrep을 결합한 2단계 정적 분석, 16종 CWE 정책 카탈로그, 등급별 감점 상한을 적용한 보조 점수 및 계층형 보안 게이트로 구성된 측정 기법을 제안한다. 취약 웹앱 8개, 공개 DT 웹앱 14개 및 수소추진선박 DT 1개 등 23개 고정 커밋을 분석하였다. OWASP Benchmark v1.2에서 정책과 중첩되는 6개 CWE에 대한 탐지 성능은 정밀도 0.533, 재현율 0.772, F1-Score 0.630이었다. 공개 DT 14개에서는 원시 탐지 482건 중 274건이 정책 범위에 포함되었고, PASS 3개, WARN 1개, BLOCK 9개 및 승인 대기 1개로 판정되었다. 저장소 단위 Fisher 정확 검정에서 CWE-319와 CWE-79의 DT 보유율은 취약 웹앱 비교군보다 높지 않았으며 각각 p=0.1365와 p=0.0815로 유의하지 않아, 두 CWE가 DT에서 더 빈번하다는 가설은 지지되지 않았다.",
    )
    replace(
        "DT 특이 취약점 프로파일 도출:",
        "DT 취약점 프로파일의 실증 비교: 공개 DT 웹앱 14개와 취약 웹앱 8개를 저장소 단위로 비교하고 Fisher 정확 검정과 Odds Ratio를 적용하여 CWE-319, CWE-79, CWE-89 및 CWE-798의 분포 차이와 가설의 지지 여부를 검증한다.",
    )
    replace(
        "16개 항목은 OWASP Top 10:2021의",
        "16개 항목은 Critical·High·Medium·Low 각 4종으로 구성되며, CWE를 단일 기준으로 사용해 스캐너의 원시 심각도를 정책 등급으로 재분류한다. 정책 카탈로그 밖 탐지는 범위 외로 보존하여 미검사를 안전으로 해석하지 않도록 한다.",
    )

    formula_intro = replace(
        "탐지된 범위 내 취약점의 심각도 분포를 기반으로",
        "범위 내 탐지 레코드의 등급별 분포를 이용해 100점 만점의 보조 점수를 산출한다. 점수는 코드 건강도를 요약하는 지표이며 배포 차단 여부는 다음 절의 계층형 게이트가 독립적으로 결정한다.",
    )
    formula = find_paragraph("S=100")
    set_paragraph_text(
        formula,
        "D_H=min(5C_H,19), D_M=min(C_M,4), D_L=min(0.2C_L,0.9)",
    )
    formula_index = paragraphs.index(formula)
    set_paragraph_text(
        paragraphs[formula_index + 1],
        "C_C=0이면 S=100-D_H-D_M-D_L이고, C_C≥1이면 S=max(0,min(40,100-20C_C-D_H-D_M-D_L))이다.",
    )
    replace(
        "여기서 Ccrit",
        "여기서 C_C, C_H, C_M, C_L은 각각 Critical, High, Medium, Low 등급의 범위 내 탐지 건수이며 D_H, D_M, D_L은 등급별 상한이 적용된 감점 합계이다.",
    )
    replace(
        "가중치의 설계 근거는 다음과 같다.",
        "등급별 건당 감점은 Critical 20, High 5, Medium 1, Low 0.2로 설정하였다. 하위 등급 다수가 상위 등급 1건보다 더 큰 위험으로 표시되는 역전을 막기 위해 High 19점, Medium 4점, Low 0.9점의 합산 상한을 둔다. Critical이 존재하면 게이트가 즉시 BLOCK되고 점수도 0~40 위험 구간으로 제한한다.",
    )
    replace(
        "표 2는 대안 가중치와의 비교를 나타낸다.",
        "이 설계에서 Low 전체 감점은 Medium 1건의 감점보다 작고, Medium 전체 감점은 High 1건보다 작으며, High 전체 감점은 Critical 1건보다 작다. 따라서 점수는 등급 위계를 유지하면서도 게이트 판정과 분리된 보조 지표로 작동한다.",
    )
    replace(
        "이 가중치 체계는 OWASP Risk Rating Methodology",
        "점수는 선택한 16개 정책 범위의 상대적 건강도를 나타내며 확정 취약점 수나 CVSS 점수의 합을 의미하지 않는다. 판정과 점수를 분리함으로써 높은 점수라도 High가 존재하면 승인 전 배포를 중단할 수 있다.",
    )
    replace(
        "산출된 보안 점수와 취약점 건수를 배포 환경별 임계값과 비교하여",
        "판정은 점수가 아니라 등급 위계에 따라 수행된다. 표 3은 환경별 Critical·High·Medium 처리 규칙을 나타낸다.",
    )
    replace(
        "판정 알고리즘은 다음과 같이 동작한다.",
        "게이트는 우선순위 순으로 동작한다. Critical이 1건 이상이면 예외 없는 BLOCK, 미승인 High가 1건 이상이면 BLOCK_PENDING_APPROVAL, Medium만 존재하면 WARN, Low만 존재하거나 탐지가 없으면 PASS이다. 승인된 High도 점수에는 남지만 게이트에서는 수용된 위험으로 처리한다.",
    )
    replace(
        "임계값의 설계 근거는 다음과 같다.",
        "환경은 위계를 완화하지 않고 강화만 한다. development와 feature에서는 Medium을 WARN으로 통과시키지만, production과 staging에서는 Medium도 승인 대기로 승격한다. BLOCK과 BLOCK_PENDING_APPROVAL은 모두 후속 빌드·배포를 중단하며, 후자는 책임자의 명시적 승인 경로가 있다는 점에서 구분된다.",
    )
    replace(
        "이 모델의 핵심은 동일한 탐지 결과라도",
        "예를 들어 High 1건은 보조 점수가 95점일 수 있지만 판정은 BLOCK_PENDING_APPROVAL이므로 승인 없이는 배포할 수 없다. 점수와 판정의 역할을 분리하여 높은 점수가 위험한 배포를 허용하는 모순을 방지한다.",
    )

    replace(
        "검증용 웹앱(8개):",
        "취약 웹앱 비교군(8개): OWASP Juice-Shop, OWASP NodeGoat, DVNA, WebGoat, Vulnerable-Flask-App, django.nV, OWASP Benchmark, dvpwa를 사용하였다. 이 중 공식 케이스별 정답표가 실행 스냅샷에 포함된 OWASP Benchmark v1.2를 정량 정확도 평가에 사용하고, 나머지 7개는 탐지·판정 및 CWE 프로파일 비교 대상으로 사용하였다.",
    )
    replace(
        "4.2 검증용 웹앱을 통한 정확도 검증",
        "4.2 OWASP Benchmark v1.2를 통한 탐지 정확도 검증",
    )
    replace(
        "8개 검증용 웹앱을 대상으로 제안 기법의 탐지 정확도를 평가한다.",
        "정확도 평가는 OWASP Benchmark v1.2 정답표와 16종 정책이 공통으로 포함하는 CWE-22, CWE-78, CWE-79, CWE-89, CWE-327 및 CWE-614를 대상으로 수행하였다. 파일의 테스트 케이스 ID와 CWE가 일치하는 범위 내 탐지를 TP·FP·FN으로 집계하였다. 마이크로 합계는 TP 728, FP 639, FN 215이며 정밀도 0.533, 재현율 0.772, F1-Score 0.630이다. 이는 8개 앱 전체의 공식 정답 기반 점수가 아니라 Benchmark 중첩 6개 CWE에 한정된 결과이다.",
    )
    result_intro = replace(
        "14개 DT 웹앱에 제안 기법을 적용하여",
        "14개 공개 DT 웹앱의 기존 분석 커밋을 고정하고 development 환경, 16개 정책 및 scan-only 워크플로로 재검사하였다. 모든 실행에서 Gitleaks와 Semgrep이 완료되고 필수 JSON 산출물이 생성되었다.",
    )
    result_index = paragraphs.index(result_intro)
    set_paragraph_text(
        paragraphs[result_index + 1],
        "원시 탐지 482건 중 274건이 정책 범위에 포함되고 208건이 범위 외로 분리되어 가중 축소율은 43.2%였다. 범위 내 분포는 Critical 69건, High 8건, Medium 197건, Low 0건이며 판정은 PASS 3개, WARN 1개, BLOCK 9개, BLOCK_PENDING_APPROVAL 1개였다.",
    )
    replace(
        "SecuPipeline을 development 환경으로 실행한 결과, 보안 점수 94/100, 판정 WARN",
        "SecuPipeline을 development 환경으로 실행한 결과, 보조 점수 94/100과 판정 BLOCK_PENDING_APPROVAL이 도출되었다. High 등급 CWE-319가 승인 전 빌드·배포를 중단시켰으며 범위 내 탐지 결과는 표 5와 같다.",
    )
    replace(
        "범위 외 탐지 결과로는 Kubernetes securityContext 누락",
        "범위 외 탐지는 5건으로 Subresource Integrity 누락(CWE-353), 정규표현식 DoS(CWE-1333), runAsNonRoot 미설정(CWE-250), Kubernetes 권한 설정(CWE-732), CSRF 미들웨어 누락(CWE-352)이었다.",
    )
    profile_intro = replace(
        "검증용 웹앱(일반 웹앱)과 DT 웹앱의 취약점 분포를 비교하여",
        "취약 웹앱 8개와 공개 DT 웹앱 14개의 정책 범위 내 CWE 분포를 비교하였다. 저장소 크기에 따른 탐지 건수 편향을 줄이기 위해 각 CWE가 저장소에 1건 이상 존재하는지를 분석 단위로 삼고, DT 대비 취약 웹앱의 Odds Ratio와 양측 Fisher 정확 검정 p-value를 산출하였다.",
    )
    profile_index = paragraphs.index(profile_intro)
    set_paragraph_text(
        paragraphs[profile_index + 1],
        "표의 분자는 해당 CWE가 한 건 이상 탐지된 저장소 수이며 괄호 안은 탐지 레코드 수이다. Odds Ratio는 DT의 탐지 보유 오즈를 취약 웹앱 비교군의 오즈로 나눈 값이다.",
    )
    replace(
        "가설: DT 웹앱은",
        "CWE-319는 취약 웹앱 4/8개와 DT 2/14개에서 관찰되어 OR=0.167, p=0.1365였고, CWE-79는 각각 5/8개와 3/14개로 OR=0.164, p=0.0815였다. 두 항목 모두 DT에서 더 높다는 가설과 반대 방향이며 통계적으로 유의하지 않았다. CWE-89는 취약 웹앱 7/8개, DT 0/14개로 DT에서 유의하게 낮았고(p<0.001), CWE-798은 두 집단 간 차이가 없었다(p=1.0000). 비교군이 의도적으로 취약한 앱으로 구성되므로 이 결과는 일반 웹앱 모집단의 차이로 일반화하지 않고 본 표본의 탐지 프로파일 차이로 해석한다.",
    )
    replace(
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 보안성을 정량적으로 측정하는 기법을 제안하였다.",
        "본 연구는 웹 기반 디지털트윈 소프트웨어의 정적 보안 특성을 16종 CWE 정책, 보조 점수 및 계층형 게이트로 정량화하는 기법을 제안하였다. OWASP Benchmark의 정책 중첩 6개 CWE에서 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 확인하였다. 공개 DT 14개에서는 원시 탐지 482건 중 274건이 정책 범위에 포함되었고 PASS 3개, WARN 1개, BLOCK 9개 및 승인 대기 1개로 판정되었다. CWE-319와 CWE-79가 DT에서 더 빈번하다는 가설은 본 표본에서 지지되지 않았다.",
    )
    replace(
        "본 연구의 한계는 다음과 같다.",
        "본 연구의 한계는 다음과 같다. 첫째, Semgrep과 Gitleaks의 규칙 및 파서 한계가 결과에 반영되며 14개 DT 재실행 중 8개에서 총 95개의 비치명적 파싱·타임아웃·내부 매칭 경고가 기록되었다. 둘째, 정확도 검증은 공식 정답표와 정책이 중첩되는 OWASP Benchmark의 6개 CWE에 한정되어 전체 16종 정책의 정확도를 대표하지 않는다. 셋째, CWE 프로파일 비교군은 의도적으로 취약한 웹앱이므로 일반 운영 웹앱과 DT의 모집단 차이로 일반화할 수 없다. 넷째, 정적 분석은 실행 경로, 도달 가능성, 생성 코드의 실제 사용 여부 및 체인 공격을 직접 검증하지 못한다.",
    )
    replace(
        "향후 연구 방향은 다음과 같다.",
        "향후 연구에서는 일반 운영 웹앱으로 통제 비교군을 확장하고 16종 정책 전반에 대한 독립 라벨링과 전문가 검토를 수행한다. 또한 Semgrep 규칙 revision과 도구 버전을 고정하고 파싱 경고를 정량 보고하며, SCA·DAST·컨테이너 이미지 검사와 런타임 네트워크 추적을 결합한다. DT 저장소 수와 도메인을 확대하여 Fisher 검정의 검정력을 높이고, 승인 이후 재검사와 수정 전후 효과도 검증한다.",
    )

    # Policy table: align Improper JWT with the implementation catalog.
    set_cell_text(cells_of(rows_of(tables[0])[9])[2], "CWE-347")

    # Replace the old alternative-weight table with the implemented cap model.
    weight_table = tables[1]
    weight_table.append(copy.deepcopy(rows_of(weight_table)[-1]))
    set_table(
        weight_table,
        [
            ["등급", "건당 감점", "감점 상한", "게이트 판정", "처리"],
            ["Critical", "20", "없음; 점수 0~40", "BLOCK", "승인 불가"],
            ["High", "5", "19", "BLOCK_PENDING_APPROVAL", "승인 필요"],
            ["Medium", "1", "4", "WARN", "prod/staging 승인 필요"],
            ["Low", "0.2", "0.9", "PASS", "점수에만 반영"],
        ],
    )
    set_table(
        tables[2],
        [
            ["환경", "Critical", "High", "Medium"],
            ["production", "BLOCK", "승인 대기", "승인 대기"],
            ["staging", "BLOCK", "승인 대기", "승인 대기"],
            ["development", "BLOCK", "승인 대기", "WARN"],
            ["feature", "BLOCK", "승인 대기", "WARN"],
        ],
    )

    accuracy_table = tables[4]
    for row in rows_of(accuracy_table)[8:]:
        accuracy_table.remove(row)
    set_table(
        accuracy_table,
        [
            ["평가 CWE", "TP", "FP", "FN", "Precision", "Recall", "F1-Score"],
            ["CWE-22", "120", "106", "13", "0.531", "0.902", "0.669"],
            ["CWE-78", "117", "109", "9", "0.518", "0.929", "0.665"],
            ["CWE-79", "202", "108", "44", "0.652", "0.821", "0.727"],
            ["CWE-89", "253", "170", "19", "0.598", "0.930", "0.728"],
            ["CWE-327", "0", "0", "130", "0.000", "0.000", "0.000"],
            ["CWE-614", "36", "0", "0", "1.000", "1.000", "1.000"],
            ["마이크로 합계", "728", "639", "215", "0.533", "0.772", "0.630"],
        ],
    )

    result_rows = [
        ["ID", "보안 점수", "Critical", "High", "Medium", "Low", "범위 내 합계", "판정(dev)"],
        ["DT1", "100.0", "0", "0", "0", "0", "0", "PASS"],
        ["DT2", "100.0", "0", "0", "0", "0", "0", "PASS"],
        ["DT3", "96.0", "0", "0", "8", "0", "8", "WARN"],
        ["DT4", "0.0", "14", "0", "9", "0", "23", "BLOCK"],
        ["DT5", "0.0", "24", "0", "120", "0", "144", "BLOCK"],
        ["DT6", "40.0", "2", "0", "31", "0", "33", "BLOCK"],
        ["DT7", "40.0", "1", "0", "0", "0", "1", "BLOCK"],
        ["DT8", "40.0", "1", "0", "0", "0", "1", "BLOCK"],
        ["DT9", "40.0", "1", "0", "0", "0", "1", "BLOCK"],
        ["DT10", "0.0", "16", "1", "7", "0", "24", "BLOCK"],
        ["DT11", "0.0", "6", "0", "2", "0", "8", "BLOCK"],
        ["DT12", "100.0", "0", "0", "0", "0", "0", "PASS"],
        ["DT13", "81.0", "0", "7", "0", "0", "7", "승인 대기"],
        ["DT14", "16.0", "4", "0", "20", "0", "24", "BLOCK"],
    ]
    set_table(tables[5], result_rows)

    set_table(
        tables[7],
        [
            ["CWE", "취약 웹앱 8개: 보유율(건수)", "DT 14개: 보유율(건수)", "OR(DT/웹) / p-value"],
            ["CWE-319", "4/8 (12건)", "2/14 (8건)", "0.167 / 0.1365"],
            ["CWE-79", "5/8 (470건)", "3/14 (6건)", "0.164 / 0.0815"],
            ["CWE-89", "7/8 (599건)", "0/14 (0건)", "0.000 / <0.001"],
            ["CWE-798", "5/8 (102건)", "8/14 (45건)", "0.800 / 1.0000"],
            ["기타 정책 CWE", "7/8 (635건)", "6/14 (215건)", "0.107 / 0.0743"],
        ],
    )

    updated_xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=destination.name + ".", suffix=".tmp", delete=False
    ) as handle:
        temp_path = Path(handle.name)
    try:
        with zipfile.ZipFile(temp_path, "w") as output:
            for info, data in entries:
                output.writestr(
                    info,
                    updated_xml if info.filename == "word/document.xml" else data,
                )
        temp_path.replace(destination)
    finally:
        if temp_path.exists():
            temp_path.unlink()


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: update_web_dt_docx.py SOURCE.docx DESTINATION.docx")
    main(Path(sys.argv[1]), Path(sys.argv[2]))
