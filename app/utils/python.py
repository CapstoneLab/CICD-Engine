from __future__ import annotations

import ast
import fnmatch
import os
import re
import shutil
from dataclasses import dataclass, field as dataclasses_field
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - python < 3.11 fallback
    try:
        import tomli as tomllib  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        tomllib = None  # type: ignore[assignment]


# Packages that are provided and invoked by the engine itself, so they
# must NOT be re-installed as project dependencies. semgrep in particular
# drags in 200MB+ of deps and its wheel build has been known to OOM
# small EC2 hosts. gitleaks is a Go binary also shipped by the engine.
ENGINE_MANAGED_PYTHON_PACKAGES = {"semgrep", "gitleaks"}


SUPPORTED_PACKAGE_MANAGERS = {"pip", "poetry", "pipenv", "uv", "pdm", "hatch"}

VENV_DIR_NAME = ".venv"

_PROJECT_MARKERS = (
    "pyproject.toml",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
    "Pipfile",
)


def read_pyproject(repo_dir: Path) -> dict:
    pyproject = repo_dir / "pyproject.toml"
    if not pyproject.exists() or tomllib is None:
        return {}
    try:
        with pyproject.open("rb") as fp:
            return tomllib.load(fp)
    except (OSError, ValueError):
        return {}


def has_pyproject(repo_dir: Path) -> bool:
    return (repo_dir / "pyproject.toml").exists()


def has_requirements_txt(repo_dir: Path) -> bool:
    return (repo_dir / "requirements.txt").exists()


def _has_python_marker(directory: Path) -> bool:
    return any((directory / marker).exists() for marker in _PROJECT_MARKERS)


