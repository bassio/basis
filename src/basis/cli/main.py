"""
Basis CLI — the developer command-line interface for the Basis framework.

Entry point:  ``basis`` (registered via ``[project.scripts]`` in pyproject.toml).

Usage::

    basis dev              # Start dev server with HMR
    basis init my-app      # Scaffold a new project
    basis plugin list      # Show discovered plugins
    basis theme list       # Theme commands — contributed by the theme plugin

Plugin command groups are mounted **lazily** (see ``basis.cli.lazy``): the
dispatch tree is built from import-free metadata, and a plugin's ``cli/``
module is imported only when one of its commands is actually requested.
"""

from __future__ import annotations

import typer
from rich.console import Console
from typer.main import get_command as _typer_to_click

from basis.cli.commands import dev as dev_cmd
import basis.cli.commands.init as init_cmd
from basis.cli.commands import plugin as plugin_cmd
from basis.cli.commands import bench as bench_cmd
from basis.cli.discovery import discover_plugin_group_loaders
from basis.cli.lazy import LazyGroup

console = Console()

app = typer.Typer(
    name="basis",
    help="🧱 Basis — the full-stack Python reactive web framework.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)

# Register sub-commands / command groups
app.command(name="dev", help="Start the development server with HMR.")(dev_cmd.dev)
app.command(name="init", help="Scaffold a new Basis project.")(init_cmd.init)
app.command(
    name="bench",
    help="Run the Basis benchmark suite (median + p95).",
)(bench_cmd.bench)
app.add_typer(plugin_cmd.plugin_app, name="plugin", help="Manage Basis plugins.")


def version_callback(value: bool):
    if value:
        from importlib.metadata import version as pkg_version

        try:
            ver = pkg_version("basis-framework")
        except Exception:
            ver = "0.1.0 (dev)"
        console.print(f"[bold green]basis-framework[/] {ver}")
        raise typer.Exit()


@app.callback()
def _cli_callback(
    version: bool = typer.Option(
        False,
        "--version",
        "-v",
        help="Show version and exit.",
        callback=version_callback,
        is_eager=True,
    ),
):
    """
    🧱 [bold]Basis[/bold] — the full-stack Python reactive web framework CLI.
    """
    pass


def build_root():
    """The CLI dispatch tree: builtin groups + lazy plugin command groups.

    ``typer.main.get_command(app)`` materializes the builtin Click group;
    plugin groups are added as ``LazyGroup`` stubs built from import-free
    metadata, so building the tree imports no plugin code.
    """
    root = _typer_to_click(app)
    seen = set(root.commands)
    for name, help_line, load in discover_plugin_group_loaders():
        if name in seen:
            console.print(f"[yellow]⚠️  skipping plugin command group '{name}' (duplicate)[/]")
            continue
        root.add_command(LazyGroup(name=name, help=help_line, load=load))
        seen.add(name)
    return root


def main():
    """Console entry point (``[project.scripts] basis = "basis.cli.main:main"``)."""
    build_root()()
