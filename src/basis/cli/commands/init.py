"""
``basis init`` — interactive app-shell wizard (create-react-app for Basis).

Runs a cookiecutter-style question flow (project name → shell paradigm →
top-level stack → extras), then generates a loadable Basis app shell — workbench
(``app``) or website (``site``) — that runs on ``basis dev --hmr`` with an SSR
page at "/". See INIT-SHELL-PLAN.md.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm
from rich.tree import Tree

from basis.cli.init.config import ShellConfig
from basis.cli.init.wizard import QUESTION_GROUPS, WizardAborted, run_wizard
from basis.cli.init.writer import generate

console = Console()


def init(
    project_name: Optional[str] = typer.Argument(
        None,
        help="Name for the new project (e.g. 'my-app'). If omitted, the wizard asks (default: current directory name).",
    ),
    directory: str = typer.Option(
        None,
        "--dir",
        "-d",
        help="Parent directory to create the project in. Defaults to the current directory.",
    ),
    shell: str = typer.Option(
        None,
        "--shell",
        help="Shell paradigm: 'app' (fixed-viewport workbench) or 'site' (document-flow website).",
    ),
    theme: str = typer.Option(None, "--theme", help="Theme seed: 'dark' or 'light'."),
    sidebar_left_collapsible: str = typer.Option(
        None,
        "--sidebar-left-collapsible",
        help="Left sidebar collapse mode: none | icon | offcanvas.",
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        "-y",
        help="Non-interactive: use defaults plus any provided flags (a minimal loadable skeleton).",
    ),
    config: str = typer.Option(None, "--config", help="Path to a JSON answers file to replay."),
    show_list: bool = typer.Option(False, "--list", help="Print the wizard question tree and exit."),
    test: bool = typer.Option(
        False,
        "--test",
        help="Generate a shell into a fresh temporary directory instead of the current directory (non-interactive).",
    ),
    serve: bool = typer.Option(
        False,
        "--serve",
        help="With --test: start the dev server in the generated temp directory.",
    ),
    titlebar: Optional[bool] = typer.Option(None, "--titlebar/--no-titlebar", help="Include a Titlebar."),
    statusbar: Optional[bool] = typer.Option(None, "--statusbar/--no-statusbar", help="Include a Statusbar."),
    activitybar: Optional[bool] = typer.Option(None, "--activitybar/--no-activitybar", help="Include an ActivityBar."),
    sidebar_left: Optional[bool] = typer.Option(None, "--sidebar-left/--no-sidebar-left", help="Include a Left Sidebar."),
    sidebar_right: Optional[bool] = typer.Option(None, "--sidebar-right/--no-sidebar-right", help="Include a Right Sidebar."),
    header: Optional[bool] = typer.Option(None, "--header/--no-header", help="Include a Header (nav)."),
    footer: Optional[bool] = typer.Option(None, "--footer/--no-footer", help="Include a Footer."),
    sticky_header: Optional[bool] = typer.Option(None, "--sticky-header/--no-sticky-header", help="Make the header sticky."),
    demo: Optional[bool] = typer.Option(None, "--demo/--no-demo", help="Generate demo content."),
    example_store: Optional[bool] = typer.Option(None, "--store/--no-store", help="Generate an example store."),
    example_plugin: Optional[bool] = typer.Option(None, "--plugin/--no-plugin", help="Generate an example plugin."),
):
    """Scaffold a Basis app shell interactively (or non-interactively with --yes / --test)."""
    if show_list:
        _print_question_tree()
        raise typer.Exit()

    # Map CLI flags → ShellConfig fields, keeping only what was explicitly given
    # (unset flags defer to the wizard's defaults).
    overrides: dict = {}
    if project_name:
        overrides["project_name"] = project_name
    if shell:
        overrides["paradigm"] = shell
    if theme:
        overrides["theme"] = theme
    if sidebar_left_collapsible:
        overrides["sidebar_left_collapsible"] = sidebar_left_collapsible
    for name, value in (
        ("titlebar", titlebar), ("statusbar", statusbar), ("activitybar", activitybar),
        ("sidebar_left", sidebar_left), ("sidebar_right", sidebar_right),
        ("header", header), ("footer", footer), ("sticky_header", sticky_header),
        ("demo", demo), ("example_store", example_store), ("example_plugin", example_plugin),
    ):
        if value is not None:
            overrides[name] = value

    # --config replays a saved answers file (non-interactive); flags win.
    # --test is always non-interactive (it targets a throwaway temp dir).
    non_interactive = bool(yes or test)
    if config:
        try:
            saved = json.loads(Path(config).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            console.print(f"[bold red]Error:[/] Could not read config '{config}': {exc}")
            raise typer.Exit(code=1)
        overrides = {**saved, **overrides}
        non_interactive = True

    if serve and not test:
        console.print("[bold yellow]Note:[/] --serve only applies with --test; ignoring it.")

    if test:
        # Throwaway shell in a fresh temp dir — the fast "does this generate
        # correctly / how does it look" loop (optionally --serve it).
        _run_test(overrides, serve)
        raise typer.Exit()

    parent = Path(directory).resolve() if directory else Path.cwd()

    try:
        if non_interactive:
            cfg = ShellConfig.from_flags(**overrides)
            cfg.validate()
        else:
            cfg = run_wizard(initial=overrides, console=console)
            if not Confirm.ask(
                f"Create project [bold]{cfg.project_name}[/] in {parent}?",
                default=True,
                console=console,
            ):
                console.print("[dim]Aborted.[/]")
                raise typer.Exit()
    except WizardAborted:
        raise typer.Exit(code=1)
    except ValueError as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        raise typer.Exit(code=1)

    project_dir = parent / cfg.project_name
    if project_dir.exists():
        console.print(f"[bold red]Error:[/] Directory '{project_dir}' already exists.")
        raise typer.Exit(code=1)

    written = generate(cfg, project_dir)
    _show_success(cfg, project_dir, written)


# --- output helpers -------------------------------------------------------


def _run_test(overrides: dict, serve: bool) -> None:
    """``basis init --test``: build a shell in a fresh temp dir (non-interactive).

    Uses defaults plus any provided flags, so ``basis init --test --shell site``
    tests the site generator. The temp dir is created fresh (never collides),
    and the ``cd``/dev commands are printed so the shell can be run immediately
    — pass ``--serve`` to start the dev server right here.
    """
    overrides = dict(overrides)
    overrides.setdefault("project_name", "basistest")  # predictable default slug

    temp_root = Path(tempfile.mkdtemp(prefix="basis-init-"))
    try:
        cfg = ShellConfig.from_flags(**overrides)
        cfg.validate()
    except ValueError as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        raise typer.Exit(code=1)

    written = generate(cfg, temp_root)
    console.print(f"[bold green]→[/] Test shell: [cyan]{temp_root}[/]")
    _show_success(cfg, temp_root, written, test_mode=True)

    if serve:
        _serve_generated(temp_root)


def _serve_generated(project_dir: Path) -> None:
    """``--test --serve``: run ``basis dev --hmr`` in the temp project.

    The throwaway shell isn't installed in the environment, so ``src/`` is put
    on ``PYTHONPATH`` (the framework itself is already importable) — that lets
    the server boot without a ``uv sync`` inside the temp dir. ``basis`` is run
    as a subprocess rather than called in-process, because the typer command
    function's parameter defaults are typer metadata (``ArgumentInfo``), not
    plain values — calling it directly crashes ``find_basis_app``.
    """
    basis_exe = shutil.which("basis") or str(Path(sys.executable).parent / "basis")
    src_dir = project_dir / "src"
    existing = os.environ.get("PYTHONPATH", "")
    os.environ["PYTHONPATH"] = str(src_dir) + (os.pathsep + existing if existing else "")

    console.print(f"[bold green]🚀 Starting dev server for {project_dir} ...[/]")
    subprocess.run([basis_exe, "dev", "--hmr"], cwd=str(project_dir))


def _print_question_tree() -> None:
    """Print the wizard's question tree (``basis init --list``)."""
    for group in QUESTION_GROUPS:
        console.print(f"\n[bold cyan]{group.title}[/]")
        for q in group.questions:
            default = "" if q.default is None else f" [dim](default: {q.default})[/]"
            console.print(f"  · {q.label}{default}")


