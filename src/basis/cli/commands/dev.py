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
        False,
        "--reload/--no-reload",
        help="Full-process reload on file changes (uvicorn --reload). Disables live HMR hot-swap.",
    ),
    hmr: bool = typer.Option(
        True,
        "--hmr/--no-hmr",
        help="Live client-side HMR: watch component files (.py/.html/.css) and hot-swap in the browser without a page refresh.",
    ),
    pyc: bool = typer.Option(
        False,
        "--pyc",
        help="Enable PYC compilation mode for served Python files.",
    ),
    profile: bool = typer.Option(
        False,
        "--profile",
        help="Run the server under cProfile and print a hot-path summary on shutdown (T0 server profiling).",
    ),
):
    """
    Start the Basis development server with hot-module reloading.

    By default component files (.py/.html/.css) are hot-swapped live in the
    browser over a WebSocket — no page refresh, no state loss. Pass ``--reload``
    to fall back to full process restarts instead (e.g. while editing server-only
    code outside component directories).

    Auto-detects the Basis app in the current project if no app path is given.
    """
    if pyc:
        os.environ["BASIS_PYC_MODE"] = "1"

    # Live HMR is the default. uvicorn --reload is mutually exclusive: it restarts
    # the whole process on any .py change, which would preempt (and race with) the
    # in-process HMR watcher.
    if hmr and not reload:
        os.environ["BASIS_HMR"] = "1"
    else:
        os.environ.pop("BASIS_HMR", None)

    project_dir = resolve_project_dir()
    import_path, run_dir = find_basis_app(app_path, cwd=project_dir)

    # Ensure we have the module:attribute format
    if ":" not in import_path:
        import_path = f"{import_path}:app"

    module_part, attr_part = import_path.split(":", 1)

    # Build the startup banner
    _print_banner(import_path, host, port, reload, hmr, pyc, profile, project_dir)

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

    # T0 server profiling: wrap uvicorn under cProfile so SSR/action hot paths
    # can be measured, and print a summary on shutdown.
    profile_file: Path | None = None
    if profile:
        profile_file = project_dir / ".basis-profile.pstats"
        uvicorn_args = [
            sys.executable, "-m", "cProfile",
            "-o", str(profile_file),
            *uvicorn_args[1:],  # re-add "-m uvicorn <app> ..."
        ]

    # Run uvicorn in the project directory
    try:
        os.chdir(run_dir)
        result = subprocess.run(
            uvicorn_args,
            cwd=str(run_dir),
        )
        if profile and profile_file is not None:
            _print_profile_summary(profile_file, module_part)
        raise typer.Exit(code=result.returncode)
    except KeyboardInterrupt:
        console.print("\n[dim]👋 Shutting down...[/]")
        if profile and profile_file is not None:
            _print_profile_summary(profile_file, module_part)
        raise typer.Exit()


def _print_profile_summary(profile_file: Path, module_name: str) -> None:
    """Print the hot-path summary from a cProfile dump (T0 server profiling).

    Reports the top cumulative-time frames that include this app's own module
    (or the framework's SSR/render path) so the "where does the time go" answer
    is about *user* code, not uvicorn's event loop internals.
    """
    import pstats

    if not profile_file.exists():
        console.print(
            "[yellow]No profile data was written[/] — the server never ran long "
            "enough to flush stats."
        )
        return

    console.print("\n[bold cyan]🔥 Hot-path summary[/] (top cumulative time)")
    try:
        stats = pstats.Stats(str(profile_file))
        stats.strip_dirs()
        rows = []
        for func, (cc, nc, tt, ct, callers) in stats.stats.items():
            # func is (file, line, name); skip the profile machinery itself.
            if func[2].startswith("_") and func[2] in ("_frame",):
                continue
            rows.append((ct, func, tt))
        rows.sort(reverse=True)
        shown = 0
        for ct, func, tt in rows:
            fname = func[0] or ""
            if module_name not in fname and "basis" not in fname:
                continue
            if shown >= 30:
                break
            if ct < 0.005:
                break
            console.print(
                f"  {ct:8.3f}s cum  {tt:8.3f}s self  "
                f"[dim]{fname}:{func[1]}[/] [white]{func[2]}[/]"
            )
            shown += 1
        if not shown:
            console.print("  [dim](no app/framework frames above the 5ms threshold)[/]")
    except Exception as e:  # pragma: no cover - defensive
        console.print(f"[yellow]Could not read profile: {e}[/]")

    console.print(
        f"\n[dim]Full profile saved to [bold]{profile_file}[/]. "
        "Open with `snakeviz`/`gprof2dot`, or: "
        "`python -m pstats .basis-profile.pstats`.[/]"
    )


def _print_banner(import_path: str, host: str, port: int, reload: bool, hmr: bool, pyc: bool, profile: bool, project_dir: Path):
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
    if profile:
        lines.append("[bold cyan]🔬 Profile:[/] [yellow]enabled[/] — cProfile → .basis-profile.pstats on exit")
    if hmr and not reload:
        lines.append("[bold cyan]🔥 HMR:[/]     [green]enabled[/] — live hot-swap (.py/.html/.css)")
    elif reload:
        lines.append("[bold cyan]🔥 HMR:[/]     [yellow]reload mode[/] — full process restarts")

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
