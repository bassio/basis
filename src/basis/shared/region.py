"""App-housed, page-scoped region registry — the ``$regions`` spatial primitive.

A region is a named, ordered list of *component recipes* (a ``Component`` class +
initial ``props``). The class is the identity of a contribution: there is at most
one instance per ``(region, class)``, re-adding the same class replaces the
existing entry (HMR-safe), and the framework owns every live instance (mount,
hydrate, dispose).

Layering (see ``ROADMAP-SPATIAL.md``, Tier A1/A2):

- **App-housed**: the authoritative registry lives on the app (``Basis._regions``)
  and is populated at boot by plugins / the skeleton. The ``RegionStore``
  (``$regions``) is a reactive ``_requires_app`` projection of it, serialized
  into ``#basis-initial-state``.
- **Page-scoped**: a page's visible regions are the ``<ui-region name=...>``
  tags its component tree hosts; each page renders only ``hosted ∩ registered``.

Registration timing: contributions register at import/boot (never at render —
render only reads); render points (``<ui-region>`` tags) are declarative reads,
never registered; hosted sets are derived lazily at first render of each page
and cached.

The one new primitive underneath regions is :func:`mount_component` — resolve a
component by class or ``module.path.ClassName`` and mount it into a node,
duck-typed for the server ``Element`` model and the client DOM.
"""

import importlib
from dataclasses import dataclass, field

from basis.shared.store import Store

# Sentinel used by ``position="start"`` so a contribution sorts before any
# explicit positive ``order`` (append = ``order=None`` → sorts last).
MIN_ORDER = -(2**31)


def cls_path_of(component_cls: type) -> str:
    """The serializable identity of a component class (module path + name)."""
    return f"{component_cls.__module__}.{component_cls.__name__}"


@dataclass
class RegionContribution:
    """One component recipe registered to a region.

    Identity is ``(region, cls_path)`` — re-adding the same class to the same
    region replaces the existing entry (HMR-safe). ``seq`` is the insertion
    counter used as the tie-breaker for ordering.
    """

    region: str
    component_cls: type
    props: dict = field(default_factory=dict)
    order: int | None = None
    owner: str | None = None  # plugin name (None = app/skeleton)
    seq: int = 0

    @property
    def cls_path(self) -> str:
        return cls_path_of(self.component_cls)


def _sort_key(contrib: RegionContribution):
    # Explicit ``order`` sorts before natural (None = append); ties by seq.
    order = contrib.order
    return (0 if order is not None else 1, order if order is not None else 0, contrib.seq)


def _region_listing(app) -> dict:
    """Serialize ``app._regions`` into ``{region: [{cls_path, props, order}]}``.

    Single source of truth shared by the ``$regions`` store's refresh, the
    per-page serialization slice, and any tooling. Sorted per the A1 ordering
    rules (declaration order by default; ``order=`` overrides; ties by seq).
    """
    regions = getattr(app, "_regions", None) or {}
    listing = {}
    for region, contribs in regions.items():
        listing[region] = [
            {"cls_path": c.cls_path, "props": c.props or {}, "order": c.order}
            for c in sorted(contribs, key=_sort_key)
        ]
    return listing


def _refresh_registry(app) -> None:
    """Keep the app-owned ``$regions`` store's projection in sync (if created)."""
    regions = getattr(app, "regions", None)
    if regions is not None:
        refresh = getattr(regions, "_refresh_from_app", None)
        if refresh is not None:
            refresh()


def _register_contribution(app, contrib: RegionContribution) -> None:
    """Add *contrib* to ``app._regions``, replacing any ``(region, cls_path)`` entry.

    The region's list is kept in display order (sorted by the A1 ordering rules)
    so ``app._regions`` reads the same way the store projects it.
    """
    regions = getattr(app, "_regions", None)
    if regions is None:
        regions = app._regions = {}
    region_items = regions.setdefault(contrib.region, [])
    region_items[:] = [c for c in region_items if c.cls_path != contrib.cls_path]
    region_items.append(contrib)
    region_items.sort(key=_sort_key)
    _refresh_registry(app)


