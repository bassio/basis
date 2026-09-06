"""Import-free discovery of plugin CLI command groups.

The CLI must build its dispatch tree without importing plugin code (importing a
plugin package pulls FastAPI/SQLModel via ``BasisPlugin`` — measured ~400 ms).
This module reads only package metadata (``importlib.metadata``) and the
filesystem, and hands back ``(group_name, help_line, load)`` triples whose
``load`` performs the real (heavy) import on first use (see
:mod:`basis.cli.lazy`).

Convention: a plugin ships its CLI commands in a ``cli/`` subpackage exposing a
module-level ``cli`` that is a ``typer.Typer``. The CLI mounts it as
``basis <plugin-name> <subcommand>``. A plugin without a ``cli/`` costs literally
nothing at discovery.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path

import click

from basis.cli.lazy import import_plugin_cli

#: CLI groups the framework owns outright — plugin groups may not shadow them.
RESERVED_CLI_GROUPS = frozenset({"dev", "init", "bench", "plugin", "version"})

#: A plugin's ``cli/__init__.py`` may declare a module-level ``help = "…"``
#: string as its one-line description. Discovery reads it from *source* (never
#: imports), so ``basis --help`` shows the plugin's real description import-free.
#: Absent → the caller falls back to a generic ``"{name} commands"`` line.
_CLI_HELP_RE = re.compile(
    r'^\s*help\s*=\s*(["\'])(?P<help>.*?)\1\s*(?:#.*)?$',
    re.MULTILINE,
)


def _cli_module_of(ep) -> str | None:
    """The dotted ``<pkg>.cli`` module path for an entry point, if it exists.

    Import-free: checked against the distribution's RECORD / on-disk location /
    ``sys.path`` (covers editable installs, whose RECORD does not list package
    files). ``None`` when the plugin has no ``cli/``.
    """
    module = getattr(ep, "module", None)
    if not module:
        return None
    candidates = {f"{module}.cli"}
    if "." in module:
        candidates.add(f"{module.rsplit('.', 1)[0]}.cli")
    for cand in candidates:
        if _cli_module_exists(ep, cand):
            return cand
    return None


def _cli_module_exists(ep, cli_module: str) -> bool:
    """Does ``<cli_module>`` exist on disk/installed — without importing anything?"""
    targets = {f"{cli_module.replace('.', '/')}/__init__.py", f"{cli_module.replace('.', '/')}.py"}

    dist = getattr(ep, "dist", None)
    if dist is not None:
        # 1) RECORD metadata (normal wheel installs)
        if any(str(f) in targets for f in (dist.files or ())):
            return True
        # 2) on-disk resolution via the distribution location
        base = dist.locate_file(cli_module.replace(".", "/"))
        if (base / "__init__.py").exists() or Path(f"{base}.py").exists():
            return True

    # 3) sys.path scan — editable .pth installs add a source dir to sys.path but
    #    don't record package files in RECORD.
    for base in sys.path:
        d = Path(base)
        for part in cli_module.split("."):
            d = d / part
        if (d / "__init__.py").exists() or Path(f"{d}.py").exists():
            return True
    return False


def _cli_module_path(ep, cli_module: str) -> Path | None:
    """Resolve ``<cli_module>`` to its on-disk ``__init__.py``/``.py`` file — no imports.

    ``None`` when the module can't be located on disk (e.g. RECORD lists a
    ``cli/`` that isn't actually installed). Used only to read the plugin's
    one-line help from source; presence is still decided by
    :func:`_cli_module_exists` (RECORD-presence counts).
    """
    pkg_dir = cli_module.replace(".", "/")
    targets = {f"{pkg_dir}/__init__.py", f"{pkg_dir}.py"}

    dist = getattr(ep, "dist", None)
    if dist is not None:
        for f in dist.files or ():
            if str(f) in targets:
                p = dist.locate_file(str(f))
                if p.exists():
                    return p
        base = dist.locate_file(pkg_dir)
        for cand in (base / "__init__.py", Path(f"{base}.py")):
            if cand.exists():
                return cand

    for base in sys.path:
        d = Path(base)
        for part in cli_module.split("."):
            d = d / part
        for cand in (d / "__init__.py", Path(f"{d}.py")):
            if cand.exists():
                return cand
    return None


def _cli_help_line(path: Path | None) -> str | None:
    """Import-free one-line help from a plugin's ``cli/__init__.py``.

    Reads the module-level ``help = "…"`` constant straight from source — no
    import, no command scanning. ``None`` when there is none (or the file can't
    be read); callers fall back to a generic line.
    """
    if path is None:
        return None
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    match = _CLI_HELP_RE.search(text)
    return match.group("help").strip() if match else None


def discover_installed_plugin_group_loaders() -> list[tuple[str, str, Callable[[], click.Command]]]:
    """Cli-bearing installed plugins: ``(group_name, help_line, load)`` — no imports."""
    loaders = []
    try:
        eps = entry_points(group="basis.plugins")
    except Exception:
        return loaders
    for ep in eps:
        name = getattr(ep, "name", "") or ""
        if not name.isidentifier() or name in RESERVED_CLI_GROUPS:
            continue
        cli_module = _cli_module_of(ep)
        if cli_module is None:
            continue
        dist_name = ep.dist.metadata["Name"] if ep.dist else name
        help_line = _cli_help_line(_cli_module_path(ep, cli_module)) or f"{dist_name} commands"
        loaders.append(
            (name, help_line, lambda module=cli_module: import_plugin_cli(module))
        )
    return loaders


def _resolve_canonical_package(path: Path) -> str | None:
    """Top-level dotted package name for *path* (walks up while ``__init__.py`` exists)."""
    parts = []
    current = path.resolve()
    while (current / "__init__.py").exists():
        parts.append(current.name)
        current = current.parent
    if not parts:
        return None
    parts.reverse()
    return ".".join(parts)


def _find_plugins_dir(project_dir: Path) -> Path | None:
    """Locate the app's ``plugins/`` directory (src or flat layout) — no imports."""
    from basis.cli.utils import find_basis_app

    try:
        import_path, _ = find_basis_app(None, cwd=project_dir, quiet=True)
    except Exception:
        return None
    module_name = import_path.split(":")[0]
    src_candidate = project_dir / "src" / module_name.replace(".", "/") / "plugins"
    if src_candidate.is_dir():
        return src_candidate
    flat = project_dir / module_name.replace(".", "/") / "plugins"
    return flat if flat.is_dir() else None


