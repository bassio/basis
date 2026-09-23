"""The official mobile plugin — installable apps, offline, device integration.

One declaration turns a Basis app into an installable, offline-capable app:

    # stores/pwa.py
    from basis.plugins.mobile import PwaStore

    pwa = PwaStore(
        "pwa",
        title="Myapp",
        short_name="Myapp",
        icons=["/static/icon-192.png", "/static/icon-512.png"],
    )

Declaring the store is the opt-in, exactly like an app declaring its own
``ThemeStore``: the plugin contributes nothing to an app that does not declare one (no
store in ``#basis-initial-state``, no head link, no worker). Everything the plugin
serves is derived from that declaration plus the active theme — a manifest, an
app-shell service worker, and the offline fallback document.

The pieces live next to this package rather than in core because a plain
server-rendered site should not download any of it.
"""

from basis.plugins.mobile.pwa import REGISTER_URL
from basis.plugins.mobile.store import PwaStore


def _client_module():
    """The loaded ``register.js`` namespace, or ``None``.

    ``None`` on the server, before the client module has loaded, and for a page whose
    ``$pwa`` never started its client half (dev mode, or no worker wanted) — the three
    cases where the browser has nothing to be asked.
    """
    import sys

    if "pyscript" not in sys.modules:
        return None
    from basis.client.js_runtime import JsModuleRegistry

    return JsModuleRegistry.get(REGISTER_URL)


def apply_update() -> bool:
    """Let a waiting worker take over — the one call behind ``$pwa.ready``.

    Returns whether a worker was asked, so a caller can tell "reloading" from "nothing
    left to do". Fits a plain click handler::

        from basis.plugins.mobile import apply_update

        <button if="{$pwa.ready}" onclick="{apply_update}">Update</button>
    """
    module = _client_module()
    if module is None:
        return False
    try:
        return bool(module.applyUpdate())
    except Exception as e:
        print(f"[Basis] $pwa: could not apply the update: {e}")
        return False


def install() -> bool:
    """Show the browser's install prompt — the one call behind ``$pwa.can_install``.

    Returns whether the browser had an offer to show: it never does on iOS, which is why
    the docs pair this with the Share-sheet recipe.
    """
    module = _client_module()
    if module is None:
        return False
    try:
        return bool(module.install())
    except Exception as e:
        print(f"[Basis] $pwa: could not prompt for installation: {e}")
        return False


__all__ = ["PwaStore", "apply_update", "install"]
