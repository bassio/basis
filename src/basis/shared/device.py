"""The ``$device`` context store.

An always-present, SSR-safe reactive store of *client* viewport / context state —
the window size + DPR, orientation, pointer / hover / touch capability, and the
user's reduced-motion preference — so app code and components can make DAG-level
decisions from Python (chunk a list, skip a JS animation, drop a hover-only
affordance) without touching ``document`` at declaration time.

Core / Page-default store (like ``$plugins`` / ``$meta``)
--------------------------------------------------------
``$device`` is a framework control-plane store, not plugin-owned:

- ``Page`` guarantees it exists on every page (``shared/page.py`` ``_load``; the
  client entrypoint; ``FRAMEWORK_STORE_NAMES`` includes ``"device"`` so it is
  serialized into ``#basis-initial-state`` even on a strict ``Page.stores``
  page) — exactly like ``$plugins`` and ``$meta``.
- The **server** sets *neutral* defaults (the desktop-friendly assumption:
  ``width``/``height`` 0, ``dpr`` 1, ``pointer`` "fine", ``hover`` True,
  ``touch``/``reduced_motion`` False). Neutral values are what SSR serializes and
  the client first hydrates, so server markup and client markup agree on first
  paint.
- The **client** OVERWRITES them with the real browser values *after mount*
  (``basis/client/device_probes.py``), which
  re-renders only the nodes that read the store.

Which side answers what
-----------------------
- **Capability** (``hover``, ``reduced_motion``) is a CSS media feature, so the field is
  *declared* with :func:`~basis.shared.media.media`: the browser answers it through the
  one shared listener per query, a device change re-answers it, and the declared
  ``default`` is the neutral the server ships. Nothing to probe.
- **Measurement** (``width``, ``height``, ``dpr``, ``orientation``, ``pointer``,
  ``touch``) has no media feature to ask, so the neutral below stands until the client
  probe reads the window after mount.

Fields are plain reactive ``Store`` attributes (``$device.width`` …). Keep
*presentation* CSS-first (media queries) — this store is for Python / DAG decisions.

Viewport tier
-------------
``tier`` is the viewport class: ``"compact"`` (≤ 767px), ``"medium"`` (768–1023px) or
``"regular"`` (≥ 1024px), derived from the two declared width queries below (see
``basis.shared.breakpoints`` for the boundaries and the matching CSS form). Use it for
*behaviour* — chunk a list, swap a control, choose which state a control toggles — and
leave *layout* to CSS: the server ships the neutral tier, so a structural difference
would only appear after the browser answered.
"""

from basis.shared.breakpoints import compact_query, medium_query
from basis.shared.media import media
from basis.shared.reactive import computed
from basis.shared.store import Store, ensure_store


def ensure_device_store() -> "DeviceStore":
    """Return the ``$device`` store, creating it if absent.

    Mirrors ``ensure_meta_store``: called by ``Page._load`` (server, per request
    — the registry is cleared between requests) and the client entrypoint so
    ``$device`` resolves on every page before any component mounts.
    """
    return ensure_store("device", DeviceStore)


class DeviceStore(Store):
    """Client viewport / context state (name ``"device"`` → ``$device``).

    SSR-safe by construction: the declared neutrals are what the server ships and the
    client's first paint hydrates, then the browser answers the media-query fields while
    the probe fills in the measured ones. ``orientation`` is ``"portrait"`` |
    ``"landscape"`` and ``pointer`` is ``"fine"`` | ``"coarse"`` (the CSS ``pointer``
    media feature).
    """

    # Capability, answered by the browser as a CSS media feature. Declaring keeps one
    # ``MediaQueryList`` and one ``change`` listener per query for the whole page, and
    # makes each answer an ordinary reactive field that serialises, hydrates and reacts.
    hover = media("(hover: hover)", default=True)
    reduced_motion = media("(prefers-reduced-motion: reduce)")

    # The viewport tier's boundaries, declared the same way (see
    # ``basis.shared.breakpoints``). ``regular`` is the remainder, so it needs no third
    # query. Neutral ``False`` = the desktop-safe baseline the server ships.
    compact = media(compact_query())
    medium = media(medium_query())

    # Measurement, which no media feature can answer: the neutral stands until the client
    # probe reads the window.
    neutral_defaults = {
        "width": 0,               # layout viewport width (px)
        "height": 0,              # layout viewport height (px)
        "dpr": 1,                 # window.devicePixelRatio
        "orientation": "portrait",
        "pointer": "fine",        # "fine" | "coarse"
        "touch": False,           # any touch points
    }

    @computed(dependencies=["compact", "medium"])
    def tier(self) -> str:
        """The viewport class: ``"compact"`` | ``"medium"`` | ``"regular"``."""
        if self.compact:
            return "compact"
        if self.medium:
            return "medium"
        return "regular"