def find_python_project_root(repo_dir: Path, max_depth: int = 3) -> Path:
    """Locate the directory that owns the python project markers.

    Checks the repo root first; if nothing is found, performs a bounded
    breadth-first scan to support monorepos (e.g. `backend/pyproject.toml`).
    Falls back to ``repo_dir`` when no markers are present anywhere.
    """
    if _has_python_marker(repo_dir):
        return repo_dir

    queue: list[tuple[Path, int]] = [(repo_dir, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir())
        except (OSError, PermissionError):
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in _IGNORED_DIRS:
                continue
            if _has_python_marker(child):
                return child
            queue.append((child, depth + 1))
    return repo_dir


def is_python_project(repo_dir: Path) -> bool:
    return _has_python_marker(find_python_project_root(repo_dir))


def python_executable() -> str:
    if os.name == "nt":
        return "python"
    if shutil.which("python3"):
        return "python3"
    return "python"


def venv_dir(repo_dir: Path) -> Path:
    return repo_dir / VENV_DIR_NAME


def venv_python(repo_dir: Path) -> Path:
    base = venv_dir(repo_dir)
    if os.name == "nt":
        return base / "Scripts" / "python.exe"
    return base / "bin" / "python"


def venv_exists(repo_dir: Path) -> bool:
    return venv_python(repo_dir).exists()


def create_venv_command(repo_dir: Path) -> list[str]:
    return [python_executable(), "-m", "venv", "--copies", str(venv_dir(repo_dir))]


def effective_python_executable(repo_dir: Path) -> str:
    if venv_exists(repo_dir):
        return str(venv_python(repo_dir))
    return python_executable()


def package_manager_executable(package_manager: str) -> str:
    if package_manager == "pip":
        return python_executable()
    if package_manager in SUPPORTED_PACKAGE_MANAGERS:
        return package_manager
    return package_manager


def is_command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def effective_package_manager(repo_dir: Path) -> str:
    """Like :func:`detect_package_manager` but downgrades to ``pip`` when the
    detected manager is not installed on the host and ``requirements.txt``
    provides a viable fallback."""
    manager = detect_package_manager(repo_dir)
    if manager == "pip":
        return manager
    executable = package_manager_executable(manager)
    if is_command_available(executable):
        return manager
    if (repo_dir / "requirements.txt").exists():
        return "pip"
    return manager


def detect_package_manager(repo_dir: Path) -> str:
    data = read_pyproject(repo_dir)
    tool_section = data.get("tool") if isinstance(data, dict) else None
    tool = tool_section if isinstance(tool_section, dict) else {}

    if "poetry" in tool:
        return "poetry"
    if "pdm" in tool:
        return "pdm"
    if "hatch" in tool:
        return "hatch"
    if "uv" in tool:
        return "uv"

    if (repo_dir / "poetry.lock").exists():
        return "poetry"
    if (repo_dir / "pdm.lock").exists():
        return "pdm"
    if (repo_dir / "uv.lock").exists():
        return "uv"
    if (repo_dir / "Pipfile.lock").exists() or (repo_dir / "Pipfile").exists():
        return "pipenv"

    build_system = data.get("build-system") if isinstance(data, dict) else None
    if isinstance(build_system, dict):
        requires = build_system.get("requires", [])
        if isinstance(requires, list):
            requires_str = " ".join(str(item).lower() for item in requires)
            if "hatchling" in requires_str:
                return "hatch"
            if "poetry-core" in requires_str or "poetry_core" in requires_str:
                return "poetry"
            if "pdm-backend" in requires_str or "pdm_backend" in requires_str:
                return "pdm"

    return "pip"


def has_lock_file(repo_dir: Path, package_manager: str) -> bool:
    if package_manager == "poetry":
        return (repo_dir / "poetry.lock").exists()
    if package_manager == "pdm":
        return (repo_dir / "pdm.lock").exists()
    if package_manager == "uv":
        return (repo_dir / "uv.lock").exists()
    if package_manager == "pipenv":
        return (repo_dir / "Pipfile.lock").exists()
    if package_manager == "pip":
        return (repo_dir / "requirements.txt").exists()
    return False


def install_command(package_manager: str, frozen_lock: bool, repo_dir: Path | None = None) -> list[str]:
    py = effective_python_executable(repo_dir) if repo_dir is not None else python_executable()

    if package_manager == "poetry":
        base = ["poetry", "install", "--no-interaction", "--no-root"]
        if frozen_lock:
            base.append("--sync")
        return base

    if package_manager == "pipenv":
        if frozen_lock:
            return ["pipenv", "install", "--deploy", "--dev"]
        return ["pipenv", "install", "--dev"]

    if package_manager == "uv":
        if frozen_lock:
            return ["uv", "sync", "--frozen"]
        return ["uv", "sync"]

    if package_manager == "pdm":
        if frozen_lock:
            return ["pdm", "install", "--frozen-lockfile"]
        return ["pdm", "install"]

    if package_manager == "hatch":
        return ["hatch", "env", "create"]

    # pip: prefer requirements.txt, then editable install from pyproject/setup.py
    if repo_dir is not None:
        if (repo_dir / "requirements.txt").exists():
            return [py, "-m", "pip", "install", "-r", "requirements.txt"]
        if has_pyproject(repo_dir) or (repo_dir / "setup.py").exists():
            return [py, "-m", "pip", "install", "."]
    return [py, "-m", "pip", "install", "-r", "requirements.txt"]


def build_command(package_manager: str, repo_dir: Path | None = None) -> list[str]:
    py = effective_python_executable(repo_dir) if repo_dir is not None else python_executable()

    if package_manager == "poetry":
        return ["poetry", "build"]
    if package_manager == "uv":
        return ["uv", "build"]
    if package_manager == "pdm":
        return ["pdm", "build"]
    if package_manager == "hatch":
        return ["hatch", "build"]
    # pip / pipenv / fallback: use PEP 517 build front-end
    return [py, "-m", "build"]


def run_in_env_command(package_manager: str, args: list[str]) -> list[str]:
    if package_manager == "poetry":
        return ["poetry", "run", *args]
    if package_manager == "pipenv":
        return ["pipenv", "run", *args]
    if package_manager == "uv":
        return ["uv", "run", *args]
    if package_manager == "pdm":
        return ["pdm", "run", *args]
    if package_manager == "hatch":
        return ["hatch", "run", *args]
    return args


def test_command(package_manager: str, repo_dir: Path | None = None) -> list[str]:
    py = effective_python_executable(repo_dir) if repo_dir is not None else python_executable()
    return run_in_env_command(package_manager, [py, "-m", "pytest"])


def bootstrap_via_pip_command(package_manager: str) -> list[str]:
    """Best-effort command to install a Python package manager via pip."""
    py = python_executable()
    return [py, "-m", "pip", "install", "--user", package_manager]


TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
_TEST_DIR_NAMES = {"tests", "test"}
_IGNORED_DIRS = {
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
    "node_modules",
    ".eggs",
    "site-packages",
    ".cache",
}


def has_test_files(repo_dir: Path) -> bool:
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]

        for dir_name in dirs:
            if dir_name in _TEST_DIR_NAMES:
                tests_path = Path(root) / dir_name
                for _, _, test_files in os.walk(tests_path):
                    if any(fname.endswith(".py") for fname in test_files):
                        return True

        for file_name in files:
            if any(fnmatch.fnmatch(file_name, pattern) for pattern in TEST_FILE_PATTERNS):
                return True

    return False