def discover_local_plugin_group_loaders(
    project_dir: Path | None = None,
) -> list[tuple[str, str, Callable[[], click.Command]]]:
    """Cli-bearing local ``plugins/`` plugins — filesystem scan, no imports.

    Local plugins are project-scoped: they only contribute when the cwd resolves
    to a Basis project (``basis dev``'s app detection).
    """
    from basis.cli.utils import resolve_project_dir

    project_dir = resolve_project_dir(project_dir)
    plugins_dir = _find_plugins_dir(project_dir)
    if plugins_dir is None:
        return []
    canonical = _resolve_canonical_package(plugins_dir)
    if not canonical:
        return []
    loaders = []
    for item in sorted(plugins_dir.iterdir()):
        if not item.is_dir() or item.name.startswith("_") or item.name in RESERVED_CLI_GROUPS:
            continue
        if not (item / "__init__.py").exists():
            continue
        if not (item / "cli" / "__init__.py").exists():
            continue
        cli_module = f"{canonical}.{item.name}.cli"
        help_line = _cli_help_line(item / "cli" / "__init__.py") or f"{item.name} commands"
        loaders.append(
            (item.name, help_line, lambda module=cli_module: import_plugin_cli(module))
        )
    return loaders


def discover_plugin_group_loaders(
    project_dir: Path | None = None,
) -> list[tuple[str, str, Callable[[], click.Command]]]:
    """Installed (global) + local (project) plugin command groups — no plugin imports."""
    return discover_installed_plugin_group_loaders() + discover_local_plugin_group_loaders(project_dir)
