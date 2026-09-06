"""Lazy plugin command groups — cheap discovery, import-on-first-use.

The CLI mounts one :class:`LazyGroup` stub per cli-bearing plugin (see
:mod:`basis.cli.discovery`). The stub is constructed from import-free metadata;
its body (``<pkg>.cli``) is imported only when Click actually descends into the
group, so ``basis dev`` / ``basis init`` / ``basis bench`` never import plugin
code, and ``basis <plugin> <sub>`` imports that plugin exactly when you run it.
"""
from __future__ import annotations

import importlib
from collections.abc import Callable

import typer
from rich.console import Console
from typer.core import TyperCommand, TyperGroup
from typer.main import get_command as _typer_to_click

# typer ≥ 0.27 vendors its own click (``typer._click``) and the whole CLI tree
# (root + bodies) is built on it. Errors must be raised with ITS exception
# classes — a real-``click`` exception is a *different* class that the vendored
# root's ``main()`` never catches, so it would leak as a traceback instead of a
# clean error. Older typer builds directly on real click → fall back to that.
try:
    from typer._click.exceptions import ClickException as _ClickException
except ImportError:  # pragma: no cover — older typer versions
    from click import ClickException as _ClickException

console = Console()


class LazyGroup(TyperGroup):
    """A group stub whose body is imported only when a subcommand is requested.

    Subclasses :class:`typer.core.TyperGroup` — the same group class Typer's
    ``get_command`` produces for the CLI root — rather than a raw
    ``click.Group``. Typer ≥ 0.27 vendors its own Click (``typer._click``); a
    real-``click`` group nested under that root raises a *real*
    ``click.exceptions.Exit`` on ``--help`` that the vendored root's ``main()``
    never catches (a different ``Exit`` class) → traceback. Matching the root's
    group class keeps the whole dispatch tree one Click flavor, so group
    ``--help`` and error handling exit cleanly.

    ``name`` and ``help`` come from import-free metadata; ``load`` performs the
    real (heavy) import on first use. A broken body surfaces as a clean error on
    that group only — it can never brick the rest of the CLI.
    """

    def __init__(
        self,
        name: str,
        help: str | None,
        load: Callable[[], TyperGroup | TyperCommand],
        **kwargs,
    ):
        super().__init__(name=name, help=help, **kwargs)
        self._load = load
        self._loaded: TyperGroup | TyperCommand | None = None

    def _ensure(self) -> TyperGroup | TyperCommand:
        if self._loaded is None:
            try:
                self._loaded = self._load()
            except Exception as exc:  # one broken plugin must not brick the CLI
                console.print(
                    f"[red]✗ Failed to load plugin command group '{self.name}':[/] {exc}"
                )
                raise _ClickException(
                    f"could not load plugin command group '{self.name}'"
                )
        return self._loaded

    def get_command(self, ctx, cmd_name):
        body = self._ensure()
        if hasattr(body, "get_command"):
            return body.get_command(ctx, cmd_name)
        # A single-command typer collapses to a plain command (no group) —
        # expose it as the only subcommand.
        return body if getattr(body, "name", None) == cmd_name else None

    def list_commands(self, ctx):
        body = self._ensure()
        if hasattr(body, "list_commands"):
            return body.list_commands(ctx)
        name = getattr(body, "name", None)
        return [name] if name else []


def import_plugin_cli(module: str) -> TyperGroup | TyperCommand:
    """Import a plugin's ``cli`` module and return the Click command for its
    ``cli`` ``typer.Typer``.

    The module must expose a module-level ``cli`` that is a ``typer.Typer``.
    Importing the submodule runs the parent package's ``__init__.py`` (Python
    semantics) — that is the expected ~400 ms cost, paid only when this plugin's
    command is actually requested.
    """
    mod = importlib.import_module(module)
    obj = getattr(mod, "cli", None)
    if not isinstance(obj, typer.Typer):
        raise TypeError(
            f"{module} must expose a module-level `cli` typer.Typer "
            f"(got {type(obj).__name__})"
        )
    return _typer_to_click(obj)