def find_test_directories(repo_dir: Path, max_depth: int = 4) -> list[Path]:
    """Return all ``test/`` and ``tests/`` directories under ``repo_dir``.

    Performs a bounded BFS so that monorepo layouts (``backend/tests``,
    ``src/tests``) and plural/singular variants (``test/`` vs ``tests/``)
    are both discovered. Ignored dirs (.venv, node_modules, etc.) are
    skipped and nested test dirs are not re-entered.
    """
    found: list[Path] = []
    queue: list[tuple[Path, int]] = [(repo_dir, 0)]
    while queue:
        current, depth = queue.pop(0)
        if depth >= max_depth:
            continue
        try:
            children = sorted(current.iterdir())
        except (OSError, PermissionError):
            continue
        for child in children:
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in _IGNORED_DIRS:
                continue
            if child.name in _TEST_DIR_NAMES:
                found.append(child)
                continue
            queue.append((child, depth + 1))
    return found


def has_collectible_tests(repo_dir: Path) -> bool:
    """Like :func:`has_test_files` but only returns True when there is at
    least one file matching pytest's naming conventions. Empty scaffold
    packages (``tests/__init__.py`` only) are treated as empty."""
    candidates: list[Path] = [repo_dir, *find_test_directories(repo_dir)]
    seen: set[Path] = set()
    for base in candidates:
        resolved = base.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in _IGNORED_DIRS]
            for file_name in files:
                if any(fnmatch.fnmatch(file_name, pattern) for pattern in TEST_FILE_PATTERNS):
                    return True
    return False


def strip_engine_managed_requirements(repo_dir: Path) -> list[str]:
    """Comment out engine-managed tools from ``requirements.txt``.

    Returns the list of package names that were neutralised. Lines matching
    packages in :data:`ENGINE_MANAGED_PYTHON_PACKAGES` are prefixed with
    ``# [engine-managed]`` instead of being deleted so diagnostics and
    future re-syncs can still see what was removed. Comments, blank lines
    and ``-r``/``-c`` include directives are preserved untouched.
    """
    req_file = repo_dir / "requirements.txt"
    if not req_file.exists():
        return []
    try:
        content = req_file.read_text(encoding="utf-8")
    except OSError:
        return []

    removed: list[str] = []
    new_lines: list[str] = []
    for raw_line in content.splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("-"):
            new_lines.append(raw_line)
            continue
        pkg_name = re.split(r"[\s<>=!~;\[]", stripped, maxsplit=1)[0].strip().lower()
        if pkg_name in ENGINE_MANAGED_PYTHON_PACKAGES:
            removed.append(pkg_name)
            new_lines.append(f"# [engine-managed] {raw_line}")
            continue
        new_lines.append(raw_line)

    if removed:
        req_file.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    return removed


def has_pytest_configured(repo_dir: Path) -> bool:
    if (repo_dir / "pytest.ini").exists() or (repo_dir / "tox.ini").exists():
        return True
    data = read_pyproject(repo_dir)
    tool = data.get("tool") if isinstance(data, dict) else None
    if isinstance(tool, dict) and "pytest" in tool:
        return True
    return False


# ---------------------------------------------------------------------------
# ASGI entry point auto-detection
# ---------------------------------------------------------------------------

