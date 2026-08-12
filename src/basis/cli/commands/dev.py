"""
``basis dev`` — Start the Basis development server.

Wraps ``uvicorn`` with sensible defaults: auto-detects the app module,
enables reload, and prints a startup banner showing discovered plugins.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich import box

from basis.cli.utils import find_basis_app, resolve_project_dir

console = Console()


def dev(
    app_path: Optional[str] = typer.Argument(
        None,
        help="App import path (e.g. 'myapp:app'). Auto-detected if omitted.",
    ),
    host: str = typer.Option(
        "127.0.0.1",
        "--host",
        "-h",
        help="Bind host.",
    ),
    port: int = typer.Option(
        8000,
        "--port",
        "-p",
        help="Bind port.",
    ),
    reload: bool = typer.Option(
        True,
        "--reload/--no-reload",
        help="Enable auto-reload on file changes.",
    ),
    pyc: bool = typer.Option(
        False,
        "--pyc",
        help="Enable PYC compilation mode for served Python files.",
    ),
):
    """
    Start the Basis development server with hot-module reloading.

    Auto-detects the Basis app in the current project if no app path is given.
    """
    if pyc:
        os.environ["BASIS_PYC_MODE"] = "1"

    project_dir = resolve_project_dir()
    import_path, run_dir = find_basis_app(app_path, cwd=project_dir)

    # Ensure we have the module:attribute format
    if ":" not in import_path:
        import_path = f"{import_path}:app"

    module_part, attr_part = import_path.split(":", 1)

    # Build the startup banner
    _print_banner(import_path, host, port, reload, pyc, project_dir)

    # Discover and display plugins before starting
    _show_plugin_summary(module_part, project_dir)

    # Build uvicorn command
    uvicorn_args = [
        sys.executable, "-m", "uvicorn",
        import_path,
        "--host", host,
        "--port", str(port),
    ]

    if reload:
        uvicorn_args.append("--reload")

        # Watch the src directory + plugins for changes
        src_dir = project_dir / "src"
        if src_dir.is_dir():
            uvicorn_args.extend(["--reload-dir", str(src_dir)])

    # Run uvicorn in the project directory
    try:
        os.chdir(run_dir)
        result = subprocess.run(
            uvicorn_args,
            cwd=str(run_dir),
        )
        raise typer.Exit(code=result.returncode)
    except KeyboardInterrupt:
        console.print("\n[dim]👋 Shutting down...[/]")
        raise typer.Exit()


def _print_banner(import_path: str, host: str, port: int, reload: bool, pyc: bool, project_dir: Path):
    """Print a styled startup banner."""
    url = f"http://{host}:{port}"
    if host == "0.0.0.0":
        url = f"http://localhost:{port}"

    lines = [
        f"[bold cyan]📦 App:[/]     {import_path}",
        f"[bold cyan]🌐 URL:[/]     [link={url}]{url}[/link]",
        f"[bold cyan]📂 Project:[/] {project_dir}",
    ]
    if pyc:
        lines.append("[bold cyan]⚡ PYC:[/]     [yellow]enabled[/] — serving bytecode to client VFS")
    if reload:
        lines.append("[bold cyan]🔥 HMR:[/]     [green]enabled[/] — watching for changes")

    panel = Panel(
        "\n".join(lines),
        title="[bold white]🚀 Basis Dev Server[/]",
        border_style="bright_blue",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)


def _show_plugin_summary(module_name: str, project_dir: Path):
    """
    Attempt to discover plugins and display a summary table.

    This does a lightweight scan without fully importing the app — it checks
    the ``plugins/`` directory for plugin files and scans entry_points.
    """
    from basis.server.app import discover_local_plugins, discover_installed_plugins

    # Try to find the plugins/ dir relative to the package
    src_dir = project_dir / "src"
    plugins_found = False

    # Scan for local plugins
    local_plugins = []
    package_dir = src_dir / module_name.replace(".", "/")
    if package_dir.is_dir():
        local_plugins = discover_local_plugins(package_dir, "plugins")
    elif (project_dir / module_name.replace(".", "/")).is_dir():
        local_plugins = discover_local_plugins(
            project_dir / module_name.replace(".", "/"), "plugins"
        )

    # Scan for installed plugins
    installed_plugins = discover_installed_plugins()

    if not local_plugins and not installed_plugins:
        return

    console.print()

    if local_plugins:
        table = Table(
            title="🔌 Local Plugins (plugins/)",
            box=box.ROUNDED,
            title_style="bold white",
            border_style="bright_blue",
            header_style="bold cyan",
        )
        table.add_column("Name", style="bold white")
        table.add_column("Prefix", style="green")
        table.add_column("Source", style="dim")

        for p in local_plugins:
            table.add_row(p.name, p.prefix, f"plugins/{p.name}.py")
        console.print(table)
        plugins_found = True

    if installed_plugins:
        if plugins_found:
            console.print()
        table = Table(
            title="📦 Installed Plugins (entry_points)",
            box=box.ROUNDED,
            title_style="bold white",
            border_style="bright_blue",
            header_style="bold cyan",
        )
        table.add_column("Name", style="bold white")
        table.add_column("Prefix", style="green")
        table.add_column("Package", style="dim")

        for p in installed_plugins:
            table.add_row(p.name, p.prefix, "—")
        console.print(table)

    console.print()
