"""
``basis plugin`` — Plugin lifecycle management commands.

Sub-commands::

    basis plugin list    — Show all discovered plugins (local + installed)
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table
from rich import box

from basis.cli.utils import find_basis_app, resolve_project_dir

console = Console()

plugin_app = typer.Typer(
    name="plugin",
    help="🔌 Manage Basis plugins.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@plugin_app.command("list")
def plugin_list(
    app_path: str = typer.Option(
        None,
        "--app",
        "-a",
        help="App import path (e.g. 'myapp:app'). Auto-detected if omitted.",
    ),
):
    """
    Show all discovered plugins — local (from ``plugins/`` directory) and
    installed (from Python ``entry_points``).
    """
    from basis.server.app import discover_local_plugins, discover_installed_plugins

    project_dir = resolve_project_dir()
    import_path, _ = find_basis_app(app_path, cwd=project_dir)

    module_name = import_path.split(":")[0]

    # Discover local plugins
    local_plugins = []
    src_dir = project_dir / "src"
    package_dir = src_dir / module_name.replace(".", "/")
    if package_dir.is_dir():
        local_plugins = discover_local_plugins(package_dir, "plugins")
    elif (project_dir / module_name.replace(".", "/")).is_dir():
        local_plugins = discover_local_plugins(
            project_dir / module_name.replace(".", "/"), "plugins"
        )

    # Discover installed plugins
    installed_plugins = discover_installed_plugins()

    if not local_plugins and not installed_plugins:
        console.print("\n[dim]No plugins discovered.[/]\n")
        console.print(
            "  [cyan]•[/] Place plugin files in your [bold]plugins/[/] directory\n"
            "  [cyan]•[/] Or install a plugin package: [bold]pip install basis-plugin-*[/]\n"
        )
        return

    console.print()

    if local_plugins:
        table = Table(
            title="🔌 Local Plugins (plugins/)",
            box=box.ROUNDED,
            title_style="bold white",
            border_style="bright_blue",
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("Name", style="bold white", min_width=12)
        table.add_column("Prefix", style="green", min_width=15)
        table.add_column("Source", style="dim", min_width=20)
        table.add_column("Actions", style="yellow", justify="right")

        for p in local_plugins:
            action_count = str(len(getattr(p, "actions", {})))
            source = f"plugins/{p.name}.py"
            table.add_row(p.name, p.prefix, source, action_count)

        console.print(table)

    if installed_plugins:
        if local_plugins:
            console.print()

        table = Table(
            title="📦 Installed Plugins (entry_points)",
            box=box.ROUNDED,
            title_style="bold white",
            border_style="bright_blue",
            header_style="bold cyan",
            show_lines=True,
        )
        table.add_column("Name", style="bold white", min_width=12)
        table.add_column("Prefix", style="green", min_width=15)
        table.add_column("Package", style="dim", min_width=20)
        table.add_column("Actions", style="yellow", justify="right")

        for p in installed_plugins:
            action_count = str(len(getattr(p, "actions", {})))
            table.add_row(p.name, p.prefix, "—", action_count)

        console.print(table)

    # Summary
    total = len(local_plugins) + len(installed_plugins)
    console.print(
        f"\n  [bold]{total}[/] plugin{'s' if total != 1 else ''} discovered "
        f"([cyan]{len(local_plugins)}[/] local, [cyan]{len(installed_plugins)}[/] installed)\n"
    )
