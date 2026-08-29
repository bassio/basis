"""The ``ambient`` theme definition + plugin instance.

A distinct, tasteful alternative to the built-in ``basis`` default — warm paper
light mode, deep blue-black dark mode, and a teal accent — proving the
theme-package format end-to-end (discovery, catalog, apply, disable).

The tokens are validated on construction (`ThemeDefinition.__post_init__`), so
this module doubles as the "a valid theme package looks like this" reference.
"""

from basis.plugins.theme.schema import ThemeDefinition, ThemeTokens
from basis.plugins.theme.theme import Theme


definition = ThemeDefinition(
    id="ambient",
    name="Basis Ambient",
    version="1.0.0",
    author="Basis",
    description=(
        "A calm, teal-accented alternative to the default — the in-tree "
        "dogfood proving the theme-package format (ROADMAP-THEMING §6.5)."
    ),
    data_theme="ambient",
    color_scheme="auto",
    tokens=ThemeTokens(
        # Background — warm paper light / deep blue-black dark
        bg_primary="light-dark(#F6F5F0, #171B24)",
        bg_secondary="light-dark(#FDFCF8, #1F2430)",
        bg_tertiary="light-dark(#ECEAE2, #262C3A)",

        # Text
        text_primary="light-dark(#1F242E, #E7EBF2)",
        text_secondary="light-dark(#5F6570, #A3AAB8)",
        text_muted="light-dark(#8A8E98, #6F7686)",

        # Accent — teal (vs. the default's indigo)
        accent_color="light-dark(#0E7490, #22D3EE)",
        accent_bg="light-dark(#DDF1F6, rgba(34, 211, 238, 0.14))",
        accent_text="light-dark(#0B5B70, #A5E7F5)",

        # Borders
        border_color="light-dark(#DDDBD2, #333A49)",
        border_soft="light-dark(#E7E5DC, #2A303E)",
        border_hover="light-dark(#C6C4B8, #47516A)",
        hover_bg="light-dark(rgba(0, 0, 0, 0.05), rgba(255, 255, 255, 0.08))",
        scrollbar_thumb="light-dark(#B9B7AC, #333A49)",

        # Typography (same system as the default)
        font_sans="'Inter', sans-serif",
        font_serif="'Source Serif 4', serif",
        font_mono="'IBM Plex Mono', monospace",

        # Shared tokens (same geometry as the default)
        radius_sm="0.25rem",
        radius_md="0.5rem",
        radius_lg="1rem",
        shadow_sm="0 1px 2px 0 rgba(0, 0, 0, 0.05)",
        shadow_md="0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
    ),
)

#: The module-level ``plugin`` instance (uniform entry-point convention).
plugin = Theme(definition=definition)
