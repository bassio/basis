"""
Shared utilities for the Basis CLI.

Provides app-detection logic, project structure resolution, and console helpers.
"""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

from rich.console import Console

console = Console()


def find_basis_app(app_path: str | None = None, cwd: Path | None = None) -> tuple[str, Path]:
    """
    Locate the Basis application module.

    Resolution order
    ----------------
    1. Explicit ``app_path`` argument (e.g. ``"myapp:app"`` or ``"myapp"``).
    2. Scan the current directory for common conventions.

    Returns
    -------
    tuple[str, Path]
        ``(import_path, project_dir)`` — the ``import_path`` is suitable for
        ``uvicorn`` (e.g. ``"jotter:app"``), and ``project_dir`` is the
        directory containing the package.

    Raises
    ------
    typer.Exit
        If no Basis app can be found.
    """
    import typer

    cwd = (cwd or Path.cwd()).resolve()

    if app_path:
        # User provided explicit path — validate it
        module_part = app_path.split(":")[0]
        return app_path, cwd

    # Strategy: scan for common patterns
    # 1. Check pyproject.toml for a [project.scripts] entry that references a Basis app
    pyproject = cwd / "pyproject.toml"
    if pyproject.exists():
        detected = _detect_from_pyproject(pyproject, cwd)
        if detected:
            return detected

    # 2. Check for src/<package>/__init__.py containing Basis()
    src_dir = cwd / "src"
    if src_dir.is_dir():
        for pkg_dir in sorted(src_dir.iterdir()):
            if pkg_dir.is_dir() and (pkg_dir / "__init__.py").exists():
                init_file = pkg_dir / "__init__.py"
                var_name = _find_basis_instance_in_file(init_file)
                if var_name:
                    return f"{pkg_dir.name}:{var_name}", cwd

    # 3. Check for app.py / main.py in cwd
    for candidate in ["app.py", "main.py"]:
        candidate_path = cwd / candidate
        if candidate_path.exists():
            var_name = _find_basis_instance_in_file(candidate_path)
            if var_name:
                stem = candidate_path.stem
                return f"{stem}:{var_name}", cwd

    # 4. Check for __init__.py in cwd
    init_file = cwd / "__init__.py"
    if init_file.exists():
        var_name = _find_basis_instance_in_file(init_file)
        if var_name:
            return f"{cwd.name}:{var_name}", cwd.parent

    console.print(
        "[bold red]Error:[/] Could not find a Basis app.\n"
        "Try one of:\n"
        "  • [cyan]basis dev myapp:app[/cyan]\n"
        "  • Run from a directory containing a Basis project\n"
    )
    raise typer.Exit(code=1)


def _detect_from_pyproject(pyproject: Path, cwd: Path) -> tuple[str, Path] | None:
    """
    Parse ``pyproject.toml`` to detect the project name, then look for
    a Basis() instance in ``src/<name>/__init__.py``.
    """
    try:
        # Use tomllib (stdlib in 3.11+)
        import tomllib
        with open(pyproject, "rb") as f:
            data = tomllib.load(f)
    except Exception:
        return None

    project_name = data.get("project", {}).get("name", "").replace("-", "_")
    if not project_name:
        return None

    # Check src/<project_name>/__init__.py
    src_init = cwd / "src" / project_name / "__init__.py"
    if src_init.exists():
        var_name = _find_basis_instance_in_file(src_init)
        if var_name:
            return f"{project_name}:{var_name}", cwd


def _find_basis_instance_in_file(filepath: Path) -> str | None:
    """
    Parse a Python file's AST and find a module-level variable assigned to
    ``Basis()``.  Returns the variable name (e.g. ``"app"``) or ``None``.
    """
    try:
        source = filepath.read_text()
        tree = ast.parse(source)
    except Exception:
        return None

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            # Look for: <name> = Basis(...)
            for target in node.targets:
                if isinstance(target, ast.Name) and isinstance(node.value, ast.Call):
                    func = node.value.func
                    # Direct: Basis()
                    if isinstance(func, ast.Name) and func.id == "Basis":
                        return target.id
                    # Qualified: basis.server.app.Basis() or Basis(...)
                    if isinstance(func, ast.Attribute) and func.attr == "Basis":
                        return target.id
    return None


def resolve_project_dir(cwd: Path | None = None) -> Path:
    """Return the project root (directory containing ``pyproject.toml``)."""
    cwd = (cwd or Path.cwd()).resolve()
    check = cwd
    while check != check.parent:
        if (check / "pyproject.toml").exists():
            return check
        check = check.parent
    return cwd
