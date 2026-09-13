"""The ``$meta`` document-meta store.

The dynamic half of the head-meta design: a tiny, name-keyed,
document-level reactive store for the handful of live ``<meta name=...>`` tags
that must react to state or be contributed by a plugin/component — today
``theme-color`` (follows ``$theme``). The static per-page half needs no
framework API: whole-page mount made a
Page's own ``<head>`` a live template region, so per-route tags
(``description``, ``og:*``, ``apple-*``) are simply authored in a ``Page``
subclass's template.

Core / Page-default store (like the plugin registry)
----------------------------------------------------
``$meta`` is a **framework control-plane store**, not a plugin-owned one:
- ``Page`` guarantees it exists on every page (``shared/page.py`` ``_load``;
  client entrypoint; ``FRAMEWORK_STORE_NAMES`` includes ``"meta"`` so it is
  serialized into ``#basis-initial-state`` even on a strict ``Page.stores``
  page), exactly like ``$plugins``.
- A plugin (e.g. theme) NEVER ``include_store``s it — it only **contributes
  items** (``add``/``upsert``) and records the disposer on its registration.
- **Empty ``items`` renders nothing**: the base ``Page.template()`` head loop
  over ``$meta.items`` emits zero ``<meta>`` elements when the list is empty,
  so an always-present-but-empty store is byte-stable (no head churn, no
  ``safe_eval`` error on pages without contributors).

Render + reactivity story (the ``$meta`` head loop, B.9): the base
``Page.template()`` renders ``$meta.items`` through a head ``<meta for>`` keyed
``LoopBinding`` (sibling repetition under ``<head>``, the same mechanism as the
component-style loop). Whole-page hydration keeps that loop alive, so a
plugin/component upserting into this store reconciles the live head node —
there is **no imperative ``head_sync`` reconciler**.

Item shape
----------
``items`` holds plain dicts ``{"key", "name", "content"}`` — the same shape on
the server, in ``#basis-initial-state`` and after client hydration, so the head
loop binds one shape everywhere and :meth:`Store.serialize` needs no
special-casing (the ModelStore lesson: don't send objects across the wire and
expect the same type back).

``key`` is the dedup identity (``name:theme-color``) and doubles as the loop's
reconciliation key. Metas are *name-keyed*: the document-level live channel
only carries ``name``/``content`` tags (``theme-color``, later ``color-scheme``
etc.). ``property``/``http-equiv`` metas are page-static and live in page
templates, never here.

Per-request SSR note (for contributors)
--------------------------------------
``Store._registry`` is cleared per request for SSR isolation (only the
persistent blueprint survives), so runtime adds made once at boot do NOT
survive into a later request's render. A contributor whose items are derived
from request state (``$theme``'s cookie) must re-seed per request — the
established seam is the ``apply_request(request)`` hook the render engines call
on every store in the registry (see ``server/render.py`` / ``shared/page.py``),
which recomputes ``items`` before the head loop's final paint and the
initial-state serialization.
"""

from basis.shared.store import Store, ensure_store


def _item_key(name: str) -> str:
    """The dedup / reconciliation key for a name-keyed meta (``theme-color`` →
    ``"name:theme-color"``)."""
    return f"name:{name}"


def ensure_meta_store() -> "MetaStore":
    """Return the ``$meta`` store, creating it if absent.

    Mirrors ``ensure_plugin_registry``: called by the Page ``_load`` (server,
    per request — the registry is cleared between requests) and the client
    entrypoints so ``$meta`` resolves on every page before the head loop
    mounts. Empty by default (``items == []`` → nothing renders).
    """
    return ensure_store("meta", MetaStore)


class MetaStore(Store):
    """Document-level, reactive, name-keyed head-meta store (registered under
    ``"meta"``).

    ``items`` is an ordered list of ``{"key", "name", "content"}`` dicts.
    Mutations reassign ``items`` so the ``$meta.items`` DAG edge fires — the
    trigger that re-renders the head ``<meta for>`` loop (B.9).
    """

    def __init__(self, name: str = "meta"):
        super().__init__(name)
        # Store-subclass footgun: never clobber SSR-hydrated items (hydration
        # runs inside Store.__init__, reading #basis-initial-state).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = []

    # ── contribution API (data-first, revertible; returns disposers) ──────

    def add(self, name: str, content: str) -> callable:
        """Append a meta unless that identity is already present.

        Returns a disposer that removes it again (``registration.disposers``
        pattern — plugin disable unwinds its head contribution).
        """
        key = _item_key(name)
        items = list(self.__dict__.get("items") or [])
        if any(it.get("key") == key for it in items):
            return lambda: None  # already present — nothing to do
        items.append({"key": key, "name": name, "content": content})
        self.items = items
        return lambda: self.remove(name)

    def upsert(self, name: str, content: str) -> callable:
        """Replace a meta with the same identity, or append it if absent.

        The single ``theme-color`` node is guaranteed (one node per identity);
        used by ``$theme`` mode flips to update the browser-chrome color.
        """
        key = _item_key(name)
        items = list(self.__dict__.get("items") or [])
        for i, it in enumerate(items):
            if it.get("key") == key:
                items[i] = {"key": key, "name": name, "content": content}
                self.items = items
                return lambda: self.remove(name)
        items.append({"key": key, "name": name, "content": content})
        self.items = items
        return lambda: self.remove(name)

    def remove(self, name: str) -> None:
        """Remove a meta by its name identity (no-op when absent)."""
        key = _item_key(name)
        items = list(self.__dict__.get("items") or [])
        kept = [it for it in items if it.get("key") != key]
        if len(kept) != len(items):
            self.items = kept

    def dispose(self, disposer) -> None:
        """Run a disposer returned by :meth:`add` / :meth:`upsert`."""
        if disposer is not None:
            try:
                disposer()
            except Exception:
                pass

    # ── read helpers ───────────────────────────────────────────────────────

    def items_for(self) -> list[dict]:
        """The current ordered item list (``[]`` when empty / not seeded)."""
        return list(self.__dict__.get("items") or [])
