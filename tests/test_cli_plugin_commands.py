"""Lazy plugin command groups in the CLI (CLI-EXTENSIBILITY.md §6.11).

Covers: the import-free cli/ existence check, the LazyGroup import-on-first-use
semantics (root help is import-free, dispatch imports), reserved/identifier
filtering, clean failure isolation, and the end-to-end theme port
(``basis theme list`` contributed by the theme plugin).
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import click
import pytest
import typer
from click.testing import CliRunner
from typer.main import get_command as typer_to_click

from basis.cli.discovery import (
    RESERVED_CLI_GROUPS,
    _cli_help_line,
    _cli_module_of,
    discover_installed_plugin_group_loaders,
)
from basis.cli.lazy import LazyGroup, import_plugin_cli
from basis.cli.main import build_root

runner = CliRunner()


class _F:
    """Minimal PackagePath stand-in: str() is a RECORD-relative path."""

    def __init__(self, path: str):
        self._path = path

    def __str__(self):
        return self._path


class _FakeDist:
    def __init__(self, name: str, files):
        self.metadata = {"Name": name}
        self.files = [_F(f) for f in files]

    def locate_file(self, rel):
        return Path("/nonexistent") / rel


class _FakeEP:
    def __init__(self, name: str, module: str, files=()):
        self.name = name
        self.module = module
        self.dist = _FakeDist(name, files)


def _inject_cli_module(name: str, commands=("up", "down")) -> str:
    """Register a fake module exposing a module-level ``cli`` typer.Typer."""
    mod = types.ModuleType(name)
    cli = typer.Typer(name=name.rsplit(".", 1)[-1], help="x", no_args_is_help=True)
    for cmd in commands:
        cli.command(cmd)(lambda cmd=cmd: print(f"{cmd} ran!"))
    mod.cli = cli
    sys.modules[name] = mod
    return name


# --------------------------------------------------------------------------- #
# Import-free discovery
# --------------------------------------------------------------------------- #


def test_cli_module_of_finds_package_cli_under_entry_module():
    ep = _FakeEP("mig", "myapp.plugins.mig.plugin", ["myapp/plugins/mig/cli/__init__.py"])
    assert _cli_module_of(ep) == "myapp.plugins.mig.cli"


def test_cli_module_of_finds_module_cli_when_entry_is_package():
    # entry point points at the package __init__ itself
    ep = _FakeEP("mig", "myapp.plugins.mig", ["myapp/plugins/mig/cli.py"])
    assert _cli_module_of(ep) == "myapp.plugins.mig.cli"


def test_cli_module_of_none_without_cli(monkeypatch):
    ep = _FakeEP("ui", "basis.plugins.ui.plugin", ["basis/plugins/ui/plugin.py"])
    assert _cli_module_of(ep) is None


def test_installed_discovery_filters_by_cli_identifier_reserved(monkeypatch):
    # myapp/* paths so the sys.path fallback can't resolve them against the real
    # basis source tree — the help then falls back to the generic line.
    eps = [
        _FakeEP("theme", "myapp.plugins.theme.plugin", ["myapp/plugins/theme/cli/__init__.py"]),
        _FakeEP("ui", "myapp.plugins.ui.plugin", ["myapp/plugins/ui/plugin.py"]),  # no cli
        _FakeEP("theme-basis", "myapp.plugins.theme.default_theme", ["myapp/plugins/theme/cli/__init__.py"]),  # not an identifier
        _FakeEP("plugin", "evil.plugin", ["evil/plugin/cli/__init__.py"]),  # reserved
    ]
    monkeypatch.setattr("basis.cli.discovery.entry_points", lambda group: eps)
    loaders = discover_installed_plugin_group_loaders()
    assert [(n, h) for n, h, _ in loaders] == [("theme", "theme commands")]


def test_cli_help_line_reads_module_level_help(tmp_path):
    init_py = tmp_path / "cli" / "__init__.py"
    init_py.parent.mkdir()
    init_py.write_text(
        '"""Docs."""\nhelp = "🎨 Manage Basis themes."  # trailing comment\ncli = None\n',
        encoding="utf-8",
    )
    assert _cli_help_line(init_py) == "🎨 Manage Basis themes."
    assert _cli_help_line(tmp_path / "missing" / "cli" / "__init__.py") is None


def test_cli_help_line_ignores_help_kwarg_inside_typer_call(tmp_path):
    # only a module-level `help = "…"` (line start) counts — the `help=` kwarg
    # inside typer.Typer(...) must NOT be picked up as the description
    init_py = tmp_path / "cli" / "__init__.py"
    init_py.parent.mkdir()
    init_py.write_text(
        "cli = typer.Typer(\n    name='theme',\n    help='hidden',\n)\n",
        encoding="utf-8",
    )
    assert _cli_help_line(init_py) is None


def test_installed_discovery_reads_help_from_disk(tmp_path, monkeypatch):
    cli_init = tmp_path / "myapp" / "plugins" / "mig" / "cli" / "__init__.py"
    cli_init.parent.mkdir(parents=True)
    cli_init.write_text('help = "Manage migrations."\ncli = None\n', encoding="utf-8")

    class _TmpDist:
        metadata = {"Name": "myapp"}
        files = []

        def locate_file(self, rel):
            return tmp_path / rel

    class _TmpEP:
        name = "mig"
        module = "myapp.plugins.mig.plugin"
        dist = _TmpDist()

    monkeypatch.setattr("basis.cli.discovery.entry_points", lambda group: [_TmpEP()])
    loaders = discover_installed_plugin_group_loaders()
    assert [(n, h) for n, h, _ in loaders] == [("mig", "Manage migrations.")]


def test_import_plugin_cli_expects_typer_cli():
    module = _inject_cli_module("fake.mig.cli")
    cmd = import_plugin_cli(module)
    assert hasattr(cmd, "get_command")
    assert cmd.name == "cli"


def test_import_plugin_cli_rejects_module_without_cli():
    mod = types.ModuleType("fake.bad.cli")
    sys.modules["fake.bad.cli"] = mod
    with pytest.raises(TypeError, match="module-level `cli`"):
        import_plugin_cli("fake.bad.cli")


# --------------------------------------------------------------------------- #
# LazyGroup semantics
# --------------------------------------------------------------------------- #


def _make_root(stub_cli, spy):
    app = typer.Typer(name="basis")
    app.command("builtin")(lambda: print("builtin ran!"))

    @app.callback()
    def _cb():  # callback → get_command returns a TyperGroup (add_command-capable)
        pass

    def load():
        spy["n"] += 1
        return typer_to_click(stub_cli)

    root = typer_to_click(app)
    root.add_command(LazyGroup(name="stub", help="Stub commands.", load=load))
    return root


def test_lazy_group_root_help_does_not_import():
    stub = typer.Typer(name="stub", no_args_is_help=True)
    stub.command("hi")(lambda: None)
    spy = {"n": 0}
    root = _make_root(stub, spy)

    result = runner.invoke(root, ["--help"])
    assert result.exit_code == 0
    assert "stub" in result.output
    assert spy["n"] == 0  # listing the group did not import its body


def test_lazy_group_imports_only_when_descended():
    stub = typer.Typer(name="stub", no_args_is_help=True)
    stub.command("hi")(lambda: print("hi ran!"))
    spy = {"n": 0}
    root = _make_root(stub, spy)

    result = runner.invoke(root, ["stub", "hi"])
    assert result.exit_code == 0
    assert "hi ran!" in result.output
    assert spy["n"] == 1  # imported exactly once, at dispatch


def test_lazy_group_group_help_imports_once_then_caches():
    stub = typer.Typer(name="stub", no_args_is_help=True)
    stub.command("hi")(lambda: print("hi ran!"))
    spy = {"n": 0}
    root = _make_root(stub, spy)

    runner.invoke(root, ["stub", "--help"])  # group help imports once (help exits via Exit(0))
    assert spy["n"] == 1
    result = runner.invoke(root, ["stub", "hi"])
    assert result.exit_code == 0
    assert "hi ran!" in result.output
    assert spy["n"] == 1  # cached — no second import


def test_broken_plugin_group_is_a_clean_error_not_a_traceback():
    app = typer.Typer(name="basis")

    @app.callback()
    def _cb():  # callback → TyperGroup root
        pass

    root = typer_to_click(app)

    def broken_load():
        raise ImportError("no module named 'x.cli'")

    root.add_command(LazyGroup(name="broken", help="Broken.", load=broken_load))

    result = runner.invoke(root, ["broken", "x"])
    assert result.exit_code != 0
    assert "Failed to load plugin command group 'broken'" in result.output
    # the rest of the CLI is unaffected
    assert runner.invoke(root, ["--help"]).exit_code == 0


def test_reserved_groups_are_protected():
    assert "dev" in RESERVED_CLI_GROUPS
    assert "theme" not in RESERVED_CLI_GROUPS  # theme is plugin-provided now


# --------------------------------------------------------------------------- #
# End-to-end: the theme port
# --------------------------------------------------------------------------- #


def test_build_root_mounts_theme_plugin_group():
    root = build_root()
    assert "theme" in root.commands
    group = root.commands["theme"]
    assert isinstance(group, LazyGroup)
    # real description read import-free from the theme plugin's cli/__init__.py
    assert group.help == "🎨 Manage Basis themes."


def test_theme_commands_run_via_plugin_group():
    root = build_root()
    result = runner.invoke(root, ["theme", "list"])
    assert result.exit_code == 0
    assert "Themes" in result.output  # the installed-themes table rendered

    apply = runner.invoke(root, ["theme", "apply", "basis"])
    assert apply.exit_code == 0
    assert "valid" in apply.output
