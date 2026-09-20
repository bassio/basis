"""The ``$head`` document-head store.

Two keyed item lists, one head loop each in the base ``Page.template()``:

- ``metas`` — ``<meta name=... content=...>`` tags that must react to state or be
  contributed by a plugin/component — today ``theme-color`` (follows ``$theme``);
- ``links`` — ``<link>`` tags: ``manifest``/icons today, ``preconnect``/``preload``
  whenever a component needs them.

The static per-page half needs no framework API: whole-page mount made a
Page's own ``<head>`` a live template region, so per-route tags
(``description``, ``og:*``, ``apple-*``) are simply authored in a ``Page``
subclass's template.

Core / Page-default store (like the plugin registry)
----------------------------------------------------
``$head`` is a **framework control-plane store**, not a plugin-owned one:
- ``Page`` guarantees it exists on every page (``shared/page.py`` ``_load``;
  client entrypoint; ``FRAMEWORK_STORE_NAMES`` includes ``"head"`` so it is
  serialized into ``#basis-initial-state`` even on a strict ``Page.stores``
  page), exactly like ``$plugins``.
- A plugin (e.g. theme) NEVER ``include_store``s it — it only **contributes
  items** (``add_meta``/``upsert_meta``/``add_link``) and records the disposer
  on its registration.
- **An empty list renders nothing**: the base ``Page.template()`` loops emit
  zero elements for an empty list, so an always-present-but-empty store is
  byte-stable (no head churn, no ``safe_eval`` error on pages without
  contributors).

Render + reactivity story: the base ``Page.template()`` renders ``metas`` and
``links`` through keyed head ``LoopBinding``s (sibling repetition under
``<head>``, the same mechanism as the component-style loop). Whole-page
hydration keeps those loops alive, so a plugin/component contributing to this
store reconciles the live head node — there is **no imperative ``head_sync``
reconciler**.

Item shape
----------
Both lists hold plain dicts — the same shape on the server, in
``#basis-initial-state`` and after client hydration, so each head loop binds one
shape everywhere and :meth:`Store.serialize` needs no special-casing (the
ModelStore lesson: don't send objects across the wire and expect the same type
back).

- ``metas``: ``{"key", "name", "content"}``, dedup key ``name:<name>``. Metas are
  *name-keyed*: the document-level live channel only carries ``name``/``content``
  tags (``theme-color``, later ``color-scheme`` etc.). ``property``/``http-equiv``
  metas are page-static and live in page templates, never here.
- ``links``: ``{"key", "rel", "href", ...}``, dedup key ``<rel>:<href>``. The
  optional attribute keys are exactly :data:`_LINK_ATTRS`, and every one of them is
  **always present** — ``None`` means "this attribute does not apply" (the binding
  removes it) — because the loop's bindings are fixed. An attribute the loop cannot
  render would silently vanish, so :meth:`HeadStore.add_link` rejects anything
  outside the set instead.

``key`` is the dedup identity and doubles as the loop's reconciliation key.

Per-request SSR note (for contributors)
--------------------------------------
``Store._registry`` is cleared per request for SSR isolation (only the
persistent blueprint survives), so runtime adds made once at boot do NOT
survive into a later request's render. A contributor whose items are derived
from request state (``$theme``'s cookie) must re-seed per request — the
established seam is the ``apply_request(request)`` hook the render engines call
on every store in the registry (see ``server/render.py`` / ``shared/page.py``),
which recomputes the lists before the head loops' final paint and the
initial-state serialization.
"""

from basis.shared.store import Store, ensure_store

#: The optional ``<link>`` attributes the head loop renders. The loop's bindings list
#: these by name, so the set and the template have to move together.
_LINK_ATTRS = ("type", "sizes", "as", "media", "crossorigin")


def _meta_key(name: str) -> str:
    """The dedup / reconciliation key for a name-keyed meta (``theme-color`` →
    ``"name:theme-color"``)."""
    return f"name:{name}"


def _link_key(rel: str, href: str) -> str:
    """The dedup / reconciliation key for a head link (``icon`` + ``/a.png`` →
    ``"icon:/a.png"``)."""
    return f"{rel}:{href}"


def ensure_head_store() -> "HeadStore":
    """Return the ``$head`` store, creating it if absent.

    Mirrors ``ensure_plugin_registry``: called by the Page ``_load`` (server,
    per request — the registry is cleared between requests) and the client
    entrypoints so ``$head`` resolves on every page before the head loops
    mount. Empty by default (``metas == []``/``links == []`` → nothing renders).
    """
    return ensure_store("head", HeadStore)


