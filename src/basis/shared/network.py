"""The ``$network`` context store.

An always-present, SSR-safe reactive store of the client's connectivity —
online / offline, the effective connection type, and save-data — so app code can
show an offline banner, degrade deliberately on slow links, or batch actions
(without touching ``navigator`` at declaration time).

Core / Page-default store (like ``$plugins`` / ``$meta``) — see
``shared/device.py`` for the full SSR-safe contract: the **server** serializes
neutral defaults (``online`` True, ``effective_type`` "unknown", ``save_data``
False — assume a healthy connection) and the **client** overwrites them with the
real values after mount (``basis/client/device_probes.py``).

Fields are reactive ``Store`` attributes (``$network.online`` …), with ``offline``
derived from ``online``.
"""

from basis.shared.reactive import computed
from basis.shared.store import Store, ensure_store


def ensure_network_store() -> "NetworkStore":
    """Return the ``$network`` store, creating it if absent.

    Mirrors ``ensure_meta_store``: called by ``Page._load`` (server, per request
    — the registry is cleared between requests) and the client entrypoint so
    ``$network`` resolves on every page before any component mounts.
    """
    return ensure_store("network", NetworkStore)


class NetworkStore(Store):
    """Client connectivity state (name ``"network"`` → ``$network``).

    ``online`` mirrors ``navigator.onLine``, and ``offline`` is its inverse so an
    offline banner binds the store instead of negating it in a template.
    ``effective_type`` mirrors ``navigator.connection.effectiveType`` ("4g",
    "3g", "2g", "slow-2g", or "unknown" where the API is unavailable — Firefox /
    Safari); ``save_data`` mirrors ``navigator.connection.saveData``.
    """

    # Optimistic: a healthy connection is the neutral that leaves desktop SSR untouched.
    neutral_defaults = {
        "online": True,               # navigator.onLine
        "effective_type": "unknown",  # navigator.connection.effectiveType
        "save_data": False,           # navigator.connection.saveData
    }

    @computed(dependencies=["online"])
    def offline(self) -> bool:
        return not self.online