def _unregister_contribution(app, contrib: RegionContribution) -> None:
    """Remove *contrib* (by identity) from ``app._regions``."""
    regions = getattr(app, "_regions", None)
    if not regions:
        return
    region_items = regions.get(contrib.region)
    if not region_items:
        return
    regions[contrib.region] = [c for c in region_items if id(c) != id(contrib)]
    _refresh_registry(app)


class RegionHandle:
    """Disposer returned by ``add_to_region``.

    ``dispose()`` removes the contribution from the app registry (and, for a
    plugin-created contribution, drops it from the plugin's pending list too).
    Bulk revert on ``disable_plugin`` / ``remove_plugin`` is driven by the
    ``PluginRegistration.region_items`` record, not individual handles.
    """

    def __init__(self, contribution: RegionContribution, app=None, owner=None):
        self._contribution = contribution
        self._app = app
        self._owner = owner
        self._disposed = False

    @property
    def contribution(self) -> RegionContribution:
        return self._contribution

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        if self._app is not None:
            _unregister_contribution(self._app, self._contribution)
        pending = getattr(self._owner, "_region_items", None)
        if pending is not None and self._contribution in pending:
            pending.remove(self._contribution)


def resolve_component(cls_path: str):
    """Resolve ``module.path.ClassName`` to the component class.

    Works on both sides — the module is imported (server: installed package;
    client: PyScript VFS), enforcing the isomorphism invariant that every
    contribution component is importable on both sides.
    """
    module_name, _, class_name = cls_path.rpartition(".")
    module = importlib.import_module(module_name)
    return getattr(module, class_name)


def mount_component(node, component_cls_or_path, props: dict | None = None):
    """Mount a component into *node* and return the live instance.

    ``component_cls_or_path`` may be a component class (author/server side) or
    a ``module.path.ClassName`` string (serialized/client side). This is the
    dynamic-mount primitive behind regions; both the server ``Element`` model
    and the client DOM share ``BaseComponent.mount``.
    """
    if isinstance(component_cls_or_path, str):
        component_cls = resolve_component(component_cls_or_path)
    else:
        component_cls = component_cls_or_path
    return component_cls.mount(node, replace=False, **(props or {}))


class RegionStore(Store):
    """Reactive, app-global region registry (registered under the name ``regions``).

    Server: a ``_requires_app`` projection of ``app._regions`` (durable,
    boot-populated), refreshed at app-attach time. Client: a pure reactive view
    hydrated from ``#basis-initial-state``, plus ``add_local`` / ``remove_local``
    for ephemeral runtime adds (never written back to the server registry).
    """

    _requires_app = True

    def __init__(self, name: str = "regions"):
        super().__init__(name)
        # Reactive projection: {region: [{cls_path, props, order}, ...]}.
        # Never clobber the SSR-hydrated items (store-subclass footgun).
        if not getattr(self, "_hydrated_from_ssr", False):
            self.__dict__["items"] = {}

    def _refresh_from_app(self) -> None:
        app = self.__dict__.get("_app")
        if app is None:
            return
        self.__dict__["items"] = _region_listing(app)

    def serialize(self) -> dict:
        self._refresh_from_app()
        return super().serialize()

    def items_for(self, region: str) -> list:
        return (self.items or {}).get(region, [])

    def add_local(self, region: str, cls_path: str, props: dict | None = None, order=None) -> None:
        """Ephemeral client-side add (replace by ``cls_path``)."""
        items = dict(self.items or {})
        region_items = [it for it in items.get(region, []) if it.get("cls_path") != cls_path]
        region_items.append({"cls_path": cls_path, "props": props or {}, "order": order})
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

    Called by the client entrypoints (and lazily by ``ui-region``) so
    ``$regions`` resolves on every page. On SSR/CSR the store hydrates from
    ``#basis-initial-state``; ``add_local`` / ``remove_local`` cover ephemeral
    runtime adds.
    """
    from basis.shared.store import ensure_store

    return ensure_store("regions", RegionStore)
