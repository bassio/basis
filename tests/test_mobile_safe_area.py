"""Safe-area insets as theme tokens.

The four ``safe_area_*`` slots default to ``env(safe-area-inset-*)``, so the
theme provider emits ``--safe-area-*`` on ``:root`` and screen-edge chrome pads
with ``var(--safe-area-*)``. That makes the whole framework notch-aware through
the token system users already know — one theme answer, every component
inherits — instead of each component hand-rolling ``env()``.
"""

from basis.plugins.theme.default import DEFAULT_TOKENS
from basis.plugins.theme.schema import (
    TOKEN_SLOTS,
    ThemeTokens,
    _valid_for,
    css_var,
)

SAFE_AREA_SLOTS = (
    "safe_area_top",
    "safe_area_right",
    "safe_area_bottom",
    "safe_area_left",
)


def _inset_of(slot: str) -> str:
    return slot[len("safe_area_"):]


# --- schema: the slots exist, typed as lengths -------------------------------

def test_safe_area_slots_declared_as_size():
    for slot in SAFE_AREA_SLOTS:
        assert TOKEN_SLOTS[slot] == "size"
    # kebab-case CSS var names match the slot convention.
    assert css_var("safe_area_top") == "--safe-area-top"
    assert css_var("safe_area_bottom") == "--safe-area-bottom"


def test_theme_tokens_has_a_field_per_safe_area_slot():
    tokens = ThemeTokens()
    for slot in SAFE_AREA_SLOTS:
        assert hasattr(tokens, slot)


def test_default_theme_safe_area_values_are_env_insets_with_zero_fallback():
    for slot in SAFE_AREA_SLOTS:
        assert getattr(DEFAULT_TOKENS, slot) == f"env(safe-area-inset-{_inset_of(slot)}, 0px)"


# --- validation: env()/calc() are valid "size" values ------------------------

def test_size_validation_accepts_css_functions_and_lengths():
    # The safe-area defaults (env) and dynamic lengths (calc) must validate.
    assert _valid_for("size", "env(safe-area-inset-top, 0px)")
    assert _valid_for("size", "env(safe-area-inset-top)")
    assert _valid_for("size", "calc(100dvh - 48px)")
    assert _valid_for("size", "var(--some-length)")
    assert _valid_for("size", "0")
    assert _valid_for("size", "1rem")
    # ...while junk still falls back (dev warning, never an error).
    assert not _valid_for("size", "banana")
    assert not _valid_for("size", "")


def test_theme_tokens_round_trips_env_safe_area_values():
    tokens = ThemeTokens.from_dict(
        {"safe_area_top": "env(safe-area-inset-top, 12px)"},
        base=DEFAULT_TOKENS,
    )
    assert tokens.safe_area_top == "env(safe-area-inset-top, 12px)"
    # A missing slot falls back to the base theme's env() inset.
    assert tokens.safe_area_bottom == DEFAULT_TOKENS.safe_area_bottom


# --- provider: --safe-area-* emitted on :root --------------------------------

def _provider_page():
    import basis.plugins.theme  # noqa: F401  # registers <ui-theme-provider>

    from basis.server.app import Basis
    from basis.shared.component import Component
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        template = "<div><ui-theme-provider></ui-theme-provider></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    return app


def test_provider_emits_safe_area_vars_into_root():
    from fastapi.testclient import TestClient

    html = TestClient(_provider_page()).get("/demo").text
    for slot in SAFE_AREA_SLOTS:
        expected = f"{css_var(slot)}: env(safe-area-inset-{_inset_of(slot)}, 0px)"
        assert expected in html, expected


# --- consumers: the shell chrome pads with the tokens ------------------------

def test_shell_chrome_consumes_safe_area_tokens():
    from basis.plugins.shell.status_bar import StatusBar
    from basis.plugins.shell.title_bar import TitleBar

    # The class API resolves the stylesheet whatever form `style` is declared in.
    title_css = TitleBar._get_style_string()
    status_css = StatusBar._get_style_string()

    assert "padding-top: var(--safe-area-top, env(safe-area-inset-top, 0px))" in title_css
    assert "padding-bottom: var(--safe-area-bottom, env(safe-area-inset-bottom, 0px))" in status_css
    # The raw env() call is now only the fallback, never the primary value.
    assert "padding-top: env(safe-area-inset-top, 0px)" not in title_css
    assert "padding-bottom: env(safe-area-inset-bottom, 0px)" not in status_css
