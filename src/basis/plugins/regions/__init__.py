"""Official regions plugin — ``$regions`` + ``<ui-region>``.

Re-exported public API. Importing this package registers the ``<ui-region>``
custom element (server + client) and exposes the region contribution API.

Usage::

    from basis.plugins.regions import regions_plugin  # the plugin instance
    regions_plugin.add_to_region("statusbar-right", SyncStatus, props={"label": "synced"})

    # ...or the conventional module-level name (entry-point convention):
    from basis.plugins.regions.plugin import plugin as regions
"""

from basis.plugins.regions.plugin import RegionsPlugin, plugin as regions_plugin
from basis.plugins.regions.region import Region
from basis.plugins.regions.registry import (
    MIN_ORDER,
    RegionContribution,
    RegionHandle,
    cls_path_of,
    mount_component,
    resolve_component,
)
from basis.plugins.regions.store import RegionStore, ensure_region_registry

# The canonical module-level ``plugin`` variable (entry-point convention).
# Re-exposed explicitly: importing the package also binds the submodule
# ``basis.plugins.regions.plugin`` as a package attribute, which would shadow
# this otherwise (entry points must resolve the instance, not the submodule).
plugin = regions_plugin

__all__ = [
    "RegionsPlugin",
    "plugin",
    "regions_plugin",
    "Region",
    "RegionStore",
    "RegionContribution",
    "RegionHandle",
    "ensure_region_registry",
    "cls_path_of",
    "resolve_component",
    "mount_component",
    "MIN_ORDER",
]
