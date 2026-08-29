"""The official regions plugin — provides ``$regions`` + ``<ui-region>``.

Registered through the standard ``basis.plugins`` entry point (see
``pyproject.toml``), so it uses the same discovery/lifecycle path as any
third-party plugin. It owns:

- the app-hosted region registry state (``app._regions`` / ``app._region_seq``),
- the ``$regions`` store (created in ``on_register``),
- the region contribution API (``add_to_region`` / ``remove_from_region``,
  formerly app-level ``Basis`` methods),
- the ``<ui-region>`` component (served to the client via ``serving_dir``).
"""

from pathlib import Path

from basis.shared.plugin import BasisPlugin


class RegionsPlugin(BasisPlugin):
    """The regions service plugin.

    ``on_register`` sets up the app-owned registry + the ``$regions`` store. The
    contribution API (``add_to_region`` / ``remove_from_region``) registers
    directly against the owning app — this is the former ``Basis.add_to_region``
    surface, moved into the plugin space so the framework core has no region
    knowledge.
    """

    def on_register(self, app) -> None:
        """Create the app-owned region registry state + the ``$regions`` store."""
        # App-housed region registry (ROADMAP-SPATIAL.md): {region: [RegionContribution]}.
        # Durable, boot-populated; the $regions store is a reactive projection.
        if not hasattr(app, "_regions"):
            app._regions = {}
        if not hasattr(app, "_region_seq"):
            app._region_seq = 0
        # The $regions store — the spatial control plane. Wired through the
        # first-class plugin store-inclusion API (BasisPlugin.include_store): it
        # constructs/reuses RegionStore("regions"), app-attaches it ($regions is
        # _requires_app), and adds it to the app-global store list.
        from basis.plugins.regions.store import RegionStore

        store = self.include_store(app, RegionStore, "regions")
        if not hasattr(app, "regions"):
            app.regions = store

    def add_to_region(
        self,
        region: str,
        component_cls,
        *,
        props: dict | None = None,
        order: int | None = None,
        position: str = "end",
        owner: str | None = None,
    ):
        """Register *component_cls* into *region* directly against the owning app.

        Identity is ``(region, class)``: re-adding the same class replaces the
        existing entry (HMR-safe). Ordering: declaration order (append) by
        default, overridable by ``order=`` (int sort key); ``position="start"``
        prepends. Returns a ``RegionHandle`` disposer. See ROADMAP-SPATIAL.md.

        This is the plugin-space replacement for the former ``Basis.add_to_region``.
        """
        from basis.plugins.regions.registry import (
            MIN_ORDER,
            RegionContribution,
            RegionHandle,
            _register_contribution,
        )

        app = getattr(self, "_app", None)
        if app is None:
            raise RuntimeError(
                "The regions plugin is not registered with an app yet — call "
                "app.include_plugin(regions_plugin) (or app.bootstrap()) first."
            )
        if position == "start" and order is None:
            order = MIN_ORDER
        seq = getattr(app, "_region_seq", 0)
        contrib = RegionContribution(
            region=region,
            component_cls=component_cls,
            props=props or {},
            order=order,
            owner=owner,
            seq=seq,
        )
        app._region_seq = seq + 1
        _register_contribution(app, contrib)
        return RegionHandle(contrib, app=app, owner=owner)

    def remove_from_region(self, region: str, component_cls) -> bool:
        """Remove every contribution of *component_cls* from *region*."""
        from basis.plugins.regions.registry import _unregister_contribution, cls_path_of

        app = getattr(self, "_app", None)
        if app is None:
            return False
        removed = False
        for contrib in list(getattr(app, "_regions", {}).get(region, [])):
            if contrib.cls_path == cls_path_of(component_cls):
                _unregister_contribution(app, contrib)
                removed = True
        return removed


# The module-level plugin instance (entry-point convention: a module-level
# ``plugin`` variable that is a ``BasisPlugin`` instance).
plugin = RegionsPlugin(
    prefix="",
    serving_dir=Path(__file__).parent,
    serving_mount="/basis/plugins/regions",
    name="regions",
    tags=None,
)
