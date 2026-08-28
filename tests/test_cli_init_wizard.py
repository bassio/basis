"""The declarative question tree + wizard driver — P2 of INIT-SHELL-PLAN.md.

The P2 gate: the question-tree model is fully testable without a TTY
(``iter_active_questions`` gating + ``build_config``), and ``run_wizard`` walks
the whole tree with an injected prompter (no terminal required).
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from basis.cli.init.config import PARADIGM_APP, PARADIGM_SITE, ShellConfig
from basis.cli.init.wizard import (
    QUESTION_GROUPS,
    WizardAborted,
    build_config,
    default_answers,
    iter_active_questions,
    run_wizard,
)


def _quiet_console() -> Console:
    return Console(file=io.StringIO())


# --- defaults --------------------------------------------------------------

def test_default_answers_cover_all_shell_config_fields():
    fields = {f.name for f in ShellConfig.__dataclass_fields__.values()}
    assert set(default_answers()) == fields


def test_default_answers_honor_project_name_default():
    assert default_answers("myapp")["project_name"] == "myapp"


# --- build_config ----------------------------------------------------------

def test_build_config_from_answers():
    cfg = build_config({"project_name": "demo", "paradigm": PARADIGM_SITE, "footer": False})
    assert cfg.paradigm == PARADIGM_SITE
    assert cfg.footer is False
    assert cfg.titlebar is True  # untouched default


def test_build_config_rejects_unknown_key():
    with pytest.raises(ValueError, match="Unknown shell config option"):
        build_config({"project_name": "x", "nope": True})


def test_build_config_requires_project_name():
    with pytest.raises(ValueError, match="Project name is required"):
        build_config(default_answers())


# --- question-tree gating --------------------------------------------------

def test_app_questions_active_in_app_mode():
    active = {q.id for q in iter_active_questions({"paradigm": PARADIGM_APP})}
    assert {"titlebar", "statusbar", "activitybar", "sidebar_left", "sidebar_right"} <= active
    assert "header" not in active
    assert "footer" not in active


def test_site_questions_active_in_site_mode():
    active = {q.id for q in iter_active_questions({"paradigm": PARADIGM_SITE})}
    assert {"header", "footer"} <= active
    assert "titlebar" not in active


def test_collapsible_only_when_left_sidebar_chosen():
    on = {q.id for q in iter_active_questions({"paradigm": PARADIGM_APP, "sidebar_left": True})}
    off = {q.id for q in iter_active_questions({"paradigm": PARADIGM_APP, "sidebar_left": False})}
    assert "sidebar_left_collapsible" in on
    assert "sidebar_left_collapsible" not in off


def test_sticky_header_only_when_site_and_header():
    on = {q.id for q in iter_active_questions({"paradigm": PARADIGM_SITE, "header": True})}
    no_header = {q.id for q in iter_active_questions({"paradigm": PARADIGM_SITE, "header": False})}
    app = {q.id for q in iter_active_questions({"paradigm": PARADIGM_APP})}
    assert "sticky_header" in on
    assert "sticky_header" not in no_header
    assert "sticky_header" not in app


def test_question_shape_is_valid():
    for group in QUESTION_GROUPS:
        assert group.title.strip()
        for q in group.questions:
            assert q.id.strip()
            assert q.kind in {"text", "confirm", "choice"}
            assert q.label.strip()
            if q.kind == "choice":
                assert q.choices


# --- run_wizard (no TTY: injected prompter) --------------------------------

def test_run_wizard_walks_tree_and_returns_defaults():
    cfg = run_wizard(
        project_name_default="demo",
        prompter=lambda q, a, c: a.get(q.id, q.default),
        console=_quiet_console(),
    )
    assert cfg.project_name == "demo"
    assert cfg.paradigm == PARADIGM_APP
    assert cfg.demo is True
    assert cfg.example_store is True


def test_run_wizard_applies_prompter_answers():
    def prompter(q, a, c):
        overrides = {"paradigm": PARADIGM_SITE, "footer": False, "demo": False}
        return overrides.get(q.id, a.get(q.id, q.default))

    cfg = run_wizard(project_name_default="demo", prompter=prompter, console=_quiet_console())
    assert cfg.paradigm == PARADIGM_SITE
    assert cfg.footer is False
    assert cfg.demo is False


def test_run_wizard_skips_initial_keys():
    asked: list[str] = []

    def prompter(q, a, c):
        asked.append(q.id)
        return a.get(q.id, q.default)

    cfg = run_wizard(initial={"project_name": "myapp"}, prompter=prompter, console=_quiet_console())
    assert cfg.project_name == "myapp"
    assert "project_name" not in asked  # pre-filled → not asked
    assert "paradigm" in asked


def test_run_wizard_abort_raises_wizard_aborted():
    def prompter(q, a, c):
        raise KeyboardInterrupt

    with pytest.raises(WizardAborted):
        run_wizard(project_name_default="demo", prompter=prompter, console=_quiet_console())
