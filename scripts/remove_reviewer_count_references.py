#!/usr/bin/env python3
"""Remove reviewer-count and inter-rater-statistic references from the DT paper.

The contextual adjudication procedure and all experimental results remain
unchanged. Only statements about the number of reviewers, single-reviewer
wording, Cohen's kappa, and planned multi-reviewer validation are removed.
"""

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
DEFAULT_SOURCE = ROOT / "웹 기반 디지털트윈_KCI_용어체계_통합본.docx"
DEFAULT_DESTINATION = ROOT / "웹 기반 디지털트윈_KCI_최종제출본.docx"
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


def table_signature(table) -> tuple[tuple[str, ...], ...]:
    return tuple(
        tuple(cell.text for cell in row.cells)
        for row in table.rows
    )


def all_text(document: Document) -> str:
    parts = [paragraph.text for paragraph in document.paragraphs]
    parts.extend(
        cell.text
        for table in document.tables
        for row in table.rows
        for cell in row.cells
    )
    return "\n".join(parts)


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
        "단일 판독자",
        "1명의 판독자",
        "1인이 수행",
        "판독자",
        "single-reviewer",
        "Single-reviewer",
        "single reviewer",
        "Cohen",
        "평가자 간",
        "2인 이상 검토자",
        "복수 검토자",
    ):
        if forbidden in text:
            raise AssertionError(f"reviewer-related text remains: {forbidden}")

    for required in (
        "문맥 검토",
        "문맥 판독",
        "Table 8. Automatic, deduplicated, and contextually adjusted DT results",
        "Table 9. Contextual validation of automated DT findings",
        "정밀도 0.533",
        "재현율 0.772",
        "F1-Score 0.630",
        "TP 728, FP 639, FN 215",
        "Critical 69건과 High 8건을 전수 검토하였다.",
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

    replace(
        document,
        "웹 기반 DT는 3D 시각화",
        "웹 기반 DT는 3D 시각화, 실시간 센서 동기화 및 원격 제어 기능을 제공하지만, "
        "웹 애플리케이션 계층의 정적 분석 경고를 DT 구성요소와 배포 문맥에서 해석하는 "
        "실증 연구는 제한적이다. 본 연구는 범용 정적 분석기를 DT 전용 탐지기로 제안하는 "
        "대신, Gitleaks와 Semgrep의 경고를 16종 CWE 보안 정책 카탈로그에 따라 재분류하고, "
        "정확 위치 중복 제거, 문맥 검토, 정책 기반 보조지수 및 즉시·선택적 배포 차단을 "
        "구체화한 환경 민감형 배포 게이트로 연결하는 재현성을 고려한 절차를 제시한다. "
        "OWASP Benchmark v1.2와 공개 DT 14개 고정 커밋을 대상으로 기준 성능 평가, 수동 "
        "판독, 구성요소 제거 및 가중치 민감도 분석을 수행하였다. 정책 중첩 6개 CWE에서 "
        "현재 룰셋은 정밀도 0.533, 재현율 0.772 및 F1-Score 0.630을 보였고, CWE-327의 "
        "130개 실제 취약 사례는 탐지하지 못하였다. 공개 DT에서 자동 분류된 274건 가운데 "
        "Critical·High 77건과 Medium 30건을 검토한 결과, 중복을 제외한 Critical·High "
        "72개 위치 중 31개가 확인된 위험 패턴으로 분류되었다. 문맥 검토를 반영한 취약점 "
        "의사결정 결과, 즉시 배포 차단 상태는 BLOCK 8개와 BLOCK_PENDING_APPROVAL "
        "1개였으며, 선택적 배포 차단이 활성화되지 않은 Medium 탐지 저장소는 WARN 2개, "
        "활성화된 차단 조건이 없는 저장소는 PASS 3개로 산출되었다.",
    )
    replace(
        document,
        "Web-based digital twins provide",
        "Web-based digital twins provide 3D visualization, real-time sensor synchronization, "
        "and remote control, but empirical studies that interpret static-analysis alerts in DT "
        "component and deployment contexts remain limited. This study does not present "
        "general-purpose analyzers as DT-specific detectors. Instead, it connects Gitleaks and "
        "Semgrep alerts to a 16-CWE security policy catalogue, exact-location deduplication, "
        "contextual adjudication, an auxiliary policy index, and environment-sensitive deployment "
        "control that operationalizes immediate and selective deployment blocking. OWASP "
        "Benchmark v1.2 and 14 pinned public DT repositories were evaluated through baseline "
        "performance, manual adjudication, ablation, and weight-sensitivity analyses. On six "
        "policy-overlapping CWEs, the current ruleset achieved 0.533 precision, 0.772 recall, and "
        "an F1-score of 0.630, while all 130 true CWE-327 cases remained undetected. Of 77 "
        "automated Critical/High records in the DT repositories, 72 unique locations remained "
        "after deduplication and 31 were classified as confirmed risky patterns. After contextual "
        "adjudication, the vulnerability decision-making results yielded eight BLOCK and one "
        "BLOCK_PENDING_APPROVAL as immediate deployment-blocking states, two WARN for repositories "
        "where selective blocking for Medium findings was inactive, and three PASS with no active "
        "blocking condition.",
    )
    replace(
        document,
        "본 연구는 범용 정적 분석 도구가 생성한 경고를 웹 기반 DT 코드베이스의",
        "본 연구는 범용 정적 분석 도구가 생성한 경고를 웹 기반 DT 코드베이스의 "
        "구성요소와 배포 문맥에서 판독하고, 정확 위치 중복 제거, 정책 기반 보조지수와 "
        "즉시·선택적 배포 차단을 구체화한 환경별 DevSecOps 배포 제어로 연결하는 "
        "재현성을 고려한 실증 절차를 제시한다. 자동 경고는 확정 취약점이 아니므로 자동 "
        "취약점 의사결정 결과와 문맥 판독 반영 취약점 의사결정 결과를 구분한다. "
        "Benchmark의 정책 중첩 6개 CWE에서 현재 룰셋의 기준 성능과 미탐 영역을 확인하고, "
        "공개 DT 14개에 적용하여 경고 처리 단계가 배포 제어 실행 상태에 미치는 변화를 "
        "분석하였다.",
    )
    replace(
        document,
        "추적 가능한 경고–취약점 의사결정 연결 절차:",
        "추적 가능한 경고–취약점 의사결정 연결 절차: Gitleaks·Semgrep 경고를 16종 "
        "CWE 보안 정책 카탈로그에 매핑하고, 정확 위치 중복 제거와 문맥 판독을 거쳐 정책 "
        "기반 보조지수와 환경별 배포 제어로 연결하였다(제3.1절 및 제3.2절).",
    )
    replace(
        document,
        "다층 실증 평가:",
        "다층 실증 평가: OWASP Benchmark의 기준 성능, 공개 DT 14개의 문맥 검토, "
        "구성요소 제거 및 가중치 민감도 분석을 수행하였다. 취약 웹앱과의 CWE 비교는 "
        "모집단 차이 검정이 아닌 후속 연구용 탐색적 분석으로 한정하였다(제4.3절 및 "
        "제4.4절).",
    )
    replace(
        document,
        "RQ2:",
        "RQ2: 정확 위치 중복 제거와 문맥 판독은 탐지량과 배포 제어 실행 상태를 어떻게 "
        "변화시키는가?",
    )
    replace(
        document,
        "본 연구는 이러한 연구 공백을",
        "본 연구는 이러한 연구 공백을 다루기 위해 범용 정적 분석 경고를 DT 구성요소 "
        "문맥과 연결하고, 중복 제거·문맥 검토·정책 기반 보조지수·환경 민감형 배포 제어로 "
        "이어지는 절차를 정의한다. RQ1은 제4.3.1절의 Benchmark 기준 성능과 룰 진단으로, "
        "RQ2는 제4.3.2절 및 제4.4.1절의 공개 DT 판독과 구성요소 제거로, RQ3은 "
        "제4.4.2절 및 제4.4.3절의 민감도와 탐색적 프로파일 분석으로 각각 답한다.",
    )
    replace(
        document,
        "실험은 Ubuntu 26.04 LTS",
        "실험은 Ubuntu 26.04 LTS, Intel N95 4코어(최대 3.40 GHz), 메모리 7 GiB "
        "환경에서 수행하였다. Semgrep v1.157.0과 Gitleaks v8.21.2를 사용했으며, 공개 "
        "DT 14개는 development 환경과 16개 정책으로 실행하였다. Semgrep core 룰 번들 "
        "SHA-256은 574df0e5…a669e, Gitleaks 설정 SHA-256은 2ce9d818…430bb이다. "
        "명시적 제외 경로는 없고, 집계에서 엔진이 삽입한 .localci/workflow.yml만 "
        "제외하였다. 테스트·예제·생성 코드는 자동 스캔에 포함하고 문맥 검토에서 별도 "
        "배포 문맥으로 분류하였다.",
    )
    replace(
        document,
        "검증 절차는 연구 질문에 따라 구성하였다.",
        "검증 절차는 연구 질문에 따라 구성하였다. RQ1은 OWASP Benchmark v1.2와 정책이 "
        "중첩되는 6개 CWE의 TP·FP·FN 및 룰별 기여를 분석하였다. RQ2는 공개 DT 14개의 "
        "자동 탐지, 정확 위치 중복 제거 및 문맥 판독을 비교하였다. RQ3은 구성요소 제거와 "
        "보조지수 가중치 민감도를 평가하고, 코드 계보 중복의 영향을 탐색적으로 기술하였다.",
    )
    replace(
        document,
        "14개 공개 DT 웹앱은",
        "14개 공개 DT 웹앱은 표 5의 전체 커밋 SHA를 고정하고 development 환경에서 "
        "재검사하였다. 모든 저장소에서 두 스캐너가 완료되고 배포 제어 실행 상태 JSON이 "
        "생성되었으며, 저장소당 전체 분석 시간 중앙값은 30.5초였다. 자동 결과, 정확 위치 "
        "중복 제거 결과 및 Critical·High 문맥 판독 반영 결과를 표 8에 함께 제시한다.",
    )
    replace(
        document,
        "원시 탐지 482건 가운데",
        "원시 탐지 482건 가운데 274건이 CWE 보안 정책 카탈로그의 정책 적용 대상 탐지 "
        "항목으로 분류되고 208건은 정책 외 탐지 항목으로 분리되었다. 자동 CWE 기반 보안 "
        "등급 분포는 Critical 69건, High 8건, Medium 197건이며, 정확 위치 중복 제거 후 "
        "220개 위치로 축약되었다. 자동 취약점 의사결정 결과의 배포 제어 실행 상태는 PASS "
        "3개, WARN 1개, BLOCK_PENDING_APPROVAL 1개 및 BLOCK 9개였다. 문맥 판독에서는 "
        "Critical·High의 확인 패턴만 유지하고 Medium·Low는 중복 제거 자동 결과를 유지하였다. "
        "이를 반영한 취약점 의사결정 결과의 배포 제어 실행 상태는 PASS 3개, WARN 2개, "
        "BLOCK_PENDING_APPROVAL 1개 및 BLOCK 8개로 변경되었다.",
    )
    replace(
        document,
        "Table 8.",
        "Table 8. Automatic, deduplicated, and contextually adjusted DT results",
    )
    replace(
        document,
        "1명의 판독자가",
        "Critical 69건과 High 8건을 전수 검토하였다. Medium은 CWE-79 6건을 전수 "
        "검토하고, CWE-22 191건에서 난수 시드 20260723으로 24건을 비복원 단순무작위 "
        "추출하였다. 정확 위치 중복을 제외하면 Critical·High 72개, CWE-79 6개, CWE-22 "
        "표본 23개로 총 101개 위치다. 판독 기준은 확인된 위험 패턴, 문맥 제한 패턴, 오탐 "
        "및 중복이며, 확인된 위험 패턴은 위험 구문이나 자격증명 내장 패턴의 존재를 뜻할 "
        "뿐 실제 악용 가능성이 확인된 취약점을 의미하지 않는다.",
    )
    replace(
        document,
        "Table 9.",
        "Table 9. Contextual validation of automated DT findings",
    )
    replace(
        document,
        "Table 11.",
        "Table 11. Ablation results for scanner combination, policy filtering, deduplication, "
        "and deployment-control execution states after contextual adjudication",
    )
    replace(
        document,
        "Gitleaks 결합은 Semgrep 단독 대비",
        "Gitleaks 결합은 Semgrep 단독 대비 Hardcoded Secret을 포함하여 자동 BLOCK을 "
        "5개에서 9개로 확대하였다. 16종 정책 필터는 전체 482건을 274건으로 축약하면서 "
        "PASS를 1개에서 3개로 조정하였다. 정확 위치 중복 제거는 54건을 줄였으나 배포 "
        "제어 실행 상태 분포는 유지되었다. 문맥 검토는 실행 상태 한 건을 변경하였다. 이 "
        "결과는 자동 경고를 실제 악용 가능성이 확인된 취약점으로 간주하지 않고 검토 단계를 "
        "분리할 필요성을 보여준다.",
    )
    replace(
        document,
        "결과의 적용 범위는 다음과 같다.",
        "결과의 적용 범위는 다음과 같다. Benchmark 기준 성능은 정책과 중첩되는 6개 "
        "CWE에 한정되며, CWE-327은 TP=0, FN=130으로 현 룰셋의 명확한 미탐 영역이다. "
        "Critical·High는 전수 검토했지만 Medium CWE-22는 191건 중 고정 난수 24건만 "
        "표본 추출했으며, 자격증명 유효성 검사와 실제 공격 실행은 수행하지 않았다.",
    )
    replace(
        document,
        "향후 연구에서는 DT와 일반 운영 웹앱을",
        "향후 연구에서는 DT와 일반 운영 웹앱을 코드 규모·언어·저장소 유형별로 매칭하고, "
        "Medium 전체 판독, 자격증명 폐기 상태 확인, 생성 코드 도달 가능성 및 안전한 "
        "범위의 동적 재현을 추가하며, SCA·DAST·컨테이너 이미지 검사와 연결한다. 정책 "
        "가중치는 전문가 순위와의 상관 및 수정 전후 결과로 재보정하며, 고정 룰 번들과 "
        "원시 산출물 해시를 이용해 장기 재현성도 검증하고자 한다.",
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
        "validated=reviewer_references_removed:true tables:15 figure:1 "
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
