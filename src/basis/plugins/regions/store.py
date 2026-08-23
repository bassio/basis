"""The ``$regions`` reactive store (the regions plugin's data plane).

Server: a ``_requires_app`` projection of ``app._regions`` (durable,
boot-populated), refreshed at app-attach time. Client: a pure reactive view
hydrated from ``#basis-initial-state``, plus ``add_local`` / ``remove_local``
for ephemeral runtime adds (never written back to the server registry).

Because disabling/enabling a plugin unwinds/restores its region contributions,
this store subscribes (locally) to the ``$plugins`` control plane via a
first-class cross-object DAG edge — the same mechanism ``ComponentSubscription``
became (``$plugins.add_subscription(self, "items")``). When ``$plugins.items``
changes on the client, the edge calls ``$regions.react``, which translates the
trigger into a server re-pull (``refresh()``). No framework code knows
``regions`` by name.
"""

import asyncio

from basis.shared.app_state import AppStateStore
from basis.shared.store import Store, ensure_store

from basis.plugins.regions.registry import _region_listing


class RegionStore(AppStateStore):
    """Reactive, app-global region registry (registered under the name ``regions``).

    An :class:`AppStateStore` whose ``items`` projection is ``app._regions``
    (durable, boot-populated), refreshed at app-attach time. Client: a pure
    reactive view hydrated from ``#basis-initial-state``, plus ``add_local`` /
    ``remove_local`` for ephemeral runtime adds (never written back to the
    server registry).
    """

    def __init__(self, name: str = "regions"):
        super().__init__(name)
        # Reactive projection: {region: [{cls_path, props, order}, ...]}.
        # Never clobber the SSR-hydrated items (store-subclass footgun).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = {}
        # $regions projects app state that plugin lifecycle changes mutate
        # (disable/enable unwinds/restores a plugin's contributions), so re-sync
        # whenever the $plugins control-plane store updates on the client. The
        # dependency is a cross-object DAG edge (BINDINGS-REVIEW §6), not a
        # parallel registry — see _wire_plugins_dependency / react.
        self._wire_plugins_dependency()

    def _wire_plugins_dependency(self) -> None:
        """Subscribe to ``$plugins.items`` via a first-class DAG edge.

        The target-side edge is ``Store.add_subscription`` — the same primitive
        the `ComponentSubscription`→DAG refactor standardized on. When
        ``$plugins.items`` changes on the client, ``$plugins``'s graph calls
        ``self.react(["$plugins.items"])``, which we translate into a server
        re-pull in :meth:`react`. No-op when the source store isn't registered
        yet (framework stores boot first, so it normally already is).
        """
        plugins = Store._registry.get("plugins")
        if plugins is not None:
            plugins.add_subscription(self, "items")

    def react(self, names: list[str]):
        """Translate cross-store triggers into a server re-pull.

        ``$plugins.add_subscription(self, "items")`` makes ``$plugins`` call
        this with ``["$plugins.items"]`` when its ``items`` changes on the
        client — re-pull our authoritative server projection (the dependency is
        a DAG edge, not a parallel registry). Other triggers pass through to the
        base reactive behaviour. (Alternative to this ``react`` overload: a
        subscriber-side effect keyed ``$plugins.items``.)
        """
        if "$plugins.items" in names:
            self._resync_from_plugins()
        super().react(names)

    def _resync_from_plugins(self) -> None:
        """Schedule a server re-pull after a ``$plugins`` change (client RPC)."""
        asyncio.ensure_future(self.refresh())

    def project(self, app) -> dict:
        """Project the app's region contributions as the store's ``items``."""
        return {"items": _region_listing(app)}

    def items_for(self, region: str) -> list:
        return (self.items or {}).get(region, [])

    def add_local(self, region: str, cls_path: str, props: dict | None = None, order=None) -> None:
        """Ephemeral client-side add (replace by ``cls_path``, **in place**).

        Re-adding a contribution that is already present (e.g. a lazy module
        import re-running ``@plugin.region``) replaces its entry WITHOUT moving
        it — the hydrated order from ``#basis-initial-state`` is authoritative
        on boot, and a remove+re-append here would silently reorder the region.
        """
        items = dict(self.items or {})
        region_items = list(items.get(region, []))
        entry = {"cls_path": cls_path, "props": props or {}, "order": order}
        for i, it in enumerate(region_items):
            if it.get("cls_path") == cls_path:
                region_items[i] = entry  # replace in place — never reorder
                items[region] = region_items
                self.items = items
                return
        region_items.append(entry)
        items[region] = region_items
        self.items = items

    def remove_local(self, region: str, cls_path: str) -> None:
        """Ephemeral client-side removal."""
        items = dict(self.items or {})
        region_items = [it for it in items.get(region, []) if it.get("cls_path") != cls_path]
        items[region] = region_items
        self.items = items


def ensure_region_registry() -> RegionStore:
    """Return the region store, creating it if absent.

    Called lazily by ``<ui-region>`` (and historically by the client
    entrypoints) so ``$regions`` resolves on every page. On SSR/CSR the store
    hydrates from ``#basis-initial-state``; ``add_local`` / ``remove_local``
    cover ephemeral runtime adds.
    """
    return ensure_store("regions", RegionStore)
