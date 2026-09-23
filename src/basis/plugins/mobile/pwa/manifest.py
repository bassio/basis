"""The web manifest — the app's installable identity, as the browser reads it.

Generated per request from the app's ``$pwa`` declaration plus the active ``$theme``,
because two of its fields are design decisions rather than constants: ``theme_color`` and
``background_color`` come from the theme the *user* is on, so an install started in dark
mode gets the dark splash screen. Everything else is the declaration, passed through.

Optional keys are omitted rather than sent empty: a manifest is validated, and
``"shortcuts": null`` / ``"icons": []`` are errors, not no-ops. ``theme_color`` follows
the same rule — no theme store, no color, which the spec allows and a wrong color is not.
"""

import json

from basis.plugins.mobile.pwa.icons import icon_items


async def resolve_theme(request):
    """The request's ``$theme`` store with its per-request hook applied, or ``None``.

    Rebuilt from the blueprint because the render engines' hook sweep only runs for page
    renders: a plain route has to ask, or it would read whatever theme the last page left
    behind. ``run_apply_request`` is the framework's own tolerant caller (sync or async
    hook, exceptions swallowed) — a broken theme read must not take down the manifest.
    """
    from basis.shared.store import Store, attach_app_to_store, run_apply_request

    if "theme" not in Store.all_names():
        return None
    theme = Store.reinstantiate("theme")
    if theme is None:
        return None
    attach_app_to_store(theme, request.app)
    await run_apply_request(theme, request)
    return theme


def theme_colors(theme) -> dict:
    """The theme's browser-chrome color for the mode it is in, as manifest keys."""
    if theme is None:
        return {}
    dark = bool(getattr(theme, "dark_mode", False))
    color = (
        getattr(theme, "theme_color_dark", None)
        if dark
        else getattr(theme, "theme_color_light", None)
    )
    return {"theme_color": color} if color else {}


def build_manifest(store, theme=None, fallback_title: str | None = None) -> dict:
    """The manifest document for an app whose ``$pwa`` store is *store*.

    ``fallback_title`` names the app when the declaration gives no ``title``: the app's
    own directory name is the one piece of identity the framework already knows.
    """
    name = store.title or fallback_title or "Basis App"

    manifest: dict = {
        "name": name,
        "short_name": store.short_name or name,
        "start_url": store.start_url,
        "scope": store.scope,
        "display": store.display,
        "icons": icon_items(store),
        "prefer_related_applications": False,
    }
    if store.description:
        manifest["description"] = store.description
    if store.shortcuts:
        manifest["shortcuts"] = list(store.shortcuts)

    colors = theme_colors(theme)
    if colors:
        manifest["theme_color"] = colors["theme_color"]
        # The install splash is a solid fill, so it reuses the chrome color unless the app
        # made its own call.
        manifest["background_color"] = store.background_color or colors["theme_color"]
    elif store.background_color:
        manifest["background_color"] = store.background_color

    return manifest


def manifest_body(store, theme=None, fallback_title: str | None = None) -> bytes:
    """The manifest as the bytes a response carries (compact, no trailing whitespace)."""
    return json.dumps(
        build_manifest(store, theme=theme, fallback_title=fallback_title),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def app_title(request) -> str | None:
    """The app's directory name — the identity a bare declaration inherits."""
    app_dir = getattr(request.app, "_app_dir", None)
    name = getattr(app_dir, "name", None)
    return name or None