class HeadStore(Store):
    """Document-level, reactive head store (registered under ``"head"``).

    ``metas`` (``{"key", "name", "content"}``) and ``links``
    (``{"key", "rel", "href", …}``) are ordered item lists. Mutations reassign the
    list so the matching head loop's DAG edge fires — the trigger that re-renders it.

    A contributor is any plugin/component that owns head content the *page* cannot
    author: ``$theme`` owns ``theme-color``, and ``links`` is the channel for a
    ``<link>`` whose ``rel``/``href`` only a plugin knows (a manifest, an icon set, a
    preload).
    """

    def __init__(self, name: str = "head"):
        super().__init__(name)
        # Store-subclass footgun: never clobber SSR-hydrated items (hydration
        # runs inside Store.__init__, reading #basis-initial-state).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["metas"] = []
            self.__dict__["links"] = []

    # ── metas (name/content) ───────────────────────────────────────────────

    def add_meta(self, name: str, content: str) -> callable:
        """Append a meta unless that identity is already present.

        Returns a disposer that removes it again (``registration.disposers``
        pattern — plugin disable unwinds its head contribution).
        """
        key = _meta_key(name)
        metas = list(self.__dict__.get("metas") or [])
        if any(it.get("key") == key for it in metas):
            return lambda: None  # already present — nothing to do
        metas.append({"key": key, "name": name, "content": content})
        self.metas = metas
        return lambda: self.remove_meta(name)

    def upsert_meta(self, name: str, content: str) -> callable:
        """Replace a meta with the same identity, or append it if absent.

        The single ``theme-color`` node is guaranteed (one node per identity);
        used by ``$theme`` mode flips to update the browser-chrome color.
        """
        key = _meta_key(name)
        metas = list(self.__dict__.get("metas") or [])
        for i, it in enumerate(metas):
            if it.get("key") == key:
                metas[i] = {"key": key, "name": name, "content": content}
                self.metas = metas
                return lambda: self.remove_meta(name)
        metas.append({"key": key, "name": name, "content": content})
        self.metas = metas
        return lambda: self.remove_meta(name)

    def remove_meta(self, name: str) -> None:
        """Remove a meta by its name identity (no-op when absent)."""
        key = _meta_key(name)
        metas = list(self.__dict__.get("metas") or [])
        kept = [it for it in metas if it.get("key") != key]
        if len(kept) != len(metas):
            self.metas = kept

    # ── links ──────────────────────────────────────────────────────────────

    def add_link(self, rel: str, href: str, **attrs) -> callable:
        """Append a head ``<link>`` unless the same ``(rel, href)`` is present.

        ``attrs`` are the optional attributes the head loop renders — see
        :data:`_LINK_ATTRS`. Pass ``as_`` for the ``as`` attribute (a keyword).
        Anything the loop cannot render raises here, because a link that reaches the
        serialized state but not the page is worse than a loud error at the call site.

        Returns a disposer that removes it again.
        """
        values = {}
        for attr, value in attrs.items():
            attr = "as" if attr == "as_" else attr
            if attr not in _LINK_ATTRS:
                raise ValueError(
                    f"Unknown <link> attribute {attr!r} — the head loop renders "
                    f"{', '.join(_LINK_ATTRS)}. Add it to _LINK_ATTRS and to the "
                    f"loop's bindings together."
                )
            values[attr] = value
        key = _link_key(rel, href)
        links = list(self.__dict__.get("links") or [])
        if any(it.get("key") == key for it in links):
            return lambda: None  # already present — nothing to do
        item = {"key": key, "rel": rel, "href": href}
        item.update({attr: values.get(attr) for attr in _LINK_ATTRS})
        links.append(item)
        self.links = links
        return lambda: self.remove_link(rel, href)

    def remove_link(self, rel: str, href: str) -> None:
        """Remove a link by its ``(rel, href)`` identity (no-op when absent)."""
        key = _link_key(rel, href)
        links = list(self.__dict__.get("links") or [])
        kept = [it for it in links if it.get("key") != key]
        if len(kept) != len(links):
            self.links = kept

    def dispose(self, disposer) -> None:
        """Run a disposer returned by any of the contribution methods."""
        if disposer is not None:
            try:
                disposer()
            except Exception:
                pass

    # ── read helpers ───────────────────────────────────────────────────────

    def metas_for(self) -> list[dict]:
        """The current ordered meta list (``[]`` when empty / not seeded)."""
        return list(self.__dict__.get("metas") or [])

    def links_for(self) -> list[dict]:
        """The current ordered link list (``[]`` when empty / not seeded)."""
        return list(self.__dict__.get("links") or [])
