#!/usr/bin/env python3
"""Validate the final KCI DOCX against the generated experiment artifacts."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from docx import Document
from docx.oxml.ns import qn


ROOT = Path(__file__).resolve().parents[1]
DOCX = ROOT / "웹 기반 디지털트윈_KCI_실험검증_최종개정본.docx"


def main() -> None:
    manual = json.loads((ROOT / "analysis/dt_manual_validation_summary.json").read_text())
    experiment = json.loads((ROOT / "analysis/dt_revision_experiments.json").read_text())
    metadata = json.loads((ROOT / "analysis/dt_repository_metadata.json").read_text())
    with zipfile.ZipFile(DOCX) as archive:
        if bad := archive.testzip():
            raise AssertionError(f"corrupt member: {bad}")
        document_xml = archive.read("word/document.xml").decode("utf-8")
        assert "secu_pipeline_flow.png" in archive.read("word/_rels/document.xml.rels").decode("utf-8")

    document = Document(DOCX)
    assert len(document.tables) == 13
    assert len(document.sections) == 1
    assert document.paragraphs[-1].text.strip()
    assert "w:type=\"page\"" not in document_xml
    for table in document.tables:
        assert all(len(row.cells) == len(table.columns) for row in table.rows)
        assert table.rows[0]._tr.get_or_add_trPr().find(qn("w:tblHeader")) is not None

    all_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    all_text += "\n" + "\n".join(
        cell.text for table in document.tables for row in table.rows for cell in row.cells
    )
    for forbidden in ("0.XX", "X.XX", "v8.30.1", "DT 특이", "최초의 저장소", "승인 대기"):
        assert forbidden not in all_text, forbidden
    for required in (
        "F1-Score 0.630", "Critical·High 77건", "BLOCK_PENDING_APPROVAL",
        "ρ=0.999", "1,074개 OSS 룰", "Gitleaks v8.21.2",
        "4.5 DT와 검증용 취약 웹앱의 저장소 단위 CWE 탐지 프로파일 비교",
    ):
        assert required in all_text, required

    assert manual["unique_location_count"] == 101
    assert manual["unique_assessment_counts"] == {
        "confirmed_pattern": 33, "context_only": 28, "false_positive": 40
    }
    assert experiment["ablation"]["combined_policy"]["finding_count"] == 274
    assert experiment["ablation"]["combined_policy_deduplicated"]["finding_count"] == 220
    assert experiment["ablation"]["manual_ch_confirmed_raw_ml"]["finding_count"] == 179
    assert len(metadata) == 14
    for row in metadata:
        assert row["full_commit_sha"] in all_text

    print(f"validated={DOCX}")
    print("tables=13 repeated_headers=13 explicit_page_breaks=0")
    print("quantitative_crosschecks=passed full_commit_shas=14 forbidden_placeholders=0")


if __name__ == "__main__":
    main()
