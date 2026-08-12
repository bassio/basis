"""
Basis CLI — the developer command-line interface for the Basis framework.

Entry point:  ``basis`` (registered via ``[project.scripts]`` in pyproject.toml).

Usage::

    basis dev              # Start dev server with HMR
    basis init my-app      # Scaffold a new project
    basis plugin list      # Show discovered plugins
"""

from __future__ import annotations

import typer
from rich.console import Console

from basis.cli.commands import dev as dev_cmd
from basis.cli.commands import init_cmd
from basis.cli.commands import plugin as plugin_cmd

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
def main(
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
