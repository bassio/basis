"""The ``<ui-theme-provider>`` element — injects design tokens as CSS variables
(ROADMAP-THEMING.md §4.3)."""

from basis.shared.component import Component
from basis.shared.reactive import computed
from basis.plugins.theme.default import DEFAULT_TOKENS
from basis.plugins.theme.schema import TOKEN_SLOTS, css_var


class ThemeProvider(Component):
    """
    Component that injects reactive CSS variables into the page.

    ``tokens_css`` recomputes whenever ``$theme`` changes, so flipping
    ``dark_mode`` (or changing any token) re-skins the whole app — no component
    edits. After SSR hydration the document root is stamped with
    ``data-theme`` / ``data-theme-mode`` so app CSS can hook
    ``:root[data-theme=…]`` / ``:root[data-theme-mode=…]`` (the attribute
    reflects the hydrated state; live token changes are driven by the reactive
    CSS variables).
    """
    __tag__ = "ui-theme-provider"

    def style(self):
        return """
        ui-theme-provider {
            display: contents;
        }
        """

    @computed(dependencies=["$theme"])
    def tokens_css(self):
        # Rules are generated from the schema's slot list — the single source
        # of truth — so every token becomes exactly one CSS variable (no
        # hardcoded / duplicated rules). Missing values fall back to the
        # default theme.
        t = self.__class__.S['theme']
        rules = []
        for slot in TOKEN_SLOTS:
            value = getattr(t, slot, None) or getattr(DEFAULT_TOKENS, slot, "")
            if value:
                rules.append(f"{css_var(slot)}: {value}")

        joined_rules = "; ".join(rules)
        # ``dark_mode`` decides which side of every light-dark() token wins. With
        # ``color-scheme: light dark`` (auto) the OS preference would override the
        # store, making the toggle a no-op — so pick a deterministic scheme here.
        scheme = "dark" if getattr(t, "dark_mode", False) else "light"
        return f":root {{ color-scheme: {scheme}; {joined_rules}}}"

    def on_hydrated(self):
        """Client-only (never called on the server). Stamp the document root with
        the active theme + mode so app CSS can hook ``:root[data-theme=…]`` /
        ``:root[data-theme-mode=…]``."""
        try:
            t = self.__class__.S.get("theme")
            if t is None:
                return
            root = document.documentElement
            root.dataset.theme = getattr(t, "data_theme", "basis") or "basis"
            root.dataset.themeMode = "dark" if getattr(t, "dark_mode", False) else "light"
        except Exception:
            pass

    def template(self):
        """
        <style id="theme-provider" text-content="{tokens_css}"></style>
        """
