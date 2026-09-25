"""The ``$pwa`` store — an app's installable identity.

The declaration an app writes to opt in (see :mod:`basis.plugins.mobile`). It is an
ordinary reactive store, not a config object, because three different sides need the
same facts and each gets them the way it already knows how:

- the **server** reads ``title``/``icons``/``scope`` when it generates the web manifest,
  and the links that point at it;
- the **client** hydrates the same fields from ``#basis-initial-state``, so an update
  prompt or an install button can read the app's identity without another request;
- the **template** binds ``$pwa.ready`` / ``$pwa.can_install`` as plain reactive state.

Field split (the ``$device`` contract)
--------------------------------------
``standalone`` is a **capability**: it is a CSS media feature, so it is *declared* with
:func:`~basis.shared.media.media` and the browser answers it. Everything the browser
learns only after the worker registers (``controlled``, ``ready``, ``waiting_version``,
``can_install``) is a **measurement** with a server-safe scalar default, then overwritten
after mount.

Identity fields are plain instance attributes so they serialize like any other store
state — and, like every store subclass, they must never clobber a hydrated value
(``__init__`` runs *after* hydration, which happens inside ``Store.__init__``).
"""

import asyncio
import sys

from basis.plugins.mobile.pwa import REGISTER_URL, RUNTIME_URL, SERVICE_WORKER_URL
from basis.shared.events import py_event
from basis.shared.media import media
from basis.shared.reactive import batch
from basis.shared.store import Store

#: Installed-app detection. ``browser`` (an ordinary tab) never matches, so the neutral
#: is the honest answer for a page that has not been installed.
STANDALONE_QUERY = "(display-mode: standalone)"


def _dev_mode() -> bool:
    """Whether the served document carries the dev marker.

    Read from the meta rather than inferred from the host: the server decides what dev
    mode is (``basis dev``), and the document is the only place the client is told.
    """
    try:
        from pyscript import document

        meta = document.querySelector('meta[name="basis-dev-mode"]')
        # An absent match is a falsy JS null, not None: truthiness is the check.
        return (meta.getAttribute("content") if meta else "").strip().lower() == "true"
    except Exception:
        return False


