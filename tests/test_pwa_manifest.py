"""``$pwa`` — the app's installable identity, and the plugin's manifest route.

Covers the manifest document and the route that serves it: the identity comes from the
declaration, the colors follow the active theme (cookie-applied, so a dark-mode install
gets a dark splash), the icons are the app's or the generated pair, optional keys are
omitted rather than sent empty, and an app that never declared a PWA gets a 404.
"""
import json

import pytest
from fastapi.testclient import TestClient

from basis.plugins.mobile import PwaStore
from basis.plugins.mobile.pwa import ICON_SIZES, ICON_URL, MANIFEST_URL
from basis.plugins.mobile.pwa.icons import generated_png, parse_color
from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page
from basis.shared.store import Store


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes
    Store._registry.clear()
    Store._store_blueprints.clear()


def _boot_app():
    """A one-page app, with whatever ``PwaStore`` the caller already declared."""
    app = Basis()
    app.bootstrap()

    class ManifestRoot(Component):
        template = "<div>hi</div>"

    class ManifestPage(Page):
        title = "manifest"
        root_component = ManifestRoot

    app.include_page("/demo", page_cls=ManifestPage)
    return app


def _app(**declaration):
    """An opted-in app; *declaration* is the ``PwaStore``'s fields (none = bare)."""
    PwaStore("pwa", **declaration)
    return _boot_app()


def _app_without_a_declaration():
    """An app that never opted in."""
    return _boot_app()


def _manifest(app, **kwargs):
    response = TestClient(app).get(MANIFEST_URL, **kwargs)
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/manifest+json")
    return json.loads(response.text)


def test_an_app_that_declared_nothing_gets_a_404():
    app = _app_without_a_declaration()
    assert TestClient(app).get(MANIFEST_URL).status_code == 404


def test_the_identity_comes_from_the_declaration():
    app = _app(
        title="Myapp",
        short_name="My",
        description="A test app",
        start_url="/app",
        scope="/app/",
        display="fullscreen",
    )
    manifest = _manifest(app)

    assert manifest["name"] == "Myapp"
    assert manifest["short_name"] == "My"
    assert manifest["description"] == "A test app"
    assert manifest["start_url"] == "/app"
    assert manifest["scope"] == "/app/"
    assert manifest["display"] == "fullscreen"
    assert manifest["prefer_related_applications"] is False


def test_the_app_directory_name_stands_in_for_a_missing_title():
    app = _app()
    manifest = _manifest(app)

    # The route passes the app's own directory name as the fallback identity.
    assert manifest["name"] == app._app_dir.name
    assert manifest["short_name"] == manifest["name"]


def test_the_fallback_title_rule():
    from basis.plugins.mobile.pwa.manifest import build_manifest

    store = PwaStore("pwa_fallback")

    assert build_manifest(store, fallback_title="myapp")["name"] == "myapp"
    assert build_manifest(store)["name"] == "Basis App"
    assert build_manifest(store, fallback_title="myapp")["short_name"] == "myapp"
    # A declared title always wins over the fallback.
    assert build_manifest(PwaStore("pwa_titled", title="Mine"), fallback_title="myapp")[
        "name"
    ] == "Mine"


def test_optional_keys_are_omitted_rather_than_sent_empty():
    """A manifest is validated: "shortcuts": null / "description": null are errors."""
    app = _app(title="Myapp")
    manifest = _manifest(app)

    assert "description" not in manifest
    assert "shortcuts" not in manifest
    assert "background_color" not in manifest or manifest["background_color"]


def test_declared_shortcuts_pass_through():
    shortcuts = [{"name": "New note", "url": "/new"}]
    app = _app(title="Myapp", shortcuts=shortcuts)

    assert _manifest(app)["shortcuts"] == shortcuts


def test_the_chrome_color_follows_the_active_theme():
    app = _app(title="Myapp", background_color="#000000")
    client = TestClient(app)
    light = json.loads(client.get(MANIFEST_URL).text)
    dark = json.loads(
        client.get(
            MANIFEST_URL,
            cookies={
                "basis_theme": json.dumps({"active_theme": "basis", "dark_mode": True})
            },
        ).text
    )

    assert light["theme_color"] == "#f6f6f7"  # the basis theme, light
    assert dark["theme_color"] == "#1b2029"   # …and dark
    # The app's own splash color outranks the derived one.
    assert light["background_color"] == "#000000"


