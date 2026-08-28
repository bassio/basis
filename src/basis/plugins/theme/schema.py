"""The theme schema — the declarative token manifest.

The theming contract (ROADMAP-THEMING.md §4.1): named, typed design tokens that
a theme declares and the framework turns into CSS variables. ``TOKEN_SLOTS`` is
the single source of truth — ThemeStore's reactive token attrs, ThemeProvider's
``:root`` injection and a theme package's ``ThemeDefinition`` all speak the same
vocabulary, so:

- an **unknown slot** is a dev warning and is ignored (the schema can grow
  without breaking older themes),
- a **missing slot** falls back to the default theme's value (themes are
  overlays, not full re-declarations),
- a **wrongly-typed value** (e.g. a length in a color slot) is a dev warning and
  is ignored.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("basis.theme")

#: Theme ids are slugs: letter first, then letters/digits/'_'/'-' (they derive
#: the plugin name — a valid Python identifier after underscore substitution).
_THEME_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")

# Slot name → value kind. Kinds drive validation only; the CSS variable name is
# the slot's kebab-case form (``bg_primary`` → ``--bg-primary``).
TOKEN_SLOTS: dict[str, str] = {
    "bg_primary": "color",
    "bg_secondary": "color",
    "bg_tertiary": "color",
    "text_primary": "color",
    "text_secondary": "color",
    "text_muted": "color",
    "accent_color": "color",
    "accent_bg": "color",
    "accent_text": "color",
    "border_color": "color",
    "border_soft": "color",
    "border_hover": "color",
    "hover_bg": "color",
    "scrollbar_thumb": "color",
    "font_sans": "font",
    "font_serif": "font",
    "font_mono": "font",
    "radius_sm": "size",
    "radius_md": "size",
    "radius_lg": "size",
    "shadow_sm": "shadow",
    "shadow_md": "shadow",
}


def css_var(slot: str) -> str:
    """The CSS custom-property name for a token slot (``bg_primary`` → ``--bg-primary``)."""
    return "--" + slot.replace("_", "-")


# Lightweight value validation — dev warnings, never errors (a bad value
# degrades to the default, matching the "themes are overlays" rule).
_SIZE_UNITS = ("px", "rem", "em", "%", "vw", "vh", "ch", "ex", "pt", "pc")


def _valid_for(kind: str, value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    if kind == "color":
        # Reject obvious length values in a color slot (a likely author mistake).
        stripped = value.strip().lower()
        return not any(stripped.endswith(u) for u in _SIZE_UNITS)
    if kind == "size":
        v = value.strip()
        if v == "0":
            return True
        return any(v.endswith(u) for u in _SIZE_UNITS)
    if kind == "font":
        return len(value.strip()) >= 2
    if kind == "shadow":
        return " " in value.strip() or value.strip().startswith(("inset", "0"))
    return True


@dataclass
class ThemeTokens:
    """A theme's design-token values (one slot per field; ``None`` = fall back).

    Fields mirror ``TOKEN_SLOTS`` exactly; values are CSS strings — commonly
    ``light-dark(<light>, <dark>)`` pairs so one token adapts to both modes.
    """

    bg_primary: str | None = None
    bg_secondary: str | None = None
    bg_tertiary: str | None = None
    text_primary: str | None = None
    text_secondary: str | None = None
    text_muted: str | None = None
    accent_color: str | None = None
    accent_bg: str | None = None
    accent_text: str | None = None
    border_color: str | None = None
    border_soft: str | None = None
    border_hover: str | None = None
    hover_bg: str | None = None
    scrollbar_thumb: str | None = None
    font_sans: str | None = None
    font_serif: str | None = None
    font_mono: str | None = None
    radius_sm: str | None = None
    radius_md: str | None = None
    radius_lg: str | None = None
    shadow_sm: str | None = None
    shadow_md: str | None = None

    @classmethod
    def from_dict(
        cls,
        data: dict,
        base: "ThemeTokens | None" = None,
    ) -> "ThemeTokens":
        """Build tokens from a dict, warning on unknown slots and falling back
        to *base* (default theme) for missing / invalid slots."""
        base = base or ThemeTokens()
        values: dict[str, str | None] = {}
        for slot, kind in TOKEN_SLOTS.items():
            value = data.get(slot)
            if value is None:
                values[slot] = getattr(base, slot)
                continue
            if not _valid_for(kind, value):
                logger.warning(
                    f"[theme] token '{slot}' has an invalid {kind} value "
                    f"{value!r} — falling back to the default theme."
                )
                values[slot] = getattr(base, slot)
                continue
            values[slot] = value
        for unknown in set(data) - set(TOKEN_SLOTS):
            logger.warning(
                f"[theme] unknown token slot '{unknown}' ignored (not in the "
                f"theme schema)."
            )
        return cls(**values)


@dataclass
class ThemeDefinition:
    """A named theme — the manifest a theme package contributes.

    The full package contract is ROADMAP-THEMING.md §6; only the fields the
    mechanism consumes today (identity + tokens) are required. ``tokens`` is an
    overlay: missing slots fall back to the default theme.
    """

    id: str = "basis"
    name: str = "Basis Default"
    version: str = "1.0.0"
    author: str | None = None
    description: str | None = None
    data_theme: str = "basis"          # value for :root[data-theme=...] (app CSS hooks)
    color_scheme: str = "auto"         # "light" | "dark" | "auto"
    tokens: ThemeTokens = field(default_factory=ThemeTokens)
    css: str | None = None             # optional extra stylesheet path (theme plugin static file)
    fonts: list[str] = field(default_factory=list)
    preview: str | None = None
    settings_schema: dict | None = None
    requires: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        """Validate on construction (loud errors for a broken theme manifest)."""
        self.validate()

    def validate(self) -> "ThemeDefinition":
        """Validate the manifest, raising ``ValueError`` with a clear message.

        Runs automatically on construction and on demand (e.g. the ``basis
        theme apply`` CLI), so a broken theme package fails **loudly** at
        import/discovery (P4) — never silently at 3am in a browser. The
        built-in and in-tree themes pass; a community theme with a bad id,
        missing name, or invalid token value is rejected up front.
        """
        problems: list[str] = []
        if not isinstance(self.id, str) or not self.id:
            problems.append("id must be a non-empty string")
        elif not _THEME_ID_RE.match(self.id):
            problems.append(
                f"id {self.id!r} must start with a letter and use only letters, "
                f"digits, '_' or '-' (it derives the plugin name and static mount)"
            )
        if not isinstance(self.name, str) or not self.name.strip():
            problems.append("name must be a non-empty string")
        if not isinstance(self.data_theme, str) or not self.data_theme.strip():
            problems.append("data_theme must be a non-empty string")
        if self.color_scheme not in ("auto", "system", "light", "dark"):
            problems.append(
                f"color_scheme {self.color_scheme!r} must be one of "
                f"'auto', 'system', 'light', 'dark'"
            )
        for slot, kind in TOKEN_SLOTS.items():
            value = getattr(self.tokens, slot, None)
            if value is None:
                continue
            if not _valid_for(kind, value):
                problems.append(f"token '{slot}' has an invalid {kind} value {value!r}")
        if problems:
            raise ValueError(
                f"Invalid theme definition {self.id!r}:\n  - "
                + "\n  - ".join(problems)
            )
        return self
