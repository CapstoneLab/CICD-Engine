# GitHub Actions + CodeQL baseline

This directory is a standalone baseline for the paper experiment that compares a regular GitHub Actions + CodeQL DevSecOps pipeline with the custom CI/CD engine.

## What is included

- `.github/workflows/codeql-analysis.yml`: GitHub Actions workflow that runs CodeQL.
- `.github/workflows/codeql-target-repos.yml`: experiment workflow that runs CodeQL against the paper target repositories.
- `.github/codeql/codeql-config.yml`: CodeQL config scoped to `src`.
- `scripts/count_codeql_sarif.py`: SARIF counter for CodeQL finding totals, levels, CWE tags, and top rules.
- `src/vulnerable_flask_app.py`: intentionally vulnerable Python sample.
- `src/vulnerable_express_app.js`: intentionally vulnerable JavaScript sample.

The workflow analyzes both `python` and `javascript-typescript`, uploads CodeQL results to GitHub code scanning, stores SARIF as a workflow artifact, and writes elapsed time plus finding counts to the job summary.

## How to run the job

1. Create a new GitHub repository for this baseline, or make `CodeQL` the root of a repository.
2. Push the contents of this directory.
3. Open GitHub Actions.
4. Run `GitHub Actions + CodeQL` manually with `workflow_dispatch`.
5. Check:
   - `Actions > GitHub Actions + CodeQL > Summary` for elapsed seconds and finding count.
   - `Actions > Artifacts` for SARIF files.
   - `Security > Code scanning` for CodeQL alerts.

## How to run the paper target experiment

Run `CodeQL Target Repository Experiment` from GitHub Actions. The matrix uses the same target repositories as the paper experiment:

| Target | Repository | Branch | CodeQL language |
| --- | --- | --- | --- |
| juice | `printwd/juice-shop` | `master` | `javascript-typescript` |
| DjanGoat | `printwd/DjanGoat` | `master` | `python` |
| WebGoat | `printwd/WebGoat` | `main` | `java-kotlin` |

For each target, the workflow stores:

- `codeql-results/<target>/<language>/*.sarif`
- `codeql-counts/<target>/codeql-count-summary.json`
- `codeql-counts/<target>/codeql-count-summary.md`

Use `total_findings` from `codeql-count-summary.json` as the CodeQL detection count in the comparison table.

## Notes for comparison

- Use the same target source code when comparing with the custom engine.
- Run at least three repeated jobs and average the elapsed seconds.
- For the paper table, use the workflow summary value as the CodeQL analysis time.
- CodeQL findings are not automatically converted into a CWE gate here. That limitation is the comparison point against the custom engine's CWE policy gate.