def _show_success(
    cfg: ShellConfig,
    project_dir: Path,
    written: list[Path],
    *,
    test_mode: bool = False,
) -> None:
    """Print the created project tree + next steps."""
    label = str(project_dir) if test_mode else f"{cfg.project_name}/"
    tree = Tree(f"📁 [bold cyan]{label}[/]")
    _build_tree(tree, project_dir, project_dir)
    console.print(tree)
    console.print()
    if test_mode:
        panel = Panel(
            f"[bold green]✅ Test shell generated in a temp directory![/]\n\n"
            f"[bold]Temp dir:[/] [cyan]{project_dir}[/]\n\n"
            f"  [dim]$[/] cd {project_dir}\n"
            f"  [dim]$[/] PYTHONPATH=src basis dev --hmr\n\n"
            f"[dim]Throwaway shell under the system temp dir — delete it when "
            f"you're done inspecting. (PYTHONPATH=src runs it with the "
            f"already-installed framework; no uv sync needed.)[/]",
            title="[bold white]Test It Now[/]",
            border_style="green",
            padding=(1, 2),
        )
    else:
        panel = Panel(
            f"[bold green]✅ Project created![/]\n\n"
            f"  [dim]$[/] cd {cfg.project_name}\n"
            f"  [dim]$[/] uv sync\n"
            f"  [dim]$[/] basis dev\n",
            title="[bold white]Next Steps[/]",
            border_style="green",
            padding=(1, 2),
        )
    console.print(panel)


def _build_tree(tree: Tree, current: Path, root: Path, depth: int = 0):
    """Recursively build a Rich Tree from the filesystem."""
    if depth > 4:
        return

    entries = sorted(current.iterdir(), key=lambda p: (p.is_file(), p.name))
    for entry in entries:
        if entry.name.startswith(".") and entry.name != ".gitignore":
            continue
        if entry.name == "__pycache__":
            continue

        if entry.is_dir():
            branch = tree.add(f"📁 [cyan]{entry.name}/[/]")
            _build_tree(branch, entry, root, depth + 1)
        else:
            icon = _file_icon(entry.name)
            tree.add(f"{icon} {entry.name}")


def _file_icon(name: str) -> str:
    if name.endswith(".py"):
        return "🐍"
    if name.endswith(".toml"):
        return "⚙️"
    if name.endswith(".md"):
        return "📄"
    if name.endswith(".html"):
        return "🌐"
    if name.endswith(".css"):
        return "🎨"
    return "📄"
