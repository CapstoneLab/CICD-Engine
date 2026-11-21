from __future__ import annotations

import fnmatch
import json
import os
import shutil
from pathlib import Path


SUPPORTED_PACKAGE_MANAGERS = {"npm", "yarn", "pnpm"}

# Packages that are provided and invoked by the engine itself, so they
# must NOT be re-installed as project dependencies.
ENGINE_MANAGED_NODE_PACKAGES = {"semgrep", "gitleaks", "@semgrep/semgrep"}


def strip_engine_managed_dependencies(repo_dir: Path) -> list[str]:
    """Remove engine-managed tools from ``package.json``.

    Scans ``dependencies``, ``devDependencies``, ``optionalDependencies``
    and ``peerDependencies`` for any package in
    :data:`ENGINE_MANAGED_NODE_PACKAGES` (case-insensitive). Returns the
    removed entries as ``"{field}.{pkg}"`` strings. The file is only
    rewritten when something actually changed.
    """
    pkg_file = repo_dir / "package.json"
    if not pkg_file.exists():
        return []
    try:
        data = json.loads(pkg_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, dict):
        return []

    removed: list[str] = []
    for field in ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies"):
        deps = data.get(field)
        if not isinstance(deps, dict):
            continue
        for pkg_name in list(deps.keys()):
            if pkg_name.lower() in ENGINE_MANAGED_NODE_PACKAGES:
                del deps[pkg_name]
                removed.append(f"{field}.{pkg_name}")

    if removed:
        pkg_file.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return removed


def read_package_json(repo_dir: Path) -> dict:
    package_json = repo_dir / "package.json"
    if not package_json.exists():
        return {}

    try:
        return json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def has_script(repo_dir: Path, script_name: str) -> bool:
    package_data = read_package_json(repo_dir)
    scripts = package_data.get("scripts", {})
    return isinstance(scripts, dict) and script_name in scripts


def get_script(repo_dir: Path, script_name: str) -> str | None:
    package_data = read_package_json(repo_dir)
    scripts = package_data.get("scripts", {})
    if not isinstance(scripts, dict):
        return None
    script = scripts.get(script_name)
    return script if isinstance(script, str) else None


def is_placeholder_test_script(script_value: str | None) -> bool:
    if not script_value:
        return True

    value = script_value.lower()
    return "no test specified" in value


def has_test_files(repo_dir: Path) -> bool:
    test_file_patterns = [
        "*.spec.js",
        "*.test.js",
        "*_spec.js",
        "*_test.js",
        "*.spec.ts",
        "*.test.ts",
        "*_spec.ts",
        "*_test.ts",
        "*.spec.jsx",
        "*.test.jsx",
        "*_spec.jsx",
        "*_test.jsx",
        "*.spec.tsx",
        "*.test.tsx",
        "*_spec.tsx",
        "*_test.tsx",
        "*.spec.mjs",
        "*.test.mjs",
        "*_spec.mjs",
        "*_test.mjs",
        "*.spec.cjs",
        "*.test.cjs",
        "*_spec.cjs",
        "*_test.cjs",
    ]
    ignored_dirs = {
        "node_modules",
        ".git",
        "dist",
        "build",
        "coverage",
        ".next",
        "out",
    }

    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in ignored_dirs]

        for file_name in files:
            if any(fnmatch.fnmatch(file_name, pattern) for pattern in test_file_patterns):
                return True

    return False


def npm_executable() -> str:
    return "npm.cmd" if os.name == "nt" else "npm"


def package_manager_executable(package_manager: str) -> str:
    if package_manager == "npm":
        return "npm.cmd" if os.name == "nt" else "npm"
    if package_manager == "yarn":
        return "yarn.cmd" if os.name == "nt" else "yarn"
    if package_manager == "pnpm":
        return "pnpm.cmd" if os.name == "nt" else "pnpm"
    return package_manager


def corepack_executable() -> str:
    return "corepack.cmd" if os.name == "nt" else "corepack"


def is_command_available(command_name: str) -> bool:
    return shutil.which(command_name) is not None


def detect_package_manager(repo_dir: Path) -> str:
    package_data = read_package_json(repo_dir)

    package_manager_field = package_data.get("packageManager")
    if isinstance(package_manager_field, str):
        manager_name = package_manager_field.split("@", 1)[0].strip().lower()
        if manager_name in SUPPORTED_PACKAGE_MANAGERS:
            return manager_name

    if (repo_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (repo_dir / "yarn.lock").exists():
        return "yarn"
    if (repo_dir / "package-lock.json").exists() or (repo_dir / "npm-shrinkwrap.json").exists():
        return "npm"

    return "npm"


def package_manager_prepare_target(repo_dir: Path, package_manager: str) -> str:
    package_data = read_package_json(repo_dir)
    package_manager_field = package_data.get("packageManager")
    if isinstance(package_manager_field, str):
        raw_value = package_manager_field.strip()
        lowered = raw_value.lower()
        if lowered.startswith(f"{package_manager}@") and "@" in raw_value:
            return raw_value

    if package_manager == "yarn":
        yarn_lock = repo_dir / "yarn.lock"
        try:
            lock_header = yarn_lock.read_text(encoding="utf-8", errors="replace")[:4096]
        except OSError:
            lock_header = ""
        if "# yarn lockfile v1" in lock_header:
            return "yarn@1.22.22"

    return f"{package_manager}@stable"


def wrap_with_corepack(command: list[str], package_manager: str) -> list[str]:
    if not command:
        return command
    return [corepack_executable(), package_manager, *command[1:]]


def has_lock_file(repo_dir: Path, package_manager: str) -> bool:
    if package_manager == "npm":
        return (repo_dir / "package-lock.json").exists() or (repo_dir / "npm-shrinkwrap.json").exists()
    if package_manager == "yarn":
        return (repo_dir / "yarn.lock").exists()
    if package_manager == "pnpm":
        return (repo_dir / "pnpm-lock.yaml").exists()
    return False


def install_command(package_manager: str, frozen_lock: bool) -> list[str]:
    exe = package_manager_executable(package_manager)
    if package_manager == "npm":
        if frozen_lock:
            return [exe, "ci", "--no-audit", "--no-fund"]
        return [exe, "install", "--no-audit", "--no-fund"]

    if package_manager == "yarn":
        if frozen_lock:
            return [exe, "install", "--frozen-lockfile"]
        return [exe, "install"]

    if package_manager == "pnpm":
        if frozen_lock:
            return [exe, "install", "--frozen-lockfile"]
        return [exe, "install", "--no-frozen-lockfile"]

    return [exe, "install"]


def run_script_command(package_manager: str, script_name: str) -> list[str]:
    exe = package_manager_executable(package_manager)
    if package_manager == "yarn":
        return [exe, "run", script_name]
    return [exe, "run", script_name]


def test_command(package_manager: str) -> list[str]:
    exe = package_manager_executable(package_manager)
    if package_manager == "yarn":
        return [exe, "test"]
    if package_manager == "pnpm":
        return [exe, "test"]
    return [exe, "test"]
