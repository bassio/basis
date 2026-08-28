"""The interactive question wizard for ``basis init`` (P2).

A declarative question tree (``Question`` / ``QuestionGroup``) drives
``rich.prompt`` — no new dependency. The tree is a pure model (testable without
a TTY): ``iter_active_questions`` applies each question's ``when`` predicate to
the answers-so-far, and ``build_config`` turns the collected answers into a
validated ``ShellConfig``. ``run_wizard`` is the thin interactive driver; the
CLI (P3) can pre-fill answers (e.g. the project name from ``basis init myapp``)
and those questions are skipped.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt

from basis.cli.init.config import (
    COLLAPSIBLE_MODES,
    COLLAPSIBLE_NONE,
    PARADIGM_APP,
    PARADIGM_SITE,
    PARADIGMS,
    THEMES,
    ShellConfig,
)


class WizardAborted(Exception):
    """Raised when the user interrupts the wizard (Ctrl-C)."""


@dataclass(frozen=True)
class Question:
    """One wizard step. ``when`` is a predicate over the answers-so-far dict."""

    id: str
    kind: str  # "text" | "confirm" | "choice"
    label: str
    default: Any = None
    choices: tuple[str, ...] = ()
    when: Callable[[dict], bool] = lambda answers: True


@dataclass(frozen=True)
class QuestionGroup:
    """A labelled batch of questions; a "current plan" panel is shown after it."""

    title: str
    questions: tuple[Question, ...]


def _when_app(answers: dict) -> bool:
    return answers.get("paradigm") == PARADIGM_APP


def _when_site(answers: dict) -> bool:
    return answers.get("paradigm") == PARADIGM_SITE


QUESTION_GROUPS: tuple[QuestionGroup, ...] = (
    QuestionGroup("0 · Project", (
        Question("project_name", "text", "Project / package name:", default=""),
    )),
    QuestionGroup("A · Shell paradigm", (
        Question("paradigm", "choice", "Shell paradigm:", default=PARADIGM_APP,
                 choices=PARADIGMS),
    )),
    QuestionGroup("B · Top-level Stack", (
        Question("titlebar", "confirm", "Include a Titlebar?", default=True, when=_when_app),
        Question("statusbar", "confirm", "Include a Statusbar?", default=True, when=_when_app),
        Question("activitybar", "confirm", "Include an ActivityBar?", default=True, when=_when_app),
        Question("sidebar_left", "confirm", "Include a Left Sidebar?", default=True, when=_when_app),
        Question("sidebar_left_collapsible", "choice",
                 "Left sidebar collapse (none/icon/offcanvas):", default=COLLAPSIBLE_NONE,
                 choices=COLLAPSIBLE_MODES,
                 when=lambda a: _when_app(a) and a.get("sidebar_left", True)),
        Question("sidebar_right", "confirm", "Include a Right Sidebar?", default=False, when=_when_app),
        Question("header", "confirm", "Include a Header (nav)?", default=True, when=_when_site),
        Question("sticky_header", "confirm", "Make the header sticky?", default=False,
                 when=lambda a: _when_site(a) and a.get("header", True)),
        Question("footer", "confirm", "Include a Footer?", default=True, when=_when_site),
    )),
    QuestionGroup("C · Extras", (
        Question("theme", "choice", "Theme seed:", default="dark", choices=THEMES),
        Question("demo", "confirm", "Generate demo content?", default=True),
        Question("example_store", "confirm", "Generate an example store?", default=True),
        Question("example_plugin", "confirm", "Generate an example plugin?", default=True),
        Question("use_db", "confirm", "Wire up SQLModel DB? (deferred)", default=False),
    )),
)


def default_answers(project_name_default: str | None = None) -> dict:
    """All question defaults as a flat dict (project name overridable)."""
    answers: dict = {}
    for group in QUESTION_GROUPS:
        for q in group.questions:
            answers[q.id] = q.default
    if project_name_default:
        answers["project_name"] = project_name_default
    return answers


def iter_active_questions(answers: dict) -> list[Question]:
    """The questions whose ``when`` predicate passes for ``answers`` (in order)."""
    return [q for group in QUESTION_GROUPS for q in group.questions if q.when(answers)]


def build_config(answers: dict) -> ShellConfig:
    """Validate + build a ``ShellConfig`` from wizard answers."""
    cfg = ShellConfig.from_flags(**answers)
    cfg.validate()
    return cfg


# --- interactive driver ---------------------------------------------------

def _ask(q: Question, answers: dict, console: Console) -> Any:
    # Default from the current answer value (pre-filled defaults, e.g. the
    # project name from the cwd), falling back to the question's own default.
    current = answers.get(q.id, q.default)
    if q.kind == "text":
        return Prompt.ask(q.label, default=str(current), console=console)
    if q.kind == "confirm":
        return Confirm.ask(q.label, default=bool(current), console=console)
    if q.kind == "choice":
        return Prompt.ask(q.label, choices=list(q.choices), default=str(current), console=console)
    raise ValueError(f"unknown question kind {q.kind!r}")


def _summary_text(answers: dict) -> str:
    paradigm = "Application (workbench)" if answers.get("paradigm") == PARADIGM_APP else "Website"
    lines = [
        f"Project:  {answers.get('project_name') or '—'}",
        f"Paradigm: {paradigm}",
    ]
    if answers.get("paradigm") == PARADIGM_APP:
        chrome = [
            n for n, on in (
                ("title bar", answers.get("titlebar")),
                ("status bar", answers.get("statusbar")),
                ("activity bar", answers.get("activitybar")),
                ("left sidebar", answers.get("sidebar_left")),
                ("right sidebar", answers.get("sidebar_right")),
            ) if on
        ]
    else:
        chrome = [
            n for n, on in (
                ("header", answers.get("header")),
                ("footer", answers.get("footer")),
            ) if on
        ]
    lines.append("Chrome:   " + (", ".join(chrome) if chrome else "(none)"))
    extras = [
        n for n, on in (
            ("demo", answers.get("demo")),
            ("example store", answers.get("example_store")),
            ("example plugin", answers.get("example_plugin")),
        ) if on
    ]
    lines.append("Extras:   " + (", ".join(extras) if extras else "(none)"))
    return "\n".join(lines)


def _show_summary(group: QuestionGroup, answers: dict, console: Console) -> None:
    console.print(Panel(
        _summary_text(answers),
        title=f"{group.title} — current plan",
        border_style="dim",
    ))


def run_wizard(
    *,
    initial: dict | None = None,
    project_name_default: str | None = None,
    prompter: Callable[[Question, dict, Console], Any] | None = None,
    console: Console | None = None,
) -> ShellConfig:
    """Run the interactive wizard and return a validated ``ShellConfig``.

    ``initial`` pre-fills answers and skips those questions (used by the CLI to
    pass e.g. the project name from ``basis init myapp``); ``prompter`` is the
    ask function (injectable for tests); Ctrl-C aborts with ``WizardAborted``.
    """
    console = console or Console()
    prompter = prompter or _ask
    provided = set(initial or {})
    answers = default_answers(project_name_default or Path.cwd().name)
    if initial:
        answers.update(initial)
    try:
        for group in QUESTION_GROUPS:
            for q in group.questions:
                if q.id in provided:
                    continue
                if not q.when(answers):
                    continue
                answers[q.id] = prompter(q, answers, console)
            _show_summary(group, answers, console)
    except KeyboardInterrupt:
        console.print("\n[dim]Aborted — no files were created.[/]")
        raise WizardAborted() from None
    return build_config(answers)
