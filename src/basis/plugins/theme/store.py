"""The ``$theme`` store — reactive design tokens + the active-theme control plane
(ROADMAP-THEMING.md §4.2 / §6.5.3).

API-compatible with the pre-P3 store (token attrs, ``dark_mode``,
``toggle_dark_mode()``) plus the P3 control plane: ``active_theme``,
``set_theme(id)`` / ``set_mode(mode)`` / ``set_accent(value)`` — all *dual-path*
methods (the client-side theme engine): on the client they apply locally and
persist by flushing the cookie directly (no RPC round trip); on the server they
apply and mark the cookie dirty. Preferences persist to the ``basis_theme``
cookie via the shared :class:`~basis.shared.cookie_store.CookieStore` base (no
FOUC on reload).

The store is app-bound (``_requires_app``) so ``set_theme`` can resolve a
definition from the app's theme registrations; its token attributes are the
source of truth (not an app projection), so it is a plain cookie store with the
app attached, not an ``AppStateStore``.
"""

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

    # ── theme switching (dual-path: client applies locally + flushes the ─────
    #    cookie directly; server applies + marks dirty for the RPC write) ─────

    def set_theme(self, theme_id: str) -> str:
        """Apply a theme by id.

        Resolves its definition (server: the app's theme registrations; client:
        dynamic-import the theme's package via the ``$themes`` catalog's
        ``module`` field), re-derives the token attributes, and persists the
        ``basis_theme`` cookie — on the client by writing it directly (no RPC),
        on the server by marking it dirty for the RPC response.
        """
        definition = self._resolve_definition(theme_id)
        if definition is None:
            raise ValueError(f"Unknown theme '{theme_id}'")
        self._apply_definition(definition)
        self.active_theme = theme_id
        self._mark_dirty()
        self._flush_cookie()
        return f"applied {theme_id}"

    def set_mode(self, mode: str) -> str:
        """Set the color mode (``"light"`` / ``"dark"``), a user preference
        layered over the active theme — applied locally + persisted (the client
        flushes the cookie directly; the server path marks it dirty)."""
        if mode not in ("light", "dark"):
            raise ValueError(f"Unknown mode '{mode}' (expected 'light' or 'dark')")
        self.dark_mode = mode == "dark"
        self._mark_dirty()
        self._flush_cookie()
        return f"mode {mode}"

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
        self._flush_cookie()
        return f"accent {self.accent}"

    def _resolve_definition(self, theme_id: str):
        """Resolve a :class:`ThemeDefinition` by id.

        Server: from the app's *enabled* theme registrations (falls back to the
        built-in default). Client: look up the ``$themes`` catalog, gate on
        ``state == "enabled"``, then dynamic-import the theme's package (served
        to the client VFS) and read its ``plugin.definition`` — cached per
        module. Returns the default for ``"basis"``; ``None`` when unknown.
        """
        if not IS_CLIENT:
            return _resolve_theme_definition(self.__dict__.get("_app"), theme_id)

        catalog = self._themes_catalog()
        for info in (catalog or {}).values():
            theme = info.get("theme") or {}
            if theme.get("id") != theme_id:
                continue
            # A disabled theme's VFS files are pruned — importing would fail, so
            # the enabled-state gate must run before the import.
            if info.get("state") != "enabled":
                return None
            module = theme.get("module")
            if not module:
                return None
            cache = self.__dict__.setdefault("_definition_cache", {})
            if module in cache:
                return cache[module]
            try:
                import importlib
                mod = importlib.import_module(module)
                definition = getattr(getattr(mod, "plugin", None), "definition", None)
            except Exception:
                definition = None
            cache[module] = definition
            return definition
        return _resolve_theme_definition(None, theme_id)

    def _themes_catalog(self):
        """The ``$themes`` catalog items on the client (the hydrated reactive
        view of the theme registry). ``None`` when the catalog isn't live."""
        try:
            from basis.shared.store import ensure_store
            from basis.plugins.theme.registry import ThemeRegistryStore
            return getattr(ensure_store("themes", ThemeRegistryStore), "items", None)
        except Exception:
            return None

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
        Flips locally (instant) and persists by flushing the ``basis_theme``
        cookie directly — no server round trip, so the choice survives reloads
        and theme switches.
        """
        self.dark_mode = not self.dark_mode
        self._mark_dirty()
        self._flush_cookie()
