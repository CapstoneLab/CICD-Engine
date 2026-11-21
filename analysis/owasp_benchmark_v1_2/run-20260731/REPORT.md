# OWASP Benchmark v1.2 fair Semgrep evaluation

The ground-truth CSV was used only after scanning. Findings are deduplicated at `(Benchmark test ID, CWE)`. No test-ID or expected-label exceptions are permitted in the harmonization file.

## Summary

| Mode | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| strict | 1118 | 552 | 297 | 773 | 0.669 | 0.790 | 0.725 |
| harmonized | 1248 | 552 | 167 | 773 | 0.693 | 0.882 | 0.776 |

The summary uses category-aligned OWASP-style scoring. `taxonomy_strict_micro` in `metrics.json` additionally penalizes alerts whose predicted Benchmark CWE differs from the test's expected CWE.

## Taxonomy-strict diagnostic

| Mode | TP | Same-CWE FP | Cross-CWE FP | Total FP | FN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| strict | 1118 | 552 | 146 | 698 | 297 | 0.616 | 0.790 | 0.692 |
| harmonized | 1248 | 552 | 146 | 698 | 167 | 0.641 | 0.882 | 0.743 |

## Declared CWE harmonization

| Semgrep rule | From CWE | Benchmark CWE | Rationale |
|---|---:|---:|---|
| java.lang.security.audit.crypto.des-is-deprecated.des-is-deprecated | 326 | 327 | The rule detects use of DES. Semgrep classifies the weakness as CWE-326, while OWASP Benchmark v1.2 classifies its broken/risky symmetric-crypto cases as CWE-327. |
| java.lang.security.audit.crypto.desede-is-deprecated.desede-is-deprecated | 326 | 327 | The rule detects use of 3DES/DESede. Semgrep classifies the weakness as CWE-326, while OWASP Benchmark v1.2 classifies its broken/risky symmetric-crypto cases as CWE-327. |

## Harmonized per-CWE metrics

| CWE | TP | FP | FN | TN | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|
| CWE-22 | 120 | 106 | 13 | 29 | 0.531 | 0.902 | 0.669 |
| CWE-78 | 117 | 109 | 9 | 16 | 0.518 | 0.929 | 0.665 |
| CWE-79 | 202 | 108 | 44 | 101 | 0.652 | 0.821 | 0.727 |
| CWE-89 | 253 | 170 | 19 | 62 | 0.598 | 0.930 | 0.728 |
| CWE-90 | 26 | 28 | 1 | 4 | 0.481 | 0.963 | 0.642 |
| CWE-327 | 130 | 0 | 0 | 116 | 1.000 | 1.000 | 1.000 |
| CWE-328 | 89 | 0 | 40 | 107 | 1.000 | 0.690 | 0.817 |
| CWE-330 | 218 | 0 | 0 | 275 | 1.000 | 1.000 | 1.000 |
| CWE-501 | 43 | 18 | 40 | 25 | 0.705 | 0.518 | 0.597 |
| CWE-614 | 36 | 0 | 0 | 31 | 1.000 | 1.000 | 1.000 |
| CWE-643 | 14 | 13 | 1 | 7 | 0.519 | 0.933 | 0.667 |

## Reproducibility

- Scanner: Semgrep 1.157.0
- Source commit: `0352dbb5a4f1e9c29edb2d648bd869bd9f431dcd`
- Scanner command: `cd /home/capstone/CICD-Engine/workspace/run-20260624-017/repo && SEMGREP_ENABLE_VERSION_CHECK=0 semgrep --metrics=off --config /home/capstone/CICD-Engine/analysis/reproducibility/semgrep-auto-rules-20260723.json --json --output /home/capstone/CICD-Engine/analysis/owasp_benchmark_v1_2/run-20260731/semgrep_report.json src/main/java/org/owasp/benchmark/testcode`
- Truth SHA-256: `1809f6a690c6cf7dd6685df6ebe2eef8fe3ca93d19a7ca0ce45987ca4f5d78e1`
- Semgrep report SHA-256: `945c018ab70a8adbaae4af6a75fa72cad3275692eb80ad7611b123e0ba6ed226`
- Harmonization SHA-256: `f65e20c0723a0cf0baf48005ea2a13cf115c63d90c70d4d6ddf3b4d9a1544a7d`
- Rule config SHA-256: `574df0e554aad5b8e981d05a5eab3008f39654566d57d9fb2f64da3f630a669e`
