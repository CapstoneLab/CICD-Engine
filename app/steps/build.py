from __future__ import annotations

import json
import shutil
from pathlib import Path

from app.models import StepRunResult
from app.utils.logger import append_log
from app.utils.node import (
    corepack_executable,
    detect_package_manager,
    has_script,
    is_command_available,
    package_manager_executable,
    package_manager_prepare_target,
    run_script_command,
    wrap_with_corepack,
)
from app.utils.java import (
    artifact_directories as java_artifact_directories,
    build_command as java_build_command,
    build_command_fallbacks as java_build_command_fallbacks,
    build_tool_executable as java_build_tool_executable,
    detect_build_tool as java_detect_build_tool,
    ensure_wrapper_executable as java_ensure_wrapper_executable,
    find_java_project_root,
    has_wrapper as java_has_wrapper,
    is_command_available as java_is_command_available,
    is_deployable_artifact as java_is_deployable_artifact,
    is_java_project,
    setup_java_env,
)
from app.utils.python import (
    AsgiEntryPoint,
    build_command as py_build_command,
    detect_package_manager as py_detect_package_manager,
    effective_package_manager as py_effective_package_manager,
    effective_python_executable,
    find_asgi_entry_point,
    find_python_project_root,
    is_command_available as py_is_command_available,
    is_python_project,
    package_manager_executable as py_package_manager_executable,
    plan_entry_wrapper,
    python_executable,
    venv_exists,
    write_entry_wrapper,
)
from app.utils.shell import run_command


def run_build(
    repo_dir: Path,
    log_file: Path,
    artifacts_dir: Path,
    runtime_type: str = "node",
) -> StepRunResult:
    if runtime_type == "python":
        return _run_python_build(repo_dir=repo_dir, log_file=log_file, artifacts_dir=artifacts_dir)
    if runtime_type == "java":
        return _run_java_build(repo_dir=repo_dir, log_file=log_file, artifacts_dir=artifacts_dir)
    return _run_node_build(repo_dir=repo_dir, log_file=log_file, artifacts_dir=artifacts_dir)


def _run_node_build(repo_dir: Path, log_file: Path, artifacts_dir: Path) -> StepRunResult:
    package_manager = detect_package_manager(repo_dir)
    use_corepack = _should_use_corepack_runner(repo_dir=repo_dir, package_manager=package_manager, log_file=log_file)
    build_scripts: list[str] = []

    if has_script(repo_dir, "build"):
        build_scripts = ["build"]
    else:
        if has_script(repo_dir, "build:frontend"):
            build_scripts.append("build:frontend")
        if has_script(repo_dir, "build:server"):
            build_scripts.append("build:server")

    if not build_scripts:
        append_log(log_file, "No supported build scripts found: build, build:frontend, build:server")
        if has_script(repo_dir, "start") or (repo_dir / "server.js").exists():
            generated_names = _create_fallback_artifacts(
                repo_dir=repo_dir,
                artifacts_dir=artifacts_dir,
                build_scripts=["start"],
            )
            append_log(
                log_file,
                "No build script required for server-style Node app; generated deployable fallback artifacts",
            )
            return StepRunResult(
                status="success",
                exit_code=0,
                summary_message=(
                    "node server app has no build script; "
                    f"fallback artifacts saved: {', '.join(generated_names)}"
                ),
            )
        return StepRunResult(status="failed", exit_code=1, summary_message="build script missing in package.json")

    for script_name in build_scripts:
        cmd = run_script_command(package_manager, script_name)
        if use_corepack:
            cmd = wrap_with_corepack(cmd, package_manager)
        # Some toolchains (e.g., react-scripts) treat warnings as errors when CI=true.
        # Build should fail only on actual errors, not warnings.
        result = run_command(command=cmd, cwd=repo_dir, log_file=log_file, env=_node_build_env(package_manager))
        if result.exit_code != 0:
            if _is_unsupported_playwright_browser_install_failure(result.output):
                append_log(
                    log_file,
                    (
                        f"{package_manager} run {script_name} was blocked by unsupported "
                        "Playwright browser postinstall; generating fallback artifacts"
                    ),
                )
                generated_names = _create_fallback_artifacts(
                    repo_dir=repo_dir,
                    artifacts_dir=artifacts_dir,
                    build_scripts=build_scripts,
                )
                return StepRunResult(
                    status="success",
                    exit_code=0,
                    summary_message=(
                        f"{package_manager} run {script_name} skipped unsupported Playwright "
                        f"browser postinstall; fallback artifacts saved: {', '.join(generated_names)}"
                    ),
                )
            return StepRunResult(
                status="failed",
                exit_code=result.exit_code,
                summary_message=f"{package_manager} run {script_name} failed",
            )

    collected = _collect_build_artifacts(repo_dir=repo_dir, artifacts_dir=artifacts_dir)
    if not collected:
        generated_names = _create_fallback_artifacts(
            repo_dir=repo_dir,
            artifacts_dir=artifacts_dir,
            build_scripts=build_scripts,
        )
        append_log(
            log_file,
            "Build completed without known output directories; generated deployable fallback artifacts",
        )
        collected.extend(generated_names)

    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message=(
            "build scripts succeeded: "
            + ", ".join(build_scripts)
            + f" | artifacts saved: {', '.join(collected)}"
        ),
    )