_ASGI_CLASS_NAMES = {"FastAPI", "Starlette", "Sanic", "Quart", "Litestar"}
_ENTRY_IGNORED_DIR_NAMES = _IGNORED_DIRS | {
    "tests",
    "test",
    "__pycache__",
    "migrations",
    "alembic",
    "scripts",
    "docs",
    "examples",
}


@dataclass
class AsgiEntryPoint:
    """Describe how to launch an ASGI application with uvicorn.

    Attributes:
        module: Dotted Python module path (e.g. ``secure_app.api``).
        attr:   The attribute on that module. Either a module-level
                variable holding an app instance or a factory function
                that returns one.
        is_factory: ``True`` when ``attr`` is a callable (factory) that
                must be invoked to produce the app. Signalled to
                uvicorn via ``--factory``.
        required_kwargs: Names of keyword-only (or positional-without-default)
                parameters the factory requires. Empty when ``is_factory``
                is False or the factory takes no required arguments. The
                build step uses this to decide whether a wrapper module
                needs to be generated.
        app_dir: Directory relative to the project root that should be
                passed to ``uvicorn --app-dir``. ``"."`` for repos where
                the package lives at the project root, ``"src"`` for
                ``src``-layout projects.
        file_path: Relative path of the source file the entry point was
                detected in, for logging only.
    """

    module: str
    attr: str
    is_factory: bool
    app_dir: str
    file_path: str
    required_kwargs: list[str] = dataclasses_field(default_factory=list)


def _detect_src_layout(project_root: Path) -> str:
    """Return ``"src"`` for projects whose Python packages live under
    ``src/`` (PEP 518 src-layout), otherwise ``"."``.

    Checks ``pyproject.toml`` first (setuptools / hatchling / poetry
    variants), then falls back to a filesystem heuristic: if
    ``src/<something>/__init__.py`` exists, assume src-layout.
    """
    data = read_pyproject(project_root)
    if isinstance(data, dict):
        tool = data.get("tool") if isinstance(data.get("tool"), dict) else None
        if isinstance(tool, dict):
            setuptools_cfg = tool.get("setuptools") if isinstance(tool.get("setuptools"), dict) else None
            if isinstance(setuptools_cfg, dict):
                pkg_dir = setuptools_cfg.get("package-dir")
                if isinstance(pkg_dir, dict) and pkg_dir.get("") == "src":
                    return "src"
                find_cfg = setuptools_cfg.get("packages")
                if isinstance(find_cfg, dict):
                    nested = find_cfg.get("find")
                    if isinstance(nested, dict) and nested.get("where") == ["src"]:
                        return "src"

    src_dir = project_root / "src"
    if src_dir.is_dir():
        try:
            for child in src_dir.iterdir():
                if child.is_dir() and (child / "__init__.py").exists():
                    return "src"
        except OSError:
            pass
    return "."


def _iter_python_source_files(root: Path):
    """Yield ``.py`` files under ``root`` that are plausible application
    source files (excluding tests, venvs, build outputs, etc)."""
    if not root.is_dir():
        return
    for path in root.rglob("*.py"):
        try:
            rel = path.relative_to(root)
        except ValueError:
            continue
        # Skip hidden / ignored directories anywhere in the relative path
        parents = rel.parts[:-1]
        if any(part in _ENTRY_IGNORED_DIR_NAMES or part.startswith(".") for part in parents):
            continue
        yield path


def _file_to_module_path(py_file: Path, search_root: Path) -> str:
    try:
        rel = py_file.relative_to(search_root)
    except ValueError:
        return ""
    parts = list(rel.parts)
    if not parts:
        return ""
    last = parts[-1]
    if last == "__init__.py":
        parts.pop()
    elif last.endswith(".py"):
        parts[-1] = last[:-3]
    else:
        return ""
    if not parts or not all(p.isidentifier() for p in parts):
        return ""
    return ".".join(parts)


