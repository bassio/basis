"""``basis init`` CLI wiring — P3 of INIT-SHELL-PLAN.md.

Exercises the typer command registered on ``basis.cli.main:app``: flag-driven
non-interactive generation (``--yes``), ``--list``, ``--config`` replay, and the
clean-error paths.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from basis.cli.main import app

runner = CliRunner()


def _temp_dir_from_output(output: str) -> Path:
    """Extract the temp root path printed by ``basis init --test``."""
    match = re.search(r"Temp dir:\s*(\S+)", output)
    assert match, f"no 'Temp dir:' line in output:\n{output}"
    return Path(match.group(1))


def test_list_prints_question_tree():
    result = runner.invoke(app, ["init", "--list"])
    assert result.exit_code == 0
    assert "0 · Project" in result.output
    assert "Shell paradigm:" in result.output
    assert "Include a Titlebar?" in result.output
    assert "Theme seed:" in result.output


def test_yes_generates_minimal_project(tmp_path):
    result = runner.invoke(app, ["init", "demo", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    project = tmp_path / "demo"
    assert (project / "pyproject.toml").exists()
    assert (project / "src/demo/__init__.py").exists()
    assert (project / "src/demo/components/page.py").exists()
    assert (project / "src/demo/components/app_container.py").exists()


def test_shell_site_flag_customizes_frame(tmp_path):
    result = runner.invoke(
        app,
        ["init", "demo", "--dir", str(tmp_path), "--yes", "--shell", "site", "--no-footer"],
    )
    assert result.exit_code == 0, result.output
    frame = (tmp_path / "demo/src/demo/components/app_container.py").read_text()
    assert "<shell-site>" in frame
    assert "<shell-footer" not in frame
    # app-only chrome must not be present in a site shell
    assert "<shell-title-bar>" not in frame


def test_app_shell_includes_chrome(tmp_path):
    result = runner.invoke(app, ["init", "demo", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 0, result.output
    frame = (tmp_path / "demo/src/demo/components/app_container.py").read_text()
    assert "shell-title-bar" in frame
    assert "shell-status-bar" in frame
    assert "shell-activity-bar" in frame


def test_config_replay(tmp_path):
    cfg_file = tmp_path / "answers.json"
    cfg_file.write_text(
        json.dumps({"project_name": "cfgapp", "paradigm": "site", "footer": False}),
        encoding="utf-8",
    )
    result = runner.invoke(app, ["init", "--dir", str(tmp_path), "--config", str(cfg_file)])
    assert result.exit_code == 0, result.output
    project = tmp_path / "cfgapp"
    assert (project / "src/cfgapp/components/app_container.py").exists()
    frame = (project / "src/cfgapp/components/app_container.py").read_text()
    assert "<shell-site>" in frame


def test_invalid_shell_is_clean_error(tmp_path):
    result = runner.invoke(
        app, ["init", "demo", "--dir", str(tmp_path), "--yes", "--shell", "terminal"]
    )
    assert result.exit_code == 1
    assert "Unknown shell paradigm" in result.output
    assert not (tmp_path / "demo").exists()


def test_existing_dir_is_clean_error(tmp_path):
    (tmp_path / "demo").mkdir()
    result = runner.invoke(app, ["init", "demo", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 1
    # Rich word-wraps long error lines to the console width (80 cols when stdout
    # isn't a tty, as under pytest capture); the pytest tmp_path is long enough
    # to force a wrap here, so collapse whitespace before the substring check.
    assert "already exists" in re.sub(r"\s+", " ", result.output)


def test_yes_without_name_is_clean_error(tmp_path):
    result = runner.invoke(app, ["init", "--dir", str(tmp_path), "--yes"])
    assert result.exit_code == 1
    assert "Project name is required" in result.output


# --- --test mode (generate into a throwaway temp directory) ---------------


def test_test_generates_into_temp_dir():
    """``basis init --test`` generates the default app shell into a fresh temp
    dir (non-interactive, no collision with the cwd), and prints its path."""
    result = runner.invoke(app, ["init", "--test"])
    assert result.exit_code == 0, result.output
    project = _temp_dir_from_output(result.output)
    assert (project / "pyproject.toml").exists()
    assert (project / "src/basistest/__init__.py").exists()
    assert (project / "src/basistest/components/app_container.py").exists()
    assert "Test shell generated" in result.output
    assert "basis-init-" in result.output


def test_test_honors_flags_and_positional_name():
    """Flags + positional name still customize the generated shell."""
    result = runner.invoke(
        app, ["init", "zappy", "--test", "--shell", "site", "--no-footer"]
    )
    assert result.exit_code == 0, result.output
    project = _temp_dir_from_output(result.output)
    assert (project / "src/zappy/__init__.py").exists()
    frame = (project / "src/zappy/components/app_container.py").read_text()
    assert "<shell-site>" in frame
    assert "<shell-footer" not in frame


def test_test_invalid_flags_are_clean_error():
    """Validation still fails cleanly (and before writing anything)."""
    result = runner.invoke(app, ["init", "--test", "--shell", "terminal"])
    assert result.exit_code == 1
    assert "Unknown shell paradigm" in result.output


def test_test_repeated_invocations_do_not_collide():
    """Every --test run gets its own temp dir (no 'already exists' collision)."""
    first = runner.invoke(app, ["init", "--test"])
    second = runner.invoke(app, ["init", "--test"])
    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    p1 = _temp_dir_from_output(first.output)
    p2 = _temp_dir_from_output(second.output)
    assert p1 != p2
    assert (p1 / "src/basistest/__init__.py").exists()
    assert (p2 / "src/basistest/__init__.py").exists()
