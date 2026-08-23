"""The region primitive — ``<ui-region name="...">``.

A data-driven mount point: the component reads its page's ``$regions`` slice
for ``name`` and mounts each contribution's component class into its own root,
live, on both SSR and the client. See ``ROADMAP-SPATIAL.md`` (Tier A1/A2).

Not a ``<slot>`` — slots are static and shadow-DOM-bound. A region grows and
shrinks with the ``$regions`` store (which is app-housed and page-scoped): the
``<ui-region name>`` tag is the only declaration, contributions register at
boot, and runtime add/remove re-runs a scoped re-sync of this region only.
"""

from basis.shared.component import Component, in_ssr_hydration

from basis.plugins.regions.registry import mount_component
from basis.plugins.regions.store import ensure_region_registry


class Region(Component):
    """A named, ordered mount point for component contributions.

    Renders whatever ``$regions`` holds for ``name`` by mounting each
    contribution's component class into its own root element. Class-as-identity:
    one live instance per ``(region, cls_path)``; removed contributions are
    disposed (node removal — full binding teardown + SSR-hydration of region
    items is the P1 follow-up flagged in ROADMAP-SPATIAL.md).
    """

    __tag__ = "ui-region"
    name = ""

    def template(self):
        """
        <div class="ui-region" data-region-name="{name}"></div>
        """

    def on_mounted(self):
        """Mount the region's contributions and subscribe to the store.

        Contributions register at boot (app-housed); render points are never
        registered — this is a declarative read of ``$regions`` for ``name``.
        Runtime add/remove re-runs ``_sync`` (a scoped re-sync, not a page
        re-render).

        On the client's SSR-hydration path the app is first mounted into a
        detached shadow before ``initialize_ssr`` re-points every component at
        the live SSR tree. Mounting contributions here would leave their
        bindings on shadow nodes the user never sees (dead reactivity), so the
        region defers and re-runs after hydration (``on_hydrated``).
        """
        ensure_region_registry()
        if in_ssr_hydration():
            # Client, SSR path: mount + store wiring happen after hydration
            # re-points this component at the live SSR region node.
            return
        self._sync()
        self._subscribe_to_region_store()

    def _subscribe_to_region_store(self):
        store = self.S.get("regions")
        if store is None:
            return
        if (self, "items") in store._subscriptions:
            return  # already wired — don't double-register the DAG effect
        store.add_subscription(self, "items", scope=self._scope)
        self._dag.get_or_create_state("$regions.items")
        self._scope.add_effect(self._dag, "region_sync", self._sync, ["$regions.items"])

    def on_hydrated(self):
        """Client-only (via ``initialize_ssr``). The SSR tree pre-rendered each
        contribution statically, but item roots carry no canonical hydration ids
        and the shadow-mounted copies were deferred — so the client takes over
        the subtree: drop the static items and re-mount live contributions into
        the hydrated (SSR) region node. Their bindings then act on the visible
        DOM, restoring reactivity (e.g. selecting a team in the sidebar updates
        a region-hosted explorer)."""
        element = self.__element__  # live SSR region node (post-hydration)
        for node in list(element.querySelectorAll("[data-region-item]")):
            try:
                node.remove()
            except Exception:
                pass
        self._region_mounted = {}
        self._sync()
        self._subscribe_to_region_store()

    def _sync(self):
        """Reconcile mounted contributions against the current store slice."""
        store = self.S.get("regions")
        items = store.items_for(self.name) if store is not None else []
        expected = [(it.get("cls_path"), it.get("props") or {}) for it in items]
        expected_paths = {path for path, _ in expected}

        mounted = self.__dict__.setdefault("_region_mounted", {})
        for path in list(mounted):
            if path not in expected_paths:
                instance = mounted.pop(path)
                # Real teardown: the contribution's scope owns its bindings /
                # subscriptions; then remove its DOM node.
                try:
                    instance._scope.destroy()
                except Exception:
                    pass
                try:
                    node = instance.__element__
                    node.remove()
                except Exception:
                    pass

        for path, props in expected:
            if path in mounted:
                continue
            try:
                instance = mount_component(self.__element__, path, props)
                node = instance.__element__
                if hasattr(node, "setAttribute"):
                    node.setAttribute("data-region-item", path)
                mounted[path] = instance
            except Exception:
                # One broken contribution must not break the whole region.
                continue

    def style(self):
        """
        ui-region {
            display: contents;
        }

        .ui-region {
            display: contents;
        }
        """