class PwaStore(Store):
    """The app's installable identity (name ``"pwa"`` → ``$pwa``).

    ``icons`` accepts URLs or dicts: a string is an icon the plugin derives
    ``sizes``/``type`` for from the file itself, a dict passes ``src``/``sizes``/
    ``type``/``purpose`` through verbatim. ``offline`` is the switch behind the
    app-shell worker — an app that wants the manifest without the worker says so here
    rather than the plugin guessing.
    """

    # Capability, answered by the browser as a CSS media feature (one shared listener).
    standalone = media(STANDALONE_QUERY)

    # Worker state keeps these server-safe values until the client registers it.
    controlled = False
    ready = False
    waiting_version = None
    can_install = False
    error = None

    def __init__(
        self,
        name: str = "pwa",
        *,
        title: str | None = None,
        short_name: str | None = None,
        description: str | None = None,
        start_url: str = "/",
        scope: str = "/",
        display: str = "standalone",
        icons: list | tuple = (),
        shortcuts: list | tuple = (),
        apple_touch_icon: str | None = None,
        background_color: str | None = None,
        offline: bool = True,
    ):
        super().__init__(name)
        for key, value in (
            ("title", title),
            ("short_name", short_name),
            ("description", description),
            ("start_url", start_url),
            ("scope", scope),
            ("display", display),
            ("icons", list(icons)),
            ("shortcuts", list(shortcuts)),
            ("apple_touch_icon", apple_touch_icon),
            ("background_color", background_color),
            ("offline", offline),
        ):
            setattr(self, key, value)

    def apply_request(self, request) -> None:
        """Server-only: contribute this app's head links for the request being rendered.

        The manifest link and the icons ride together — a link to a manifest the app does
        not serve is worse than no link at all — and ``$head`` is cleared with the rest of
        the per-request registry, so a render always contributes the full set exactly once.
        A page without ``$head`` (a hand-rolled route that never mounted one) contributes
        nothing rather than failing.
        """
        from basis.plugins.mobile.pwa import MANIFEST_URL
        from basis.plugins.mobile.pwa.icons import apple_touch_href, icon_links
        from basis.shared.store import Store

        head = Store._registry.get("head")
        if head is None:
            return
        head.add_link("manifest", MANIFEST_URL)
        for icon in icon_links(self):
            head.add_link("icon", icon["src"], type=icon.get("type"), sizes=icon.get("sizes"))
        touch = apple_touch_href(self)
        if touch:
            head.add_link("apple-touch-icon", touch)

    # ── the client half: registration and the worker's lifecycle ────────────
    def on_client_ready(self) -> None:
        """Client-only: start the browser conversation ``register.js`` owns.

        Not in ``__init__``: a listener attached before the document mounted would write
        before hydration, and this store's whole client life is one listener plus the
        registration the browser keeps. Skipped in dev mode — a worker would shadow HMR's
        hot-swap with stale modules, the one failure this framework refuses to hide — and
        in a page with no Pyodide, where there is nobody to hear the events.
        """
        super().on_client_ready()
        if self.__dict__.get("_pwa_client"):
            return
        # Read at call time rather than from an import-time constant: whether this module
        # was imported before PyScript is a detail of how the app was started, and getting
        # it wrong here would silently cost the app its worker.
        if "pyscript" not in sys.modules:
            return
        if _dev_mode():
            print(
                "[Basis] $pwa: no service worker in dev mode "
                "(it would serve stale modules over HMR)"
            )
            return
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return  # no loop to schedule on — a bare import, not a mounted page
        self.__dict__["_pwa_client"] = True
        asyncio.ensure_future(self._start_client())

    def on_client_teardown(self) -> None:
        """Client-only: release the listener.

        The registration is the browser's and stays: unregistering it would leave the app
        permanently uncontrolled until the next reload registered it again.
        """
        super().on_client_teardown()
        self.__dict__.pop("_pwa_client", None)
        listener = self.__dict__.pop("_pwa_listener", None)
        if listener is not None:
            listener.dispose()

    async def _start_client(self) -> None:
        """Load the client module, then let it register (client-only).

        The listener is attached before registering, because registration reports state
        synchronously when a worker already controls the page — an event nobody was
        listening for yet would leave ``$pwa.controlled`` False on every revisit.
        """
        from pyscript import document, ffi

        from basis.client.js_runtime import JsModuleRegistry
        from basis.shared.events import Listener

        try:
            module = await JsModuleRegistry.load(REGISTER_URL)
        except Exception as e:
            self.error = f"client module failed to load: {e}"
            return
        self.__dict__["_pwa_listener"] = Listener(
            document, "basis:pwa", self._on_pwa_event
        )
        try:
            module.register(
                ffi.to_js(
                    {
                        "url": SERVICE_WORKER_URL,
                        "offline": bool(self.offline),
                        "runtime": RUNTIME_URL,
                    }
                )
            )
        except Exception as e:
            self.error = f"registration failed: {e}"

    @py_event
    def _on_pwa_event(self, event) -> None:
        """Mirror a ``basis:pwa`` detail into the store (see ``register.js``).

        Every field here is client-observed — the server ships the neutral and the client
        overwrites it — so one batch keeps a multi-field update to one render.
        """
        detail = event.detail if isinstance(event.detail, dict) else {}
        kind = detail.get("kind")
        with batch():
            if kind == "controlled":
                self.controlled = True
            elif kind == "update-ready":
                self.ready = True
                self.waiting_version = detail.get("version")
            elif kind == "installable":
                self.can_install = True
            elif kind in ("installed", "install-prompted"):
                # Either way the browser is done offering: it fires the event once per
                # prompt and not again in this page's lifetime.
                self.can_install = False
            elif kind == "unsupported":
                print(f"[Basis] $pwa: {detail.get('message')}")
            elif kind == "error":
                self.error = str(detail.get("message") or "service worker registration failed")
