#!/usr/bin/env python3
"""Finalize the reproducible single-reviewer validation of DT findings.

The judgements in this file were made after inspecting the pinned source trees.
`confirmed_pattern` means that the reported risky construct is present; it does
not assert remote exploitability or that an embedded credential is still live.
`context_only` preserves a real pattern that is confined to tests, examples,
documentation, generated/build code, or whose external-input path is not shown.
Exact same-location cross-rule reports are `duplicate` and are excluded from the
unique-location denominator.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "analysis" / "dt_manual_validation_candidates.csv"
OUTPUT = ROOT / "analysis" / "dt_manual_validation_results.csv"
SUMMARY = ROOT / "analysis" / "dt_manual_validation_summary.json"


judgements: dict[str, tuple[str, str, str]] = {}


def add(ids: str, assessment: str, relevance: str, rationale: str) -> None:
    for raw in ids.split():
        finding_id = f"MV-{int(raw):03d}"
        if finding_id in judgements:
            raise ValueError(f"duplicate judgement for {finding_id}")
        judgements[finding_id] = (assessment, relevance, rationale)


# DT4: CPS-Twinning
add("1 2", "confirmed_pattern", "ci_release", "Unquoted workflow input or step output is interpolated into a shell run block.")
add("3 4", "context_only", "ci_release", "A fixed HTTPS installer URL is piped to a shell; this is a supply-chain pattern, not an untrusted-input CWE-78 path.")
add("5 6 7 8 9 10", "context_only", "test", "The matched GitLab PAT is an intentionally reused TEST_TOKEN in pytest fixtures and is explicitly marked as a test secret.")
add("11", "context_only", "example_config", "The bcrypt hash occurs in an example configuration rather than an active deployment configuration.")
add("12 13 14", "confirmed_pattern", "developer_tooling", "Hardcoded URL token, authorization token, and workspace cookie values are stored in an HTTP client support file; liveness was not tested.")
add("15 16", "confirmed_pattern", "production_source", "React dangerouslySetInnerHTML renders Markdown with HTML enabled and no sanitizer was found on the inspected data path.")

# DT5: iTwin.js core
add("17", "confirmed_pattern", "ci_release", "A Git ref name is interpolated unquoted into a workflow shell command; Git accepts command-substitution and semicolon characters in ref names.")
add("18 19 20 21 22", "confirmed_pattern", "ci_release", "Tag- or revision-derived strings are joined into commands executed with shell=True.")
add("23 24", "confirmed_pattern", "build_tooling", "Package name/version strings are concatenated into npm commands executed with shell=True.")
add("25 26", "context_only", "generated_build_tooling", "The generated Windows runner enables shell execution, but the sampled lines do not establish an untrusted external-input path.")
add("27 28 29 30 31 32 33 34", "false_positive", "test", "Gitleaks matched cache variable names such as partialKey; no credential literal is present.")
add("35", "context_only", "test", "An access-key literal is present in an integration test configuration; production use and liveness were not established.")
add("36", "false_positive", "build_tooling", "child_process.spawn is called with an argument array and without shell:true.")
add("37 39", "confirmed_pattern", "build_tooling", "A command-line tsconfig path is interpolated into execSync with shell:true.")
add("38", "duplicate", "build_tooling", "Exact same file and line as MV-037, reported by a second Semgrep rule.")
add("40", "context_only", "documentation", "The token literal occurs only in a README command example.")
add("41", "false_positive", "production_source", "The joined child filename is a fixed constant.")
add("42", "context_only", "library_source", "Caller-provided schema components are joined, but the sampled call path does not establish remote attacker control.")
add("43", "false_positive", "library_source", "The joined child directory is a fixed constant.")
add("44 45 46 47", "false_positive", "test", "The sampled join is confined to test/performance utilities and uses fixed or directory-enumerated child names.")
add("48 49", "context_only", "test_application", "The path is constructed in a test application; containment is not shown, while production reachability is not established.")
add("50", "context_only", "build_tooling", "A local CLI argument is resolved beneath a repository path without an explicit containment check.")
add("51 52", "context_only", "developer_tooling", "Local workspace-editor file arguments are joined without a containment check; the tool is not a remote server path.")

# DT6: iTwin.js
add("53", "false_positive", "build_tooling", "Beachball supplies a commit identifier to a fixed git command; no attacker-controlled shell path was established.")
add("54", "false_positive", "test_tooling", "spawn uses a command and argument array without shell:true.")
add("55 57 58 59", "false_positive", "build_tooling", "Workspace dependency-link scripts join fixed or package-manager-derived local paths.")
add("56", "duplicate", "build_tooling", "Exact same file and line as MV-055, emitted twice in the scan output.")
add("60", "false_positive", "test", "A test utility shortens an already constructed local path; no traversal source is present.")
add("61", "false_positive", "build_tooling", "The child name comes from readdirSync on the same local directory.")

# DT7-DT9: Vertexvis examples
add("62 63 64", "confirmed_pattern", "demo_source", "A stream-key credential literal is embedded in application source; key liveness was not tested.")

# DT10: OpenRemote
add("65 66", "confirmed_pattern", "ci_release", "Reusable-workflow inputs are interpolated into shell commands without shell-safe parameter passing.")
add("67 68", "confirmed_pattern", "deployment_config", "Kubernetes Secret manifests contain base64-encoded common default credentials in data fields.")
add("69", "confirmed_pattern", "setup_resource", "A private CA key is committed under setup resources; operational use and revocation status were not tested.")
add("70", "duplicate", "setup_resource", "Exact same private-key file and line as MV-069, reported by the second scanner.")
add("71 72", "context_only", "test", "Hardcoded client/API keys occur in test source; production use and liveness were not established.")
add("73 74 75 76 77 78", "context_only", "test_fixture", "Private keys are intentionally committed as provisioning test fixtures.")
add("79 80", "false_positive", "build_tooling", "Fixed Gradle commands and fixed arguments use shell:true without a sampled variable input.")
add("81", "false_positive", "production_source", "The ws:// text is nested in an internal Undertow component URI whose host is documented as unused for the existing listener.")
add("82 83", "false_positive", "demo_source", "htmlWebpackPlugin emits a trusted build-time asset URL into a demo HTML template.")
add("84", "false_positive", "build_tooling", "The joined child filename is the fixed .appignore constant.")

# DT11: GeoTwin
add("85", "confirmed_pattern", "deployment_config", "An API-key literal is embedded in docker-compose deployment configuration; liveness was not tested.")
add("86", "duplicate", "deployment_config", "Exact same file and line as MV-085, reported by the second scanner.")
add("87 89", "confirmed_pattern", "production_source", "The same API-key literal is embedded in backend and frontend source; liveness was not tested.")
add("88", "duplicate", "production_source", "Exact same file and line as MV-087, reported by the second scanner.")
add("90", "duplicate", "production_source", "Exact same file and line as MV-089, reported by the second scanner.")
add("91 92", "false_positive", "production_source", "Express sends a GeoTIFF Buffer as a binary proxy response; no HTML/JavaScript sink is present.")

# DT13: Bevywise MQTT Route
add("93 95 96", "false_positive", "documentation", "The insecure-WebSocket match is explanatory documentation, not an executable connection endpoint.")
add("94", "context_only", "documentation", "Documentation lists public ws:// test brokers alongside secure endpoints; it is not runtime code.")
add("97", "false_positive", "production_source", "The matched text is a user-interface hint, not a WebSocket URL used by a connection call.")
add("98", "confirmed_pattern", "production_source", "Production configuration validation explicitly accepts ws:// as well as wss:// for a broker endpoint.")
add("99", "false_positive", "production_source", "The matched text is only the validation error message adjacent to MV-098.")

# DT14: Meteor3D
add("100 101 102", "confirmed_pattern", "production_source", "The same map-service token is embedded at three source locations; liveness was not tested.")
add("103", "confirmed_pattern", "demo_source", "A fallback Cesium JWT is embedded in a source view; liveness was not tested.")
add("104", "false_positive", "production_source", "path.basename is applied to the child filename before path.join.")
add("105", "false_positive", "production_source", "The reported path uses a fixed output directory and path.basename of the input; no CWE-22 traversal is present at the finding.")
add("106 107", "false_positive", "production_source", "The reported paths use names returned by readdirSync and path.basename within the extraction directory.")


def nested_counts(rows: list[dict[str, str]], fields: tuple[str, ...]) -> dict[str, int]:
    counter = Counter("|".join(row[field] for field in fields) for row in rows)
    return dict(sorted(counter.items()))


def main() -> None:
    with INPUT.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))

    input_ids = {row["finding_id"] for row in rows}
    if input_ids != set(judgements):
        missing = sorted(input_ids - set(judgements))
        extra = sorted(set(judgements) - input_ids)
        raise ValueError(f"judgement coverage mismatch: missing={missing}, extra={extra}")

    for row in rows:
        assessment, relevance, rationale = judgements[row["finding_id"]]
        row["manual_assessment"] = assessment
        row["deployment_relevance"] = relevance
        row["review_rationale"] = rationale

    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    unique_rows = [row for row in rows if row["manual_assessment"] != "duplicate"]
    by_group: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for row in unique_rows:
        by_group[row["sample_group"]][row["manual_assessment"]] += 1

    summary = {
        "review_design": {
            "reviewers": 1,
            "inter_rater_kappa": None,
            "critical_high_sampling": "census",
            "medium_cwe79_sampling": "census",
            "medium_cwe22_sampling": "simple random sample without replacement",
            "medium_cwe22_seed": 20260723,
            "medium_cwe22_population": 191,
            "medium_cwe22_sample": 24,
            "credential_liveness_tested": False,
            "exploit_execution_performed": False,
        },
        "record_count": len(rows),
        "unique_location_count": len(unique_rows),
        "record_assessment_counts": nested_counts(rows, ("manual_assessment",)),
        "unique_assessment_counts": nested_counts(unique_rows, ("manual_assessment",)),
        "unique_by_severity_assessment": nested_counts(unique_rows, ("policy_severity", "manual_assessment")),
        "unique_by_cwe_assessment": nested_counts(unique_rows, ("cwe", "manual_assessment")),
        "unique_by_sample_group_assessment": {key: dict(sorted(value.items())) for key, value in sorted(by_group.items())},
        "unique_by_deployment_relevance": nested_counts(unique_rows, ("deployment_relevance",)),
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"output={OUTPUT}")
    print(f"summary={SUMMARY}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
