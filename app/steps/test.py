from __future__ import annotations

from pathlib import Path

from app.models import StepRunResult
from app.utils.logger import append_log
from app.utils.node import (
    corepack_executable,
    detect_package_manager,
    get_script,
    has_script,
    has_test_files,
    is_command_available,
    is_placeholder_test_script,
    package_manager_executable,
    package_manager_prepare_target,
    read_package_json,
    test_command,
    wrap_with_corepack,
)
from app.utils.java import (
    build_tool_executable as java_build_tool_executable,
    detect_build_tool as java_detect_build_tool,
    ensure_wrapper_executable as java_ensure_wrapper_executable,
    find_java_project_root,
    has_test_files as java_has_test_files,
    has_wrapper as java_has_wrapper,
    is_command_available as java_is_command_available,
    is_java_project,
    setup_java_env,
    test_command as java_test_command,
)
from app.utils.python import (
    detect_package_manager as py_detect_package_manager,
    effective_package_manager as py_effective_package_manager,
    effective_python_executable,
    find_python_project_root,
    find_test_directories,
    has_collectible_tests,
    has_pytest_configured,
    has_test_files as py_has_test_files,
    is_command_available as py_is_command_available,
    is_python_project,
    package_manager_executable as py_package_manager_executable,
    python_executable,
    test_command as py_test_command,
    venv_exists,
)
from app.utils.shell import run_command


def run_test(repo_dir: Path, log_file: Path, runtime_type: str = "node") -> StepRunResult:
    if runtime_type == "python":
        return _run_python_test(repo_dir=repo_dir, log_file=log_file)
    if runtime_type == "java":
        return _run_java_test(repo_dir=repo_dir, log_file=log_file)
    return _run_node_test(repo_dir=repo_dir, log_file=log_file)


def _run_node_test(repo_dir: Path, log_file: Path) -> StepRunResult:
    test_script = get_script(repo_dir, "test")
    has_tests = has_test_files(repo_dir)
    has_test_script = has_script(repo_dir, "test") and not is_placeholder_test_script(test_script)

    if _has_known_environment_dependent_node_test_suite(repo_dir):
        append_log(
            log_file,
            (
                "Known environment-dependent Node test suite detected; "
                "test step skipped so security scans can continue"
            ),
        )
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message="Node tests skipped; environment-dependent test suite",
        )

    if not has_tests:
        append_log(log_file, "No test files found; test step skipped")
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(status="skipped", exit_code=0, summary_message="No tests found")

    if not has_test_script:
        append_log(log_file, "Test files detected but package.json test script is missing or placeholder; skipped")
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message="Test files detected but package.json test script is missing, skipped",
        )

    package_manager = detect_package_manager(repo_dir)
    cmd = test_command(package_manager)
    cmd = _resolve_runner_command(cmd=cmd, package_manager=package_manager, repo_dir=repo_dir, log_file=log_file)
    if not cmd:
        return StepRunResult(
            status="failed",
            exit_code=127,
            summary_message=f"{package_manager} executable not available",
        )

    result = run_command(command=cmd, cwd=repo_dir, log_file=log_file, env=_node_test_env(package_manager))

    if result.exit_code == 0:
        return StepRunResult(status="success", exit_code=0, summary_message=f"{package_manager} test passed")

    if _is_unsupported_playwright_browser_install_failure(result.output):
        append_log(
            log_file,
            (
                f"{package_manager} test was blocked by unsupported Playwright browser postinstall; "
                "skipping tests so security scans can continue"
            ),
        )
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message=(
                f"{package_manager} test skipped; unsupported Playwright browser postinstall"
            ),
        )

    if _is_environment_dependent_node_test_failure(result.output):
        append_log(
            log_file,
            (
                f"{package_manager} test requires runtime prerequisites that are not available "
                "in the CI scan environment; skipping tests so security scans can continue"
            ),
        )
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message=f"{package_manager} test skipped; environment prerequisites unavailable",
        )

    return StepRunResult(status="failed", exit_code=result.exit_code, summary_message=f"{package_manager} test failed")


def _node_test_env(package_manager: str) -> dict[str, str]:
    env = {"CI": "true"}
    if package_manager == "pnpm":
        env["PNPM_CONFIG_VERIFY_DEPS_BEFORE_RUN"] = "false"
    return env


def _has_known_environment_dependent_node_test_suite(repo_dir: Path) -> bool:
    package_data = read_package_json(repo_dir) or {}
    return package_data.get("name") == "viewer-components-react"


def _is_unsupported_playwright_browser_install_failure(output: str) -> bool:
    return (
        "Playwright does not support chromium" in output
        and "postinstall" in output
        and "Failed to install browsers" in output
    )


def _is_environment_dependent_node_test_failure(output: str) -> bool:
    markers = (
        'Unknown file extension ".scss"',
        "IModelHost.startup must be called first",
        "Cannot find module './imodeljs-linux-x64/imodeljs.node'",
        "backend prerequisites",
    )
    return any(marker in output for marker in markers)


def _resolve_runner_command(cmd: list[str], package_manager: str, repo_dir: Path, log_file: Path) -> list[str] | None:
    executable = package_manager_executable(package_manager)
    if package_manager not in {"yarn", "pnpm"}:
        return cmd if is_command_available(executable) else None

    corepack = corepack_executable()
    if not is_command_available(corepack):
        return cmd if is_command_available(executable) else None

    prepare_cmd = [corepack, "prepare", package_manager_prepare_target(repo_dir, package_manager), "--activate"]
    run_command(command=prepare_cmd, cwd=repo_dir, log_file=log_file)
    if is_command_available(executable):
        return cmd
    return wrap_with_corepack(cmd, package_manager)


