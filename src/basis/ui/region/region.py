"""The region primitive — ``<ui-region name="...">``.

A data-driven mount point: the component reads its page's ``$regions`` slice
for ``name`` and mounts each contribution's component class into its own root,
live, on both SSR and the client. See ``ROADMAP-SPATIAL.md`` (Tier A1/A2) and
the Advanced docs on dynamic mounting.

Not a ``<slot>`` — slots are static and shadow-DOM-bound. A region grows and
shrinks with the ``$regions`` store (which is app-housed and page-scoped): the
``<ui-region name>`` tag is the only declaration, contributions register at
boot, and runtime add/remove re-runs a scoped re-sync of this region only.
"""

from basis.shared.component import Component
from basis.shared.region import ensure_region_registry, mount_component


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
        """
        ensure_region_registry()
        self._sync()
        store = self.S.get("regions")
        if store is not None:
            store.add_subscription(self, "items")
            self._dag.get_or_create_state("$regions.items")
            self._dag.add_effect("region_sync", self._sync, ["$regions.items"])

    def _sync(self):
        """Reconcile mounted contributions against the current store slice."""
        store = self.S.get("regions")
        items = store.items_for(self.name) if store is not None else []
        expected = [(it.get("cls_path"), it.get("props") or {}) for it in items]
        expected_paths = {path for path, _ in expected}

        mounted = self.__dict__.setdefault("_region_mounted", {})
        for path in list(mounted):
            if path not in expected_paths:
                node = mounted.pop(path)
                try:
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
                mounted[path] = node
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
