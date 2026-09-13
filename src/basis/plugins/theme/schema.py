"""The theme schema — the declarative token manifest.

The theming contract: named, typed design tokens that
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
    # Safe-area insets (notch / home indicator). Defaults
    # are ``env(safe-area-inset-*)`` (0 on desktops and un-notched phones), so
    # screen-edge chrome pads with ``var(--safe-area-*)`` and is notch-aware
    # through the theme — one answer, every component inherits.
    "safe_area_top": "size",
    "safe_area_right": "size",
    "safe_area_bottom": "size",
    "safe_area_left": "size",
}


def css_var(slot: str) -> str:
    """The CSS custom-property name for a token slot (``bg_primary`` → ``--bg-primary``)."""
    return "--" + slot.replace("_", "-")


# Lightweight value validation — dev warnings, never errors (a bad value
# degrades to the default, matching the "themes are overlays" rule).
_SIZE_UNITS = ("px", "rem", "em", "%", "vw", "vh", "ch", "ex", "pt", "pc")
#: CSS value functions that resolve to a length and must pass the "size" check
#: (e.g. ``env(safe-area-inset-top, 0px)``, ``calc(100dvh - 48px)``).
_SIZE_FUNCS = ("env(", "var(", "calc(", "min(", "max(", "clamp(")


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
        if v.lower().startswith(_SIZE_FUNCS):
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
    # Safe-area insets — default to the browser's env() values; a theme may
    # override them (e.g. a fixed inset for a kiosk shell).
    safe_area_top: str | None = None
    safe_area_right: str | None = None
    safe_area_bottom: str | None = None
    safe_area_left: str | None = None

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

    The full package contract is richer; only the fields the
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
    #: Browser/OS chrome color (``theme-color`` meta) per color mode. Optional,
    #: manifest-level DESIGN data, NOT token
    #: slots / CSS vars: a theme's browser-chrome color is a real design
    #: decision, never a string-parsed side effect. When unset,
    #: :func:`resolve_theme_color` falls back to a best-effort ``light-dark()``
    #: parse of ``tokens.bg_primary``, then to the spec default.
    theme_color_light: str | None = None
    theme_color_dark: str | None = None
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
        for mode in ("theme_color_light", "theme_color_dark"):
            value = getattr(self, mode)
            if value is not None and (not isinstance(value, str) or not value.strip()):
                problems.append(f"{mode} must be a color string when set")
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


# ---------------------------------------------------------------------------
# Browser/OS chrome color resolution
# ---------------------------------------------------------------------------

#: Spec-default chrome colors used when a definition declares no
#: ``theme_color_*`` field AND its ``bg_primary`` carries no parseable
#: ``light-dark()`` pair.
DEFAULT_THEME_COLOR_LIGHT = "#f5f5f7"
DEFAULT_THEME_COLOR_DARK = "#1e1e2e"


def _split_top_level(value: str, sep: str = ",") -> list[str]:
    """Split ``value`` on *sep*, ignoring separators inside parentheses (so an
    ``rgba(...)`` inside a ``light-dark(...)`` pair is not split)."""
    parts: list[str] = []
    cur: list[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        if ch == sep and depth == 0:
            parts.append("".join(cur).strip())
            cur = []
        else:
            cur.append(ch)
    if cur:
        parts.append("".join(cur).strip())
    return parts


def _parse_light_dark(value: str | None) -> tuple[str, str] | None:
    """Best-effort parse of a ``light-dark(<light>, <dark>)`` token value into
    its two CSS colors. ``None`` when the value isn't that shape."""
    import re

    if not value:
        return None
    m = re.search(r"light-dark\((.*)\)", value)
    if not m:
        return None
    parts = _split_top_level(m.group(1))
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def resolve_theme_color(definition: "ThemeDefinition", dark: bool) -> str:
    """The browser/OS chrome color (``theme-color`` meta) for *definition* in
    the given color mode.

    Precedence (Decision C — theme-color is explicit theme data, never derived
    by string-parsing):
    1. the definition's ``theme_color_light`` / ``theme_color_dark`` field (the
       real design decision);
    2. a best-effort ``light-dark()`` parse of ``tokens.bg_primary`` (for
       themes that don't declare the field yet);
    3. the spec default (:data:`DEFAULT_THEME_COLOR_LIGHT` /
       :data:`DEFAULT_THEME_COLOR_DARK`).
    """
    explicit = definition.theme_color_dark if dark else definition.theme_color_light
    if explicit:
        return explicit
    bg = getattr(getattr(definition, "tokens", None), "bg_primary", None) or ""
    pair = _parse_light_dark(bg)
    if pair:
        return pair[1] if dark else pair[0]
    return DEFAULT_THEME_COLOR_DARK if dark else DEFAULT_THEME_COLOR_LIGHT