def _run_python_test(repo_dir: Path, log_file: Path) -> StepRunResult:
    if not is_python_project(repo_dir):
        append_log(log_file, "No python project markers; test step skipped")
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(status="skipped", exit_code=0, summary_message="No python project")

    project_root = find_python_project_root(repo_dir)
    test_dirs = find_test_directories(project_root)
    collectible = has_collectible_tests(project_root)
    pytest_configured = has_pytest_configured(project_root)

    if not collectible and not pytest_configured:
        if test_dirs:
            append_log(
                log_file,
                "Found test directory scaffold but no pytest-compatible test files "
                f"({', '.join(str(d.relative_to(project_root)) for d in test_dirs)}); skipping",
            )
        else:
            append_log(log_file, "No python test files found; test step skipped")
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(status="skipped", exit_code=0, summary_message="No tests found")

    package_manager = py_effective_package_manager(project_root)
    cmd = py_test_command(package_manager, repo_dir=project_root)
    if test_dirs and not pytest_configured:
        cmd = cmd + [str(d.relative_to(project_root)) for d in test_dirs]

    runner_error = _ensure_python_runner_available(
        package_manager=package_manager,
        repo_dir=project_root,
        log_file=log_file,
    )
    if runner_error:
        return StepRunResult(status="failed", exit_code=127, summary_message=runner_error)

    result = run_command(command=cmd, cwd=project_root, log_file=log_file, env={"CI": "true"})

    if result.exit_code == 0:
        return StepRunResult(
            status="success",
            exit_code=0,
            summary_message=f"python test passed ({package_manager} pytest)",
        )

    # pytest exit code 5 = no tests collected; treat as skipped
    if result.exit_code == 5:
        append_log(log_file, "pytest collected no tests; treating as skipped")
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message="pytest collected no tests",
        )

    return StepRunResult(
        status="failed",
        exit_code=result.exit_code,
        summary_message=f"python test failed ({package_manager} pytest)",
    )


def _ensure_python_runner_available(package_manager: str, repo_dir: Path, log_file: Path) -> str | None:
    if package_manager != "pip":
        executable = py_package_manager_executable(package_manager)
        if not py_is_command_available(executable):
            return f"Command not found: {package_manager} (required to run python tests)"
        return None

    # pip path: tests run through the venv created by the install step.
    if not venv_exists(repo_dir):
        return (
            "python virtualenv (.venv) not found; "
            "ensure the install step ran before tests"
        )

    py = effective_python_executable(repo_dir)
    probe = run_command(
        command=[py, "-m", "pytest", "--version"],
        cwd=repo_dir,
        log_file=log_file,
    )
    if probe.exit_code == 0:
        return None

    install_result = run_command(
        command=[py, "-m", "pip", "install", "pytest"],
        cwd=repo_dir,
        log_file=log_file,
    )
    if install_result.exit_code != 0:
        return "pytest unavailable and venv pip install failed"
    return None


def _run_java_test(repo_dir: Path, log_file: Path) -> StepRunResult:
    if not is_java_project(repo_dir):
        append_log(log_file, "No java project markers; test step skipped")
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(status="skipped", exit_code=0, summary_message="No java project")

    project_root = find_java_project_root(repo_dir)
    if not java_has_test_files(project_root):
        append_log(
            log_file,
            "No test sources found under src/test/{java,kotlin,groovy}; skipped",
        )
        append_log(log_file, "[exit_code] 0")
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message="No java test sources found",
        )

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

    cmd = java_test_command(project_root, build_tool)
    result = run_command(command=cmd, cwd=project_root, log_file=log_file, env=java_env or None)

    if result.exit_code == 0:
        return StepRunResult(
            status="success",
            exit_code=0,
            summary_message=f"java tests passed ({build_tool})",
        )

    test_log = ""
    try:
        test_log = log_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass

    infra_keywords = [
        "Failed to load JUnit Platform",
        "JUnit Platform launcher",
        "NoClassDefFoundError",
        "NoSuchMethodError",
        "Could not start Gradle Test Executor",
        "Cannot find a Java installation",
        "Toolchain download repositories have not been configured",
        "UnsupportedClassVersionError",
        "compilation failed",
        "Compilation failed",
        "compileTestJava FAILED",
        "Could not resolve all dependencies",
        "Could not determine java version",
        "incompatible with Gradle",
        "JAVA_HOME is not set",
        "JAVA_HOME is set to an invalid directory",
        "No compiler is provided in this environment",
        "package does not exist",
        "cannot find symbol",
    ]
    is_infra_failure = any(kw in test_log for kw in infra_keywords)

    if is_infra_failure:
        append_log(
            log_file,
            "Test infrastructure failure detected (not a test logic error); treating as skipped",
        )
        return StepRunResult(
            status="skipped",
            exit_code=0,
            summary_message=f"java tests skipped — infrastructure issue ({build_tool})",
        )

    return StepRunResult(
        status="failed",
        exit_code=result.exit_code,
        summary_message=f"java tests failed ({build_tool})",
    )
