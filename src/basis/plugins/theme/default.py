"""The built-in ``basis`` default theme (ROADMAP-THEMING.md §5).

A minimal, cohesive, token-only skin with light + dark variants (expressed as
``light-dark()`` pairs), intended as the baseline every theme competes with —
the default that a fresh ``basis init`` app renders.
"""

from basis.plugins.theme.schema import ThemeDefinition, ThemeTokens


DEFAULT_TOKENS = ThemeTokens(
    # Background — light is a warm paper gray; dark is a deep, slightly
    # cool blue-gray triad (primary / secondary / tertiary depth steps).
    bg_primary="light-dark(#F6F6F7, #1B2029)",     # page / canvas
    bg_secondary="light-dark(#FFFFFF, #222833)",   # panels: sidebar, titlebar, statusbar
    bg_tertiary="light-dark(#EEF0F3, #2A3140)",    # elevated: tab bar, cards

    # Text — muted keeps ≥~3:1 on both modes so secondary labels stay legible.
    text_primary="light-dark(#1E2431, #ECEEF2)",
    text_secondary="light-dark(#61636E, #A9AFC0)",
    text_muted="light-dark(#868A95, #767C90)",

    # Accent
    accent_color="light-dark(#6E5FD8, #9384F5)",
    accent_bg="light-dark(#EBE9F8, rgba(147, 132, 245, 0.16))",
    accent_text="light-dark(#5847C9, #B7ACF8)",

    # Borders
    border_color="light-dark(#E1E1E4, #3A4256)",
    border_soft="light-dark(#EAEAED, #2D3441)",
    border_hover="light-dark(#C9C9CE, #49536C)",
    hover_bg="light-dark(rgba(0, 0, 0, 0.04), rgba(255, 255, 255, 0.08))",
    scrollbar_thumb="light-dark(#BFC1C9, #3A4256)",

    # Typography
    font_sans="'Inter', sans-serif",
    font_serif="'Source Serif 4', serif",    # note titles / voice
    font_mono="'IBM Plex Mono', monospace",  # metadata, status bar, paths

    # Shared tokens
    radius_sm="0.25rem",
    radius_md="0.5rem",
    radius_lg="1rem",
    shadow_sm="0 1px 2px 0 rgba(0, 0, 0, 0.05)",
    shadow_md="0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)",
)


DEFAULT_DEFINITION = ThemeDefinition(
    id="basis",
    name="Basis Default",
    data_theme="basis",
    tokens=DEFAULT_TOKENS,
)
