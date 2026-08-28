"""The ``$theme`` store — reactive design tokens + the active-theme control plane
(ROADMAP-THEMING.md §4.2 / §6.5.3).

API-compatible with the pre-P3 store (token attrs, ``dark_mode``,
``toggle_dark_mode()``) plus the P3 control plane: ``active_theme``,
``set_theme(id)`` / ``set_mode(mode)`` / ``set_accent(value)`` server actions.
Preferences persist to the ``basis_theme`` cookie via the shared
:class:`~basis.shared.cookie_store.CookieStore` base (no FOUC on reload).

The store is app-bound (``_requires_app``) so ``set_theme`` can resolve a
definition from the app's theme registrations; its token attributes are the
source of truth (not an app projection), so it is a plain cookie store with the
app attached, not an ``AppStateStore``.
"""

from basis.shared.actions import server_action
from basis.shared.cookie_store import CookieStore
from basis.shared.store import IS_CLIENT
from basis.plugins.theme.default import DEFAULT_DEFINITION, DEFAULT_TOKENS
from basis.plugins.theme.schema import ThemeDefinition, TOKEN_SLOTS

#: The cookie name for persisted theme prefs (active_theme / dark_mode / accent).
PREFS_COOKIE = "basis_theme"


def _resolve_theme_definition(app, theme_id: str):
    """Resolve a :class:`ThemeDefinition` by id from the app's *enabled* theme
    registrations (``kind == "theme"``), falling back to the built-in default.

    Disabled (disposed) theme registrations are skipped — a disabled theme is
    not applicable, so resolving it returns ``None`` (callers fall back to the
    default). Returns ``None`` when the id matches neither an enabled theme nor
    the default.
    """
    if app is not None:
        registrations = getattr(app, "_plugin_registrations", {})
        for reg in registrations.values():
            if getattr(reg, "disposed", False):
                continue
            plugin = reg.plugin
            if getattr(plugin, "kind", "") == "theme":
                definition = getattr(plugin, "definition", None)
                if definition is not None and getattr(definition, "id", None) == theme_id:
                    return definition
    if theme_id == DEFAULT_DEFINITION.id:
        return DEFAULT_DEFINITION
    return None


class ThemeStore(CookieStore):
    """
    A reactive store for design tokens and the active theme.
    """

    _requires_app = True  # set_theme resolves definitions from app registrations

    # Persisted prefs: the cookie holds these three user preferences; the derived
    # token attributes are NOT persisted (they re-derive from the definition when
    # prefs are applied — see ``_apply_payload``).
    cookie_name = PREFS_COOKIE

    def __init__(self, name="theme", definition: ThemeDefinition | None = None):
        super().__init__(name)
        # Store subclass footgun: assigning instance attrs after
        # super().__init__() would CLOBBER the SSR-hydrated values (hydration
        # runs inside Store.__init__). Only apply defaults when nothing was
        # hydrated — otherwise a persisted theme / seed is lost.
        if getattr(self, "_hydrated_from_ssr", False):
            return

        self.__dict__["_definition"] = definition or DEFAULT_DEFINITION
        self.dark_mode = False
        self.active_theme = self._definition.id
        self.data_theme = self._definition.data_theme
        self.accent = None  # user accent override (unset → theme's accent)

        # Reactive token attributes — the exact names the UI/shell consume
        # (docs/04_components/ui-components.md). Missing/invalid slots fall
        # back to the default theme (themes are overlays).
        base = self._definition.tokens
        for slot in TOKEN_SLOTS:
            value = getattr(base, slot) or getattr(DEFAULT_TOKENS, slot, "")
            setattr(self, slot, value)

    # ── theme switching (server actions — authoritative new_state + cookie) ──

    @server_action
    def set_theme(self, theme_id: str) -> str:
        """Apply a theme by id: resolve its definition (from the app's theme
        registrations, or the built-in default for ``"basis"``), re-derive the
        token attributes, and mark the pref for the ``basis_theme`` cookie."""
        definition = _resolve_theme_definition(self.__dict__.get("_app"), theme_id)
        if definition is None:
            raise ValueError(f"Unknown theme '{theme_id}'")
        self._apply_definition(definition)
        self.active_theme = theme_id
        self._mark_dirty()
        return f"applied {theme_id}"

    @server_action
    def set_mode(self, mode: str) -> str:
        """Set the color mode (``"light"`` / ``"dark"``), a user preference
        layered over the active theme."""
        if mode not in ("light", "dark"):
            raise ValueError(f"Unknown mode '{mode}' (expected 'light' or 'dark')")
        self.dark_mode = mode == "dark"
        self._mark_dirty()
        return f"mode {mode}"

    @server_action
    def set_accent(self, value: str) -> str:
        """Override the accent color (VS Code-style user customization layered
        over the active theme). ``accent_color`` is replaced; ``accent_bg`` /
        ``accent_text`` stay theme-derived for now (P3 scope)."""
        if not isinstance(value, str) or not value.strip():
            raise ValueError("accent must be a CSS color string")
        value = value.strip()
        self.accent = value
        self.accent_color = value
        self._mark_dirty()
        return f"accent {self.accent}"

    def _apply_definition(self, definition: ThemeDefinition) -> None:
        """Re-derive the reactive token attributes from a definition."""
        self.__dict__["_definition"] = definition
        self.data_theme = definition.data_theme
        base = definition.tokens
        for slot in TOKEN_SLOTS:
            value = getattr(base, slot) or getattr(DEFAULT_TOKENS, slot, "")
            setattr(self, slot, value)

    # ── cookie payload (CookieStore hooks — core calls these generically) ──

    def _payload(self) -> dict:
        """The prefs written to the ``basis_theme`` cookie.

        Kept as the exact historical JSON shape (bool-coerced ``dark_mode``,
        ``basis`` default theme) so already-set cookies round-trip unchanged.
        """
        return {
            "active_theme": getattr(self, "active_theme", "basis"),
            "dark_mode": bool(getattr(self, "dark_mode", False)),
            "accent": getattr(self, "accent", None),
        }

    def _apply_payload(self, prefs: dict) -> None:
        """Hydrate theme prefs from a decoded cookie, resolving the definition so
        the token attributes re-derive (falls back to ``basis`` if the saved
        theme is no longer available — disabling a theme unwinds on the next
        render, P4)."""
        theme_id = prefs.get("active_theme")
        if theme_id:
            app = self.__dict__.get("_app")
            definition = _resolve_theme_definition(app, theme_id)
            if definition is None:
                definition = DEFAULT_DEFINITION
                theme_id = DEFAULT_DEFINITION.id
            self._apply_definition(definition)
            self.active_theme = theme_id
        if "dark_mode" in prefs:
            self.dark_mode = bool(prefs["dark_mode"])
        if prefs.get("accent"):
            self.accent = prefs["accent"]
            self.accent_color = prefs["accent"]

    # ── the demo toggle (client-side reactive) ──────────────────────────────

    def toggle_dark_mode(self, event=None):
        """Flip between light and dark mode.

        Bound directly as a click handler (e.g. ``onclick="{$theme.toggle_dark_mode}"``).
        Client-side reactive flip, then persists via the ``set_mode`` server
        action (fire-and-forget) so a reload keeps the choice.
        """
        self.dark_mode = not self.dark_mode
        if IS_CLIENT:
            import asyncio
            try:
                asyncio.ensure_future(
                    self.set_mode("dark" if self.dark_mode else "light")
                )
            except Exception:
                pass
