from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


SCRIPT = (
    Path(__file__).resolve().parents[1] / "evaluate_owasp_benchmark_v12.py"
)
SPEC = importlib.util.spec_from_file_location("benchmark_evaluator", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def test_rule_semantic_harmonization_and_scoring() -> None:
    truth = {
        "BenchmarkTest00001": MODULE.Truth(cwe=327, vulnerable=True),
        "BenchmarkTest00002": MODULE.Truth(cwe=327, vulnerable=False),
        "BenchmarkTest00003": MODULE.Truth(cwe=328, vulnerable=True),
    }
    detections = [
        MODULE.Detection(
            test_id="BenchmarkTest00001",
            cwe=326,
            rule_id="local.config.namespace.des-rule",
        ),
        MODULE.Detection(
            test_id="BenchmarkTest00003",
            cwe=328,
            rule_id="md5-rule",
        ),
    ]

    strict = MODULE.score(truth, detections)
    assert strict["per_cwe"]["CWE-327"]["fn"] == 1
    assert strict["category_aligned_micro"]["tp"] == 1

    harmonized, applied = MODULE.harmonize(
        detections,
        {"des-rule": ({326}, 327)},
    )
    improved = MODULE.score(truth, harmonized)

    assert applied == {"des-rule": 1}
    assert improved["per_cwe"]["CWE-327"] == {
        "tp": 1,
        "fp": 0,
        "fn": 0,
        "tn": 1,
        "precision": 1.0,
        "recall": 1.0,
        "f1": 1.0,
    }
    assert improved["category_aligned_micro"]["tp"] == 2
    assert improved["category_aligned_micro"]["f1"] == 1.0


def test_taxonomy_strict_counts_cross_cwe_alerts_as_fp() -> None:
    truth = {
        "BenchmarkTest00001": MODULE.Truth(cwe=89, vulnerable=True),
        "BenchmarkTest00002": MODULE.Truth(cwe=79, vulnerable=False),
    }
    detections = [
        MODULE.Detection("BenchmarkTest00001", 89, "sqli-rule"),
        MODULE.Detection("BenchmarkTest00001", 79, "xss-rule"),
    ]

    report = MODULE.score(truth, detections)

    assert report["category_aligned_micro"]["fp"] == 0
    assert report["taxonomy_strict_micro"]["same_cwe_fp"] == 0
    assert report["taxonomy_strict_micro"]["cross_cwe_fp"] == 1
    assert report["taxonomy_strict_micro"]["fp"] == 1
