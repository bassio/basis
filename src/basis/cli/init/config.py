"""``ShellConfig`` — the single answer record for ``basis init``.

One dataclass drives BOTH the interactive wizard (``wizard.py``) and the
flag-driven non-interactive path (``commands/init.py``), and is the input to
``layout.py`` (render context + file inventory) and the template registry's
``when`` predicates (``registry.py``).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, fields
from typing import Any

# Shell paradigms.
PARADIGM_APP = "app"
PARADIGM_SITE = "site"
PARADIGMS = (PARADIGM_APP, PARADIGM_SITE)

# Sidebar collapse modes (mirrors ``shell-sidebar`` collapsible prop).
COLLAPSIBLE_NONE = "none"
COLLAPSIBLE_ICON = "icon"
COLLAPSIBLE_OFFCANVAS = "offcanvas"
COLLAPSIBLE_MODES = (COLLAPSIBLE_NONE, COLLAPSIBLE_ICON, COLLAPSIBLE_OFFCANVAS)

# Theme seeds.
THEMES = ("dark", "light")


def slugify(name: str) -> str:
    """Normalise a project/package name into a valid Python identifier.

    Lowercases, maps dashes and any non-alphanumeric character to underscores,
    and prefixes a leading digit with ``_`` (a module name can't start with a
    digit).
    """
    slug = re.sub(r"[^a-zA-Z0-9_]", "_", name.strip().lower().replace("-", "_"))
    if slug and slug[0].isdigit():
        slug = "_" + slug
    return slug


@dataclass
class ShellConfig:
    """Every answer the wizard / flags can produce.

    ``validate()`` is the single place structural rules live (raised BEFORE any
    directory is created); paradigm-mismatched part flags (e.g. ``titlebar`` in
    site mode) are simply unused, never an error.
    """

    project_name: str = ""
    paradigm: str = PARADIGM_APP
    # --- workbench chrome ---
    titlebar: bool = True
    statusbar: bool = True
    activitybar: bool = True
    sidebar_left: bool = True
    sidebar_right: bool = False
    sidebar_left_collapsible: str = COLLAPSIBLE_NONE
    # --- site chrome ---
    header: bool = True
    footer: bool = True
    sticky_header: bool = False
    # --- shared / extras ---
    theme: str = "dark"
    demo: bool = True
    example_store: bool = True
    example_plugin: bool = True
    use_db: bool = False

    @property
    def package_slug(self) -> str:
        return slugify(self.project_name)

    def validate(self) -> None:
        """Raise ``ValueError`` on a structurally invalid config."""
        if not self.project_name or not self.project_name.strip():
            raise ValueError("Project name is required.")
        if not self.package_slug:
            raise ValueError(
                f"Project name {self.project_name!r} does not produce a valid "
                "Python package name."
            )
        if self.paradigm not in PARADIGMS:
            raise ValueError(
                f"Unknown shell paradigm {self.paradigm!r} (expected one of {PARADIGMS})."
            )
        if self.sidebar_left_collapsible not in COLLAPSIBLE_MODES:
            raise ValueError(
                f"Unknown sidebar collapse mode {self.sidebar_left_collapsible!r} "
                f"(expected one of {COLLAPSIBLE_MODES})."
            )
        if self.theme not in THEMES:
            raise ValueError(f"Unknown theme {self.theme!r} (expected one of {THEMES}).")

    def to_flags(self) -> dict[str, Any]:
        """All fields as a flat dict (for ``--config`` replay / flag round-trip)."""
        return asdict(self)

    @classmethod
    def from_flags(cls, **flags: Any) -> "ShellConfig":
        """Build a config from field kwargs; unknown field names raise."""
        known = {f.name for f in fields(cls)}
        unknown = set(flags) - known
        if unknown:
            raise ValueError(
                f"Unknown shell config option(s): {sorted(unknown)}. "
                f"Known: {sorted(known)}."
            )
        return cls(**flags)
