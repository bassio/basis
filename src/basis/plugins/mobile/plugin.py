"""The mobile plugin — the optional half of Basis's mobile story.

Registered through the standard ``basis.plugins`` entry point like any third-party
plugin, so it rides the normal discovery, ``requires``, enable/disable and static-serving
lifecycle. Two things make it *optional* rather than merely non-essential:

- **Nothing happens without a declaration.** The gate is the app's own ``PwaStore``
  (``stores/pwa.py``), the same convention an app uses to declare its theme. An app that
  never declares one gets no store in ``#basis-initial-state`` and no head contribution —
  there is no per-app switch to remember to turn off.
- **The plugin is registered with ``prefix=""`` because its URLs are document-level.**
  A manifest link is a fact about the whole origin, and a service worker's scope can
  never exceed the directory it is served from, so anything this plugin serves the
  browser by URL has to sit at the origin root — the shape ``basis.plugins.theme`` uses
  for ``/basis/api/themes``.

Routes belong on ``plugin.router``: those are the ones ``remove_plugin`` unwinds, so
disabling the plugin leaves no half-served app behind.

This module is served to the browser at ``/basis/plugins/mobile``, so it must import in
PyScript: ``basis.shared.plugin`` (never ``basis.server.plugin``), and server-only
imports stay inside the handlers.
"""

from pathlib import Path

from basis.shared.plugin import BasisPlugin, Request
from basis.plugins.mobile.pwa import (
    ICON_SIZES,
    ICON_URL,
    MANIFEST_URL,
    OFFLINE_URL,
    SERVICE_WORKER_URL,
)


def pwa_declared() -> bool:
    """Whether the app declared a ``PwaStore`` — the plugin's opt-in.

    Read from the persistent blueprint registry, not the live store registry: the live
    registry is cleared per request, while a declaration outlives it. App ``stores/`` are
    imported before plugin discovery, so this is already the truth when ``on_register``
    runs (the ordering the theme plugin depends on too).
    """
    from basis.shared.store import Store

    return "pwa" in Store.all_names()


def pwa_store():
    """The app's declared PWA store, or ``None`` when the app has not opted in.

    Rebuilt from the blueprint so the caller gets the app's own declaration (fields
    included) rather than whatever a previous request left behind.
    """
    from basis.shared.store import Store

    if not pwa_declared():
        return None
    return Store.reinstantiate("pwa")


class MobilePlugin(BasisPlugin):
    """Makes a declared Basis app installable and offline-capable."""

    def on_register(self, app) -> None:
        """Put the app's ``$pwa`` declaration in the render set.

        A default page already resolves every declared store, so this only matters for a
        page with an explicit ``Page.stores`` list that forgets to name it — a subtle
        failure (no manifest link, no installability on that page only).

        Deliberately the *app's* ``include_store`` rather than the plugin's: the plugin
        method also records the store on the plugin instance for unwinding, and a plugin
        instance is shared by every app in the process — so a second app would be handed a
        declaration it never made. The declaration is the app's, not the plugin's, and
        outlives the plugin for the same reason.
        """
        if not pwa_declared():
            return
        app.include_store("pwa")


plugin = MobilePlugin(
    prefix="",
    serving_dir=Path(__file__).parent,
    serving_mount="/basis/plugins/mobile",
    name="mobile",
    tags=None,
    requires=[],
)


@plugin.router.get(MANIFEST_URL)
async def _manifest(request: Request):
    """The app's web manifest, generated from its declaration and the active theme.

    404 for an app that never declared a PWA: nothing links here in that case, and a
    manifest describing an app that did not opt in would be a lie the browser acts on.
    """
    from fastapi.responses import Response
    from basis.plugins.mobile.pwa.manifest import app_title, manifest_body, resolve_theme
    from basis.server.static import conditional_response

    store = pwa_store()
    if store is None:
        return Response(status_code=404)

    theme = await resolve_theme(request)
    body = manifest_body(store, theme=theme, fallback_title=app_title(request))
    # Content-hash ETag + revalidate: the body changes with the theme cookie, so a mode
    # switch gets a fresh 200 and an unchanged one gets a 304.
    return conditional_response(
        body,
        "application/manifest+json",
        scope=request.scope,
        if_none_match=request.headers.get("if-none-match"),
    )


@plugin.router.get(SERVICE_WORKER_URL)
async def _service_worker(request: Request):
    """The app-shell worker: the declaration's ``offline`` switch, plus the shell.

    404 when the app did not ask for offline, and when it never declared a PWA at all.
    ``Service-Worker-Allowed: /`` is what lets a worker served from this path control the
    whole origin — without it the scope would be this plugin's directory, and the app
    would stay permanently uncontrolled. ``no-cache`` matters for the same reason it does
    on any worker: a cached script can hide an update for up to a day.
    """
    from fastapi.responses import Response
    from basis.plugins.mobile.pwa.service_worker import service_worker_js
    from basis.server.static import conditional_response

    store = pwa_store()
    if store is None or not store.offline:
        return Response(status_code=404)

    return conditional_response(
        service_worker_js(request.app, request, store),
        "application/javascript",
        scope=request.scope,
        headers={"Service-Worker-Allowed": "/"},
        if_none_match=request.headers.get("if-none-match"),
    )


@plugin.router.get(ICON_URL)
async def _placeholder_icon(request: Request, size: str):
    """The generated placeholder icon, colored from the theme the request is on.

    Served rather than inlined so the manifest can reference a real, cacheable URL. The
    sizes are an allowlist: the URL space is the plugin's, and a raster nobody asked for
    is work done on every request.
    """
    from fastapi.responses import Response
    from basis.plugins.mobile.pwa.icons import generated_png
    from basis.plugins.mobile.pwa.manifest import resolve_theme
    from basis.server.static import conditional_response

    if pwa_store() is None or not size.isdigit() or int(size) not in ICON_SIZES:
        return Response(status_code=404)

    theme = await resolve_theme(request)
    return conditional_response(
        generated_png(int(size), theme),
        "image/png",
        scope=request.scope,
        if_none_match=request.headers.get("if-none-match"),
    )


@plugin.router.get(OFFLINE_URL)
async def _offline(request: Request):
    """The fallback document a navigation lands on when there is no network and no
    cached copy of the route itself.

    404 when the app declared no PWA *or* turned offline off: nothing links here in
    either case — the worker that would fall back to it does not exist.

    Rendered like any other page (a ``StaticPage``: stores, hooks and chrome, no
    client), so the fallback wears the app's own theme and head links instead of a
    document written out by hand here.
    """
    from fastapi.responses import Response
    from basis.plugins.mobile.pwa.offline import OfflinePage
    from basis.server.render import render_page
    from basis.server.static import conditional_response

    store = pwa_store()
    if store is None or not store.offline:
        return Response(status_code=404)

    html = await render_page(request, OfflinePage)
    # Content-hash ETag: the document changes with the theme cookie (its scheme and
    # tokens follow the theme), so a mode switch gets a fresh 200 and an unchanged one
    # a 304.
    return conditional_response(
        html.encode("utf-8"),
        "text/html; charset=utf-8",
        scope=request.scope,
        if_none_match=request.headers.get("if-none-match"),
    )
