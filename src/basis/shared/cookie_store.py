"""A ``Store`` that persists a set of user-preference fields to a cookie.

Basis already has two generic store hooks that core calls on *any* store that
defines them — the SSR/CSR initial-state paths (``page.py`` / ``render.py``) and
the RPC handler (``rpc.py``):

* ``apply_request(request)`` — read persisted prefs before rendering / acting,
* ``persist_prefs()``         — write the cookie after a pref-changing action.

:class:`CookieStore` implements both generically: a subclass declares
``cookie_name`` and ``persisted_fields`` (the attribute names persisted into the
cookie), overrides :meth:`_payload` / :meth:`_apply_payload` when the persisted
shape isn't a flat projection of those fields (e.g. the theme store's
``dark_mode`` bool coercion), and calls :meth:`_mark_dirty` inside its mutating
server actions. Dirty tracking is automatic — only a changed preference
rewrites the cookie, and the framework never interprets the payload (it just
round-trips ``(cookie_name, cookie_value)``).

This is the shared primitive behind ``$theme``'s ``basis_theme`` cookie
(ROADMAP-THEMING.md §4.2 / §6.5.3); future preference stores (sidebar state,
layout, locale, …) subclass it the same way.
"""

import json

from basis.shared.store import IS_CLIENT, Store


class CookieStore(Store):
    """Base for preference stores persisted to a cookie (e.g. ``$theme``).

    Subclass contract:
      * ``cookie_name`` — the cookie key (required to actually persist).
      * ``persisted_fields`` — attribute names saved into the cookie (used by the
        default :meth:`_payload` / :meth:`_apply_payload`; override either for a
        custom shape).
      * call :meth:`_mark_dirty` in any mutating server action so the RPC
        response rewrites the cookie.
    """

    cookie_name: str | None = None
    persisted_fields: tuple[str, ...] = ()

    # ── subclass hooks ──────────────────────────────────────────────────

    def _mark_dirty(self) -> None:
        """Flag that persisted prefs changed; the next ``persist_prefs()`` call
        (the RPC response) rewrites the cookie."""
        self.__dict__["_prefs_dirty"] = True

    def _payload(self) -> dict:
        """The JSON payload to persist — a flat projection of ``persisted_fields``."""
        return {f: getattr(self, f, None) for f in self.persisted_fields}

    def _apply_payload(self, data: dict) -> None:
        """Hydrate this store from a decoded cookie payload (flat projection)."""
        for f in self.persisted_fields:
            if f in data:
                setattr(self, f, data[f])

    # ── framework hooks (core calls these generically — see rpc/ssr/page) ──

    def persist_prefs(self):
        """Return ``(cookie_name, cookie_value)`` when prefs changed since the
        last action, else ``None``. Called by the RPC handler after a server
        action so the response sets the cookie."""
        if not self.cookie_name:
            return None
        if not getattr(self, "_prefs_dirty", False):
            return None
        self.__dict__["_prefs_dirty"] = False
        return (self.cookie_name, json.dumps(self._payload()))

    def apply_request(self, request) -> None:
        """Server-side only: read the cookie and apply persisted prefs so the
        first paint / action already reflects them. Called by the initial-state
        generation and the RPC handler on any store that defines it."""
        if IS_CLIENT:
            return
        if not self.cookie_name:
            return
        try:
            raw = request.cookies.get(self.cookie_name) if hasattr(request, "cookies") else None
        except Exception:
            return
        if not raw:
            return
        try:
            data = json.loads(raw)
        except Exception:
            return
        self._apply_payload(data)