def _call_name(call: ast.Call) -> str:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _function_returns_asgi(func: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Heuristic: if the function body contains any ``FastAPI()``-style
    call (directly or in an assignment), treat it as an app factory."""
    for node in ast.walk(func):
        if isinstance(node, ast.Call) and _call_name(node) in _ASGI_CLASS_NAMES:
            return True
    return False


def _parse_source(py_file: Path) -> tuple[str, ast.Module] | None:
    try:
        source = py_file.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    if not any(name in source for name in _ASGI_CLASS_NAMES):
        return None
    try:
        tree = ast.parse(source, filename=str(py_file))
    except (SyntaxError, ValueError):
        return None
    return source, tree


def _scan_module_level_app(
    py_file: Path, search_root: Path, app_dir: str, project_root: Path
) -> AsgiEntryPoint | None:
    parsed = _parse_source(py_file)
    if parsed is None:
        return None
    _, tree = parsed
    module_path = _file_to_module_path(py_file, search_root)
    if not module_path:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            if _call_name(node.value) in _ASGI_CLASS_NAMES:
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        return AsgiEntryPoint(
                            module=module_path,
                            attr=target.id,
                            is_factory=False,
                            app_dir=app_dir,
                            file_path=str(py_file.relative_to(project_root)),
                        )
    return None


def _required_factory_args(func: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    """Return the names of parameters that *must* be supplied when
    calling this function.

    Includes:
        - positional parameters without defaults
        - keyword-only parameters without defaults

    Excludes:
        - ``self`` / ``cls``
        - ``*args`` / ``**kwargs``
    """
    required: list[str] = []
    args_obj = func.args

    positional = list(args_obj.posonlyargs) + list(args_obj.args)
    defaults = list(args_obj.defaults)
    # `defaults` align with the TAIL of `positional`
    num_without_default = len(positional) - len(defaults)
    for idx, arg in enumerate(positional):
        if arg.arg in {"self", "cls"}:
            continue
        if idx < num_without_default:
            required.append(arg.arg)

    for arg, default in zip(args_obj.kwonlyargs, args_obj.kw_defaults):
        if default is None:
            required.append(arg.arg)

    return required


def _scan_factory(
    py_file: Path, search_root: Path, app_dir: str, project_root: Path
) -> AsgiEntryPoint | None:
    parsed = _parse_source(py_file)
    if parsed is None:
        return None
    _, tree = parsed
    module_path = _file_to_module_path(py_file, search_root)
    if not module_path:
        return None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _function_returns_asgi(node):
                return AsgiEntryPoint(
                    module=module_path,
                    attr=node.name,
                    is_factory=True,
                    app_dir=app_dir,
                    file_path=str(py_file.relative_to(project_root)),
                    required_kwargs=_required_factory_args(node),
                )
    return None


def find_asgi_entry_point(project_root: Path) -> AsgiEntryPoint | None:
    """Locate an ASGI application entry point by parsing Python sources.

    Detection strategy (in order of preference):
        1. Top-level assignment ``app = FastAPI(...)`` (or Starlette,
           Sanic, Quart, Litestar) at module scope.
        2. Factory function whose body instantiates one of those
           classes. Returned with ``is_factory=True`` so callers know
           to pass ``--factory`` to uvicorn.

    Supports src-layout (``package-dir = { "" = "src" }`` or
    ``src/<pkg>/__init__.py``). Skips tests, virtualenvs, build
    outputs, migrations and other non-application directories.

    Returns ``None`` when no ASGI app is found — the caller can then
    decide whether to treat the repo as a non-service project or fall
    back to a heuristic candidate list.
    """
    app_dir = _detect_src_layout(project_root)
    search_root = project_root / app_dir if app_dir != "." else project_root

    # Pass 1: prefer an explicit module-level app instance
    for py_file in _iter_python_source_files(search_root):
        match = _scan_module_level_app(py_file, search_root, app_dir, project_root)
        if match is not None:
            return match

    # Pass 2: fall back to factory functions
    for py_file in _iter_python_source_files(search_root):
        match = _scan_factory(py_file, search_root, app_dir, project_root)
        if match is not None:
            return match

    return None


# ---------------------------------------------------------------------------
# Wrapper module generation for factories that require arguments
# ---------------------------------------------------------------------------

# Parameter-name heuristics for auto-injecting default values into factory
# calls. Path-like arguments get a runtime state directory, config-like
# arguments get ``None``. Any other required argument cannot be guessed
# safely, so wrapper generation is refused in that case.
_PATH_ARG_HINTS = frozenset(
    {
        "data_dir",
        "base_dir",
        "root_dir",
        "working_dir",
        "workdir",
        "datadir",
        "db_dir",
        "storage_dir",
        "state_dir",
        "cache_dir",
        "upload_dir",
        "media_dir",
        "static_dir",
        "log_dir",
        "logs_dir",
    }
)
_OPTIONAL_CONFIG_HINTS = frozenset(
    {"config", "settings", "options", "cfg", "config_path", "config_file"}
)


@dataclass
class FactoryWrapperPlan:
    """Plan for synthesising a wrapper module around an ASGI factory.

    The wrapper calls ``<original.module>.<original.attr>(**injected_kwargs)``
    and exposes the result as a module-level ``app`` variable, which uvicorn
    can then load without the ``--factory`` flag.
    """

    original: AsgiEntryPoint
    injected_kwargs: dict[str, str]  # kwarg name -> python source expression
    needs_state_dir: bool


def plan_entry_wrapper(entry: AsgiEntryPoint) -> FactoryWrapperPlan | None:
    """Decide whether a factory can be wrapped automatically.

    Returns a :class:`FactoryWrapperPlan` when every required factory
    argument can be matched to a safe default (via name-based hints),
    otherwise ``None``.
    """
    if not entry.is_factory or not entry.required_kwargs:
        return None

    injected: dict[str, str] = {}
    needs_state_dir = False
    for arg_name in entry.required_kwargs:
        lowered = arg_name.lower()
        if lowered in _PATH_ARG_HINTS:
            injected[arg_name] = "_LOCALCI_STATE_DIR"
            needs_state_dir = True
            continue
        if lowered in _OPTIONAL_CONFIG_HINTS:
            injected[arg_name] = "None"
            continue
        # Unknown argument — do not guess.
        return None

    return FactoryWrapperPlan(
        original=entry,
        injected_kwargs=injected,
        needs_state_dir=needs_state_dir,
    )


def render_wrapper_module(plan: FactoryWrapperPlan) -> str:
    """Render the Python source for an auto-generated wrapper module."""
    header = (
        '"""Auto-generated ASGI entry wrapper.\n\n'
        "Generated by the CI engine because the original factory\n"
        f"`{plan.original.module}.{plan.original.attr}` requires arguments\n"
        "that uvicorn's --factory flag cannot supply directly. Defaults are\n"
        "injected based on parameter-name heuristics.\n\n"
        'Do not edit; this file is regenerated on every build."""\n'
    )
    imports = ["from __future__ import annotations", ""]
    if plan.needs_state_dir:
        imports += ["from pathlib import Path", ""]
    imports.append(f"from {plan.original.module} import {plan.original.attr}")

    state_block: list[str] = []
    if plan.needs_state_dir:
        state_block = [
            "",
            "_LOCALCI_STATE_DIR = Path(__file__).resolve().parent / \".localci-runtime\"",
            "_LOCALCI_STATE_DIR.mkdir(parents=True, exist_ok=True)",
        ]

    kwarg_lines = ",\n    ".join(
        f"{name}={expression}" for name, expression in plan.injected_kwargs.items()
    )
    call_block = [
        "",
        f"app = {plan.original.attr}(",
        f"    {kwarg_lines},",
        ")",
        "",
    ]

    return "\n".join([header, *imports, *state_block, *call_block])


WRAPPER_MODULE_BASENAME = "_localci_entry"


def write_entry_wrapper(project_root: Path, plan: FactoryWrapperPlan) -> AsgiEntryPoint:
    """Write the wrapper module into the right spot of the project and
    return a new :class:`AsgiEntryPoint` pointing at it.

    The wrapper is placed next to the original source file under the
    same ``app_dir`` so its import path stays at the module root.
    """
    app_dir = plan.original.app_dir
    target_dir = project_root / app_dir if app_dir != "." else project_root
    target_dir.mkdir(parents=True, exist_ok=True)
    wrapper_path = target_dir / f"{WRAPPER_MODULE_BASENAME}.py"
    wrapper_path.write_text(render_wrapper_module(plan), encoding="utf-8")

    return AsgiEntryPoint(
        module=WRAPPER_MODULE_BASENAME,
        attr="app",
        is_factory=False,
        app_dir=app_dir,
        file_path=str(wrapper_path.relative_to(project_root)),
        required_kwargs=[],
    )