def _node_build_env(package_manager: str) -> dict[str, str]:
    env = {"CI": "false"}
    if package_manager == "pnpm":
        env["PNPM_CONFIG_VERIFY_DEPS_BEFORE_RUN"] = "false"
    return env


def _is_unsupported_playwright_browser_install_failure(output: str) -> bool:
    return (
        "Playwright does not support chromium" in output
        and "postinstall" in output
        and "Failed to install browsers" in output
    )


def _collect_build_artifacts(repo_dir: Path, artifacts_dir: Path) -> list[str]:
    candidates = ["dist", "build", "out", ".next", ".output", "release", "public/build"]
    collected: list[str] = []

    for relative in candidates:
        source = repo_dir / relative
        if not source.exists():
            continue

        destination = artifacts_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)

        if source.is_dir():
            if not any(source.iterdir()):
                continue
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(source, destination)
            collected.append(relative)
            continue

        shutil.copy2(source, destination)
        collected.append(relative)

    return collected


def _create_fallback_artifacts(repo_dir: Path, artifacts_dir: Path, build_scripts: list[str]) -> list[str]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    fallback_dir_name = "dist-server"
    fallback_dir_path = artifacts_dir / fallback_dir_name
    _create_node_fallback_directory(repo_dir=repo_dir, output_dir=fallback_dir_path)

    fallback_path = artifacts_dir / "build_meta.json"
    payload = {
        "repo": str(repo_dir),
        "build_scripts": build_scripts,
        "note": "No known build output directory detected; generated deployable fallback directory.",
        "fallback_directory": fallback_dir_name,
    }
    fallback_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return [fallback_dir_name, fallback_path.name]


def _should_use_corepack_runner(repo_dir: Path, package_manager: str, log_file: Path) -> bool:
    executable = package_manager_executable(package_manager)
    if package_manager not in {"yarn", "pnpm"}:
        return False

    corepack = corepack_executable()
    if not is_command_available(corepack):
        return False

    prepare_cmd = [corepack, "prepare", package_manager_prepare_target(repo_dir, package_manager), "--activate"]
    run_command(command=prepare_cmd, cwd=repo_dir, log_file=log_file)
    return not is_command_available(executable)


