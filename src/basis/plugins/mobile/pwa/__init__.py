"""The installable-app plumbing: the web manifest, its icons, and the app shell.

The URLs are constants rather than literals at the call sites because three sides need
them and must agree: the manifest generator writes them into the document's ``<head>``,
the route decorators serve them, and the docs quote them. They are root-absolute — a
manifest link is a fact about the whole origin, and a nested route would otherwise
resolve a relative URL against its own path.
"""

#: The web manifest. ``<link rel="manifest">`` in every page's head.
MANIFEST_URL = "/manifest.webmanifest"

#: The app-shell service worker. Root-absolute and root-*scoped*: a worker's scope can
#: never exceed the directory it is served from, and this one has to control the app.
SERVICE_WORKER_URL = "/service-worker.js"

#: The offline fallback document, precached at install and served when a navigation has
#: neither a network nor a cached copy.
OFFLINE_URL = "/offline"

#: The client module that registers the worker and reports its lifecycle. Served from
#: the plugin's own package path, loaded through the framework's lazy JS loader, and
#: precached — the boot that has to register a worker is the boot that has no network.
REGISTER_URL = "/basis/plugins/mobile/pwa/register.js"

#: The runtime family: the content-addressed PyScript/Pyodide bundle (``/pyscript/<hash>``)
#: and everything under it. The client-side warm passes this to the worker so the two
#: agree on what "the runtime" is — the bytes the client itself needs to boot.
RUNTIME_URL = "/pyscript/"

#: The placeholder icons, served from the plugin's own package path. Only referenced
#: when the app declines to declare icons of its own.
ICON_URL = "/basis/plugins/mobile/pwa/icon-{size}.png"

#: The sizes the placeholder is generated and served at. 192 and 512 are the pair the
#: install criteria ask for; the 512 entry is also the maskable one.
ICON_SIZES = (192, 512)
