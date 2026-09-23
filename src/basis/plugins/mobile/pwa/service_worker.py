"""The app-shell service worker: its version, its precache list, and its body.

The worker is *generated* per request rather than hand-maintained, because the server
already knows every URL it serves — ``app.vfs`` is the inventory PyScript itself boots
from, so the precache list is that inventory instead of a list somebody has to remember
to update. The worker's body is a real JavaScript file (``sw.js``, next to this module:
editors and linters still see it) and this module only computes the
``const BASIS = {…}`` prelude it is served with.

What the version is for
----------------------
``shell_version`` answers one question: *"has anything the browser already cached
changed?"* It is a stat-only digest — no file is read — over the sources that make up the
shell: the worker's own bytes, the routing strategy, the vendored runtime's fingerprint,
and ``(path, mtime, size)`` for every file the app serves as code. A file edit, a plugin
upgrade, a new component or a PyScript bundle bump all produce a new version; an
unchanged app produces the same bytes for the worker, which is how the browser decides
there is nothing to update.
"""

import hashlib
import json
from pathlib import Path

import basis

from basis.plugins.mobile.pwa import OFFLINE_URL, REGISTER_URL

#: Bumped when the *strategy* changes (which requests are cached, which are bypassed,
#: which bucket a tier lands in). The body's own bytes already version the code, so this
#: exists for the changes a body edit cannot express — nothing else needs touching.
SW_STRATEGY_VERSION = "1"

#: Files that make up the shell, by extension. Python and its companion assets are the
#: app's code; images and fonts are *assets*, cached on use rather than precached, so
#: they are deliberately excluded from the version and from the install download. ``.js``
#: is code the client boots on (``basis/client/component.js``, the plugin's
#: ``register.js``) and it is precached or loaded at boot, so it belongs here — a stale
#: entry in the shell cache is only replaced when the version moves.
_SOURCE_SUFFIXES = {".py", ".pyc", ".css", ".html", ".js"}

#: How many on-the-fly entries each runtime bucket keeps. Unbounded growth is how a
#: long-lived install quietly fills a phone; the estimate is deliberately generous for
#: the asset bucket and tight for navigations.
_ASSETS_LIMIT = 120
_PAGES_LIMIT = 30


def _sw_body() -> str:
    """The worker's body — a classic script, with the config prelude injected by
    :func:`service_worker_js`."""
    return (Path(__file__).parent / "sw.js").read_text(encoding="utf-8")


def _source_roots(app) -> list[Path]:
    """Every directory whose files this app serves to the browser as code.

    The conventional dirs (``components/`` / ``stores/`` / ``plugins/``), every component
    mount (local plugins and an ``@app.page`` app dir included) and the framework's own
    served package dirs. Deduplicated and filtered to what exists, so a walk is bounded by
    the app's own code rather than by whatever a mount happens to point at.
    """
    package = Path(next(iter(basis.__path__)))
    roots = [package / "shared", package / "client"]

    # By name: ``_discovered_dirs`` is the discovery registry (one entry per conventional
    # dir), not a list of mounts — the mounts are the component routes below.
    for entry in (getattr(app, "_discovered_dirs", None) or {}).values():
        roots.append(Path(entry["dir"]))
    for route in getattr(app, "_component_routes", None) or []:
        directory = getattr(getattr(route, "app", None), "directory", None)
        if directory:
            roots.append(Path(directory))

    unique: list[Path] = []
    for root in roots:
        root = Path(root)
        if root.is_dir() and root not in unique:
            unique.append(root)
    return unique


def _source_files(app) -> list[Path]:
    """The shell's source files, sorted so the digest never depends on walk order."""
    files: list[Path] = []
    seen: set[Path] = set()
    for root in _source_roots(app):
        for path in root.rglob("*"):
            if path.suffix in _SOURCE_SUFFIXES and path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return sorted(files)


def _shell_version(app, precache: list[str]) -> str:
    """The digest described in the module docstring."""
    from basis.server import static

    digest = hashlib.sha256()
    digest.update(SW_STRATEGY_VERSION.encode("utf-8"))
    digest.update(_sw_body().encode("utf-8"))
    digest.update(static.offline_pyscript_url().encode("utf-8"))
    digest.update("\n".join(precache).encode("utf-8"))
    for path in _source_files(app):
        stat = path.stat()
        digest.update(str(path).encode("utf-8"))
        digest.update(str(stat.st_mtime_ns).encode("utf-8"))
        digest.update(str(stat.st_size).encode("utf-8"))
    return digest.hexdigest()[:12]


def boot_plan_url(app, start_url: str) -> str | None:
    """The URL of the boot plan (``/pyscript.json?url=…``) for the start page, or ``None``.

    ``/pyscript.json`` is what the client boots *from*: no plan, no entrypoint, no
    bootstrap. PyScript's config fetch failing ends the boot before Python starts, so an
    offline start whose page is cached but whose plan is not renders the SSR markup and
    nothing else. The URL is per-route, so it is derived with the framework's own rule
    rather than re-spelled here: the registered start page's class, fed to
    :func:`~basis.shared.page.page_aware_config_url`.
    """
    from types import SimpleNamespace

    from basis.shared.page import page_aware_config_url

    page_cls = (getattr(app, "_pages", None) or {}).get(start_url)
    if page_cls is None:
        return None
    # The helper reads the request's route and nothing else.
    return page_aware_config_url(
        page_cls.pyscript_json_url, SimpleNamespace(url=SimpleNamespace(path=start_url))
    )


def precache_urls(app, base_url: str, store) -> list[str]:
    """The shell tier: the URLs installed workers fetch up front.

    The framework's own inventory (``/pyscript.json``'s file map) rather than a list
    written by hand, plus the URLs the client boot needs that no inventory carries: the
    app's ``start_url``, so a cold offline start lands on the app; that page's **boot
    plan**, without which a cached document cannot start Python at all; the client module
    that registers this worker in the first place; and the offline fallback, which a
    navigation reaches only when nothing else could be served — a fallback fetched from
    the network is not a fallback. Root-relative: a worker caches *requests*, and an
    absolute URL from one host is useless the moment the app is served from another (a
    tunnel, a LAN address, a preview deploy).

    The Pyodide runtime is deliberately absent — it is 14–18 MB, and an install-time
    download that size on a phone is hostile. It is warmed after control instead; see
    ``register.js``.
    """
    paths: list[str] = []
    for url in sorted(app.vfs.served_urls(base_url)):
        if url.startswith(base_url + "/"):
            paths.append(url[len(base_url):])
    for url in (
        store.start_url,
        boot_plan_url(app, store.start_url),
        REGISTER_URL,
        OFFLINE_URL,
    ):
        if url and url not in paths:
            paths.append(url)
    return paths


def service_worker_js(app, request, store) -> bytes:
    """The worker the browser registers: a config prelude, then the body.

    The prelude is the only bridge between the server's view of the app and the worker's
    runtime view; everything the body needs to decide is in it, so the body itself never
    has to guess at a URL.
    """
    base_url = str(request.base_url).removesuffix("/")
    precache = precache_urls(app, base_url, store)
    config = {
        "version": _shell_version(app, precache),
        "precache": precache,
        "offline": OFFLINE_URL,
        "assetsLimit": _ASSETS_LIMIT,
        "pagesLimit": _PAGES_LIMIT,
    }
    prelude = "const BASIS = " + json.dumps(config, separators=(",", ":")) + ";\n"
    return (prelude + _sw_body()).encode("utf-8")