def _create_node_fallback_directory(repo_dir: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    excluded_dirs = {
        ".git",
        "node_modules",
        ".next",
        "dist",
        "build",
        "coverage",
        ".cache",
        ".rush",
        ".pnpm-store",
        "pnpm-local",
        "pnpm-store",
    }
    excluded_prefixes = {
        Path("common/temp"),
    }
    excluded_files = {
        ".DS_Store",
    }

    for path in sorted(repo_dir.rglob("*")):
        rel = path.relative_to(repo_dir)

        if any(part in excluded_dirs for part in rel.parts):
            continue

        if any(rel == prefix or prefix in rel.parents for prefix in excluded_prefixes):
            continue

        if path.name in excluded_files:
            continue

        if path.is_symlink():
            continue

        destination = output_dir / rel
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _run_python_build(repo_dir: Path, log_file: Path, artifacts_dir: Path) -> StepRunResult:
    if not is_python_project(repo_dir):
        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message="No Python project markers found (pyproject.toml / setup.py)",
        )

    project_root = find_python_project_root(repo_dir)
    package_manager = py_effective_package_manager(project_root)

    # Detect ASGI entry point up-front by AST-scanning the source tree.
    # The result is baked into build_meta.json so the deploy step does
    # not have to redo this work on EC2 (where AST scanning would be
    # awkward) and so src-layout / factory patterns are handled correctly.
    entry = find_asgi_entry_point(project_root)
    if entry is not None:
        append_log(
            log_file,
            (
                f"Detected ASGI entry point: {entry.module}:{entry.attr} "
                f"(factory={entry.is_factory}, app_dir={entry.app_dir}, "
                f"file={entry.file_path}, required_kwargs={entry.required_kwargs})"
            ),
        )
        # uvicorn's --factory flag cannot supply arguments. If the factory
        # requires any, synthesise a wrapper module that invokes it with
        # heuristically-derived defaults and redirect the entry point to
        # that wrapper (which exposes a plain module-level `app`).
        if entry.is_factory and entry.required_kwargs:
            plan = plan_entry_wrapper(entry)
            if plan is not None:
                wrapped_entry = write_entry_wrapper(project_root=project_root, plan=plan)
                append_log(
                    log_file,
                    (
                        f"Generated entry wrapper {wrapped_entry.file_path} "
                        f"injecting kwargs {sorted(plan.injected_kwargs.keys())}; "
                        f"entry rewritten to {wrapped_entry.module}:{wrapped_entry.attr}"
                    ),
                )
                entry = wrapped_entry
            else:
                append_log(
                    log_file,
                    (
                        f"Cannot auto-wrap factory {entry.module}:{entry.attr}: "
                        f"required args {entry.required_kwargs} have no safe default. "
                        "Deploy will likely fail; the repo needs an arg-free factory or a "
                        "module-level `app = ...` assignment."
                    ),
                )
    else:
        append_log(
            log_file,
            "No ASGI entry point detected; deploy will fall back to heuristic candidates.",
        )

    # Python apps are deployed by running the source tree directly via
    # uvicorn/gunicorn, not by installing a wheel. Building a wheel with
    # `python -m build` produces only *.whl / *.tar.gz under `dist/`, which
    # breaks the deploy step's entry-point search. Always package the source
    # tree as the deployable artifact so deploy has everything it needs.
    append_log(
        log_file,
        f"Packaging python source tree as deployable artifact ({package_manager}); "
        "wheel/sdist build is skipped because deploy runs from source.",
    )
    generated = _create_python_fallback_artifacts(
        repo_dir=project_root,
        artifacts_dir=artifacts_dir,
        package_manager=package_manager,
        entry=entry,
    )

    summary_entry = f" | entry: {entry.module}:{entry.attr}" if entry else ""
    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message=(
            f"python source packaged ({package_manager}) | artifacts saved: "
            f"{', '.join(generated)}{summary_entry}"
        ),
    )


def _create_python_fallback_artifacts(
    repo_dir: Path,
    artifacts_dir: Path,
    package_manager: str,
    entry: AsgiEntryPoint | None = None,
) -> list[str]:
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    fallback_dir_name = "dist-python"
    fallback_dir_path = artifacts_dir / fallback_dir_name
    _create_python_fallback_directory(repo_dir=repo_dir, output_dir=fallback_dir_path)

    meta_path = artifacts_dir / "build_meta.json"
    payload: dict = {
        "repo": str(repo_dir),
        "runtime": "python",
        "package_manager": package_manager,
        "note": "No python wheel/sdist produced; packaged source tree as deployable fallback.",
        "fallback_directory": fallback_dir_name,
    }
    if entry is not None:
        payload["entry"] = {
            "module": entry.module,
            "attr": entry.attr,
            "factory": entry.is_factory,
            "app_dir": entry.app_dir,
            "file_path": entry.file_path,
        }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return [fallback_dir_name, meta_path.name]