def test_a_declared_icon_is_used_as_given():
    app = _app(
        title="Myapp",
        icons=[
            "/static/icon-192.png",
            {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
        ],
    )

    assert _manifest(app)["icons"] == [
        {"src": "/static/icon-192.png"},
        {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
    ]


def test_placeholder_icons_meet_the_install_criteria():
    """No declaration of icons still yields the 192 + 512 pair the browser asks for."""
    app = _app(title="Myapp")
    icons = _manifest(app)["icons"]

    assert [icon["sizes"] for icon in icons] == ["192x192", "512x512"]
    assert icons[0]["purpose"] == "any"
    assert "maskable" in icons[1]["purpose"]
    assert all(icon["type"] == "image/png" for icon in icons)


def test_the_manifest_is_revalidated_not_recached():
    app = _app(title="Myapp")
    client = TestClient(app)

    first = client.get(MANIFEST_URL)
    assert first.headers["cache-control"] == "no-cache"
    etag = first.headers["etag"]

    again = client.get(MANIFEST_URL, headers={"if-none-match": etag})
    assert again.status_code == 304


@pytest.mark.parametrize("size", ICON_SIZES)
def test_the_placeholder_route_serves_a_png_of_that_size(size):
    app = _app(title="Myapp")
    response = TestClient(app).get(ICON_URL.format(size=size))

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    body = response.content
    assert body.startswith(b"\x89PNG\r\n\x1a\n")
    # IHDR follows the signature: length(4) + tag(4) + width(4) + height(4).
    assert int.from_bytes(body[16:20], "big") == size
    assert int.from_bytes(body[20:24], "big") == size


def test_a_later_app_in_the_same_process_is_not_handed_the_earlier_declaration():
    """The declaration is per app. A plugin *instance* is shared by every app in the
    process, so it must not carry one app's store into another app's render set."""
    declaring = _app(title="Myapp")
    assert TestClient(declaring).get(MANIFEST_URL).status_code == 200

    Store._registry.clear()
    Store._store_blueprints.clear()
    second = _app_without_a_declaration()

    assert TestClient(second).get(MANIFEST_URL).status_code == 404
    assert "pwa" not in [cfg["name"] for cfg in second._global_stores]


def test_the_placeholder_route_refuses_other_sizes():
    app = _app(title="Myapp")
    client = TestClient(app)

    assert client.get("/basis/plugins/mobile/pwa/icon-1024.png").status_code == 404
    assert client.get("/basis/plugins/mobile/pwa/icon-huge.png").status_code == 404


def test_the_placeholder_route_is_404_without_a_declaration():
    app = _app_without_a_declaration()
    assert TestClient(app).get(ICON_URL.format(size=192)).status_code == 404


# ── the placeholder's own ingredients ──────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ("#f5f5f7", (245, 245, 247)),
        ("#abc", (170, 187, 204)),
        ("#11223344", (17, 34, 51)),
        ("rgb(1, 2, 3)", (1, 2, 3)),
        ("rgba(4, 5, 6, 0.5)", (4, 5, 6)),
        ("light-dark(#fff, #000)", None),
        ("var(--bg-primary)", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_color_understands_literals_only(value, expected):
    assert parse_color(value) == expected


def test_the_generated_png_is_a_png_for_the_size_and_colors_asked_for():
    from basis.plugins.mobile.pwa.icons import placeholder_png

    plain = placeholder_png(8, (255, 255, 255), (0, 0, 0))
    inverted = placeholder_png(8, (0, 0, 0), (255, 255, 255))

    assert plain.startswith(b"\x89PNG\r\n\x1a\n") and plain.endswith(b"IEND\xaeB`\x82")
    assert plain != inverted
    # Same inputs, same bytes — the pixels are a pure function of the three arguments.
    assert plain == placeholder_png(8, (255, 255, 255), (0, 0, 0))


def test_a_theme_token_that_cannot_be_rasterized_falls_back_to_the_chrome_color():
    """``light-dark()`` is a legal token value and an illegal pixel."""

    class FakeTheme:
        bg_primary = "light-dark(#ffffff, #000000)"
        accent_color = "var(--accent)"
        theme_color_light = "#123456"

    body = generated_png(8, FakeTheme())

    assert body.startswith(b"\x89PNG\r\n\x1a\n")
