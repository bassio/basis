"""Turn a ``ShellConfig`` into the render context + file inventory.

``build_context`` produces the variable/flag mapping every ``.j2`` template may
reference (including derived booleans, so templates only ever test truthiness);
``build_inventory`` filters the registry by ``when``; ``dest_path`` resolves a
template's output path with ``{slug}`` substituted.
"""

from __future__ import annotations

from typing import Any

from basis.cli.init.config import PARADIGM_APP, PARADIGM_SITE, ShellConfig
from basis.cli.init.registry import TemplateFile, filter_files

# Default sizing props (Mantine AppShell-style: every dimension is a reactive
# prop with a sensible default). The generated root exposes these as class
# attrs and feeds them to the shell parts.
DEFAULT_SIZING: dict[str, str] = {
    "titlebar_height": "48px",
    "statusbar_height": "28px",
    "activitybar_width": "56px",
    "sidebar_left_width": "240px",
    "sidebar_right_width": "240px",
}


def project_title(config: ShellConfig) -> str:
    """A pretty page title from the project name ('my-app' -> 'My App')."""
    return config.project_name.replace("-", " ").replace("_", " ").strip().title()


def build_context(config: ShellConfig) -> dict[str, Any]:
    """The full context passed to every template render (single source of truth)."""
    return {
        # identity
        "project_name": config.project_name,
        "slug": config.package_slug,
        "project_title": project_title(config),
        "paradigm": config.paradigm,
        # paradigm-derived booleans (templates test truthiness only)
        "is_app": config.paradigm == PARADIGM_APP,
        "is_site": config.paradigm == PARADIGM_SITE,
        "has_any_sidebar": config.sidebar_left or config.sidebar_right,
        # part flags
        "titlebar": config.titlebar,
        "statusbar": config.statusbar,
        "activitybar": config.activitybar,
        "sidebar_left": config.sidebar_left,
        "sidebar_right": config.sidebar_right,
        "header": config.header,
        "footer": config.footer,
        "sticky_header": config.sticky_header,
        # extras
        "theme_seed": config.theme,
        "demo": config.demo,
        "example_store": config.example_store,
        "example_plugin": config.example_plugin,
        # sizing
        **DEFAULT_SIZING,
        "sidebar_left_collapsible": config.sidebar_left_collapsible,
    }


def build_inventory(config: ShellConfig) -> list[TemplateFile]:
    """The files that will be generated for ``config`` (registry ``when`` filter)."""
    return filter_files(config)


def dest_path(template: TemplateFile, config: ShellConfig) -> str:
    """Resolve a template's output path, substituting ``{slug}``."""
    return template.dest.format(slug=config.package_slug)