def _create_python_fallback_directory(repo_dir: Path, output_dir: Path) -> None:
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    excluded_dirs = {
        ".git",
        ".venv",
        "venv",
        "env",
        "__pycache__",
        "build",
        "dist",
        ".tox",
        ".pytest_cache",
        ".mypy_cache",
        ".cache",
        "node_modules",
        ".eggs",
    }
    excluded_files = {".DS_Store"}

    for path in sorted(repo_dir.rglob("*")):
        rel = path.relative_to(repo_dir)

        if any(part in excluded_dirs for part in rel.parts):
            continue
        if any(part.endswith(".egg-info") for part in rel.parts):
            continue
        if path.name in excluded_files:
            continue

        destination = output_dir / rel
        if path.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _run_java_build(repo_dir: Path, log_file: Path, artifacts_dir: Path) -> StepRunResult:
    if not is_java_project(repo_dir):
        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message="No Java project markers found (pom.xml / build.gradle)",
        )

    project_root = find_java_project_root(repo_dir)
    build_tool = java_detect_build_tool(project_root)
    java_ensure_wrapper_executable(project_root, build_tool)

    using_wrapper = java_has_wrapper(project_root, build_tool)
    executable = java_build_tool_executable(project_root, build_tool)
    if not using_wrapper and not java_is_command_available(executable):
        return StepRunResult(
            status="failed",
            exit_code=127,
            summary_message=(
                f"Command not found: {build_tool} "
                f"(install it on the engine host or include the {build_tool} wrapper)"
            ),
        )

    java_env = setup_java_env()

    cmd = java_build_command(project_root, build_tool)
    result = run_command(command=cmd, cwd=project_root, log_file=log_file, env=java_env or None)
    if result.exit_code != 0:
        fallbacks = java_build_command_fallbacks(project_root, build_tool)
        succeeded = False
        for fallback_cmd in fallbacks:
            append_log(log_file, f"Primary build failed; trying fallback: {' '.join(fallback_cmd)}")
            fallback_result = run_command(command=fallback_cmd, cwd=project_root, log_file=log_file, env=java_env or None)
            if fallback_result.exit_code == 0:
                succeeded = True
                break
        if not succeeded:
            return StepRunResult(
                status="failed",
                exit_code=result.exit_code,
                summary_message=f"java build failed ({build_tool})",
            )

    collected = _collect_java_build_artifacts(
        project_root=project_root,
        artifacts_dir=artifacts_dir,
        build_tool=build_tool,
    )
    if not collected:
        append_log(
            log_file,
            f"Java build ({build_tool}) succeeded but no JAR/WAR artifacts were found "
            f"in {', '.join(java_artifact_directories(build_tool))}",
        )
        return StepRunResult(
            status="failed",
            exit_code=1,
            summary_message=f"java build produced no deployable JAR/WAR ({build_tool})",
        )

    meta_path = artifacts_dir / "build_meta.json"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "repo": str(project_root),
        "runtime": "java",
        "build_tool": build_tool,
        "artifacts": collected,
    }
    meta_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return StepRunResult(
        status="success",
        exit_code=0,
        summary_message=(
            f"java build succeeded ({build_tool}) | artifacts: {', '.join(collected)}"
        ),
    )


def _collect_java_build_artifacts(
    project_root: Path,
    artifacts_dir: Path,
    build_tool: str,
) -> list[str]:
    collected: list[str] = []
    for relative in java_artifact_directories(build_tool):
        source_dir = project_root / relative
        if not source_dir.exists() or not source_dir.is_dir():
            continue
        for pattern in ("*.jar", "*.war", "*.ear"):
            for artifact in sorted(source_dir.glob(pattern)):
                if not java_is_deployable_artifact(artifact):
                    continue
                artifacts_dir.mkdir(parents=True, exist_ok=True)
                destination = artifacts_dir / artifact.name
                shutil.copy2(artifact, destination)
                collected.append(artifact.name)
    return collected
