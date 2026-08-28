"""The declarative manifest of every file ``basis init`` can generate.

This is the "cookiecutter.json" analog: adding a new generated file is a single
``TemplateFile`` row (plus the ``.j2`` template in ``templates/`` and, if it
needs new values, keys in ``layout.build_context``) — never writer-path code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from basis.cli.init.config import PARADIGM_APP, ShellConfig


@dataclass(frozen=True)
class TemplateFile:
    """One generated file: where it goes, what template renders it, when."""

    dest: str  # "src/{slug}/components/titlebar.py"
    source: str  # "components/titlebar.py.j2"
    when: Callable[[ShellConfig], bool] = lambda cfg: True  # include predicate
    label: str = ""  # rich-tree label override


def when_app(*part_flags: str) -> Callable[[ShellConfig], bool]:
    """A ``when`` predicate: only in the workbench (app) paradigm, all parts on."""

    def _pred(cfg: ShellConfig) -> bool:
        return cfg.paradigm == PARADIGM_APP and all(getattr(cfg, f) for f in part_flags)

    return _pred


TEMPLATE_FILES: tuple[TemplateFile, ...] = (
    TemplateFile("pyproject.toml", "pyproject.toml.j2"),
    TemplateFile("src/{slug}/__init__.py", "__init__.py.j2"),
    TemplateFile("src/{slug}/components/page.py", "page.py.j2"),
    TemplateFile("src/{slug}/README.md", "README.md.j2"),
    TemplateFile(".gitignore", ".gitignore.j2"),
    TemplateFile("src/{slug}/components/__init__.py", "components/__init__.py.j2"),
    TemplateFile("src/{slug}/components/app_container.py", "components/app_container.py.j2"),
    TemplateFile("src/{slug}/components/titlebar.py", "components/titlebar.py.j2",
                 when=when_app("titlebar")),
    TemplateFile("src/{slug}/components/statusbar.py", "components/statusbar.py.j2",
                 when=when_app("statusbar")),
    TemplateFile("src/{slug}/components/activitybar.py", "components/activitybar.py.j2",
                 when=when_app("activitybar")),
    TemplateFile("src/{slug}/components/sidebar.py", "components/sidebar.py.j2",
                 when=lambda c: c.paradigm == PARADIGM_APP and (c.sidebar_left or c.sidebar_right)),
    TemplateFile("src/{slug}/stores/__init__.py", "stores/__init__.py.j2",
                 when=lambda c: c.example_store),
    TemplateFile("src/{slug}/stores/app_state.py", "stores/app_state.py.j2",
                 when=lambda c: c.example_store),
    TemplateFile("src/{slug}/plugins/__init__.py", "plugins/__init__.py.j2",
                 when=lambda c: c.example_plugin),
    TemplateFile("src/{slug}/plugins/demo.py", "plugins/demo.py.j2",
                 when=lambda c: c.example_plugin),
    TemplateFile("src/{slug}/static/app.css", "static/app.css.j2"),
)


def filter_files(config: ShellConfig) -> list[TemplateFile]:
    """The subset of ``TEMPLATE_FILES`` that apply to ``config``, in order."""
    return [t for t in TEMPLATE_FILES if t.when(config)]
