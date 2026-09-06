"""``basis theme`` — theme package commands, contributed by the theme plugin.

The lazy CLI-discovery convention (CLI-EXTENSIBILITY.md): a plugin ships a
``cli/`` subpackage exposing a module-level ``cli`` ``typer.Typer``; the CLI
mounts it as ``basis <plugin-name>`` with import-on-first-use. This module is the
``theme`` plugin's contribution — previously hardcoded in ``basis.cli.commands.theme``.

Sub-commands::

    basis theme list     — Show installed theme packages (kind == "theme")
    basis theme apply    — Resolve + validate a theme by id (loud errors)

CLI-only: this module imports ``typer`` and server discovery and is never
imported by the client (nothing in the app references ``basis.plugins.theme.cli``).
"""
from __future__ import annotations

import typer
from rich.console import Console
from rich.table import Table
from rich import box

console = Console()

# Read import-free by CLI discovery (CLI-EXTENSIBILITY.md §6.11) so that
# `basis --help` shows the real description without importing this module.
help = "🎨 Manage Basis themes."

cli = typer.Typer(
    name="theme",
    help=help,
    no_args_is_help=True,
    rich_markup_mode="rich",
)


def _discover_themes() -> list:
    """All installed theme plugins (``kind == "theme"``), sorted by id."""
    from basis.server.plugins import discover_installed_plugins

    themes = [
        p for p in discover_installed_plugins()
        if getattr(p, "kind", "") == "theme"
    ]
    return sorted(themes, key=lambda p: getattr(getattr(p, "definition", None), "id", p.name))


def _modes(definition) -> list[str]:
    scheme = getattr(definition, "color_scheme", "auto") or "auto"
    return ["light", "dark"] if scheme in ("auto", "system") else [scheme]


@cli.command("list")
def theme_list():
    """Show all installed theme packages (kind == \"theme\")."""
    themes = _discover_themes()
    if not themes:
        console.print("\n[dim]No themes installed.[/]\n")
        console.print("  [cyan]•[/] Themes are packages — [bold]pip install basis-theme-*[/]\n")
        return

    table = Table(
        title="🎨 Installed Themes",
        box=box.ROUNDED,
        title_style="bold white",
        border_style="bright_blue",
        header_style="bold cyan",
        show_lines=True,
    )
    table.add_column("ID", style="bold white", min_width=10)
    table.add_column("Name", style="green", min_width=18)
    table.add_column("Plugin", style="dim", min_width=16)
    table.add_column("Version", style="yellow", min_width=8)
    table.add_column("Modes", style="cyan", min_width=12)

    for p in themes:
        d = p.definition
        table.add_row(
            d.id,
            d.name,
            p.name,
            d.version or "—",
            "/".join(_modes(d)),
        )
    console.print(table)
    console.print(
        f"\n  [bold]{len(themes)}[/] theme{'s' if len(themes) != 1 else ''} installed.\n"
    )


@cli.command("apply")
def theme_apply(
    theme_id: str = typer.Argument(
        ...,
        help="Theme id to resolve + validate (e.g. 'ambient' or 'basis').",
    ),
):
    """Resolve + validate a theme by id — loud errors on a broken manifest."""
    from basis.plugins.theme.default import DEFAULT_DEFINITION

    definition = next(
        (p.definition for p in _discover_themes() if getattr(p.definition, "id", None) == theme_id),
        None,
    )
    if definition is None and theme_id == DEFAULT_DEFINITION.id:
        definition = DEFAULT_DEFINITION
    if definition is None:
        console.print(f"[red]✗ Unknown theme '{theme_id}'.[/]")
        console.print("  Run [bold]basis theme list[/] to see the installed themes.")
        raise typer.Exit(code=1)

    definition.validate()  # raises a clear ValueError on a broken manifest
    console.print(f"[green]✔[/] [bold]{definition.name}[/] ({definition.id}) — valid.")
    console.print(
        f"  version {definition.version or '—'} · modes {'/'.join(_modes(definition))} · "
        f"data-theme {definition.data_theme}"
    )
    console.print("  Apply it at runtime via the theme manager (<ui-theme-picker>); the")
    console.print("  choice persists per-user (basis_theme cookie). A per-app default")
    console.print("  theme seed (basis theme apply writing app config) is a later phase.")
