"""P3 — theme registry + managers (ROADMAP-THEMING.md §6.5, §8 P3).

Covers: the `Theme(BasisPlugin)` classification (`kind="theme"`), the shared
kind-filtered registry listing (`$plugins` vs `$themes`), the `$theme` control
plane (app-bound, `set_theme`/`set_mode`/`set_accent` + `basis_theme` cookie
persistence), cookie-applied SSR/CSR first paint (no FOUC), and the shared
`RegistryManager` base behind `<ui-plugin-manager>` / `<ui-theme-picker>`.
"""

import json
from types import SimpleNamespace

import pytest

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page
from basis.shared.plugin_registry import _plugin_listing, _registry_listing
from fastapi.testclient import TestClient


# --- classification: themes are a kind of plugin ----------------------------

def test_default_theme_registered_as_kind_theme():
    app = Basis()
    app.bootstrap()
    reg = app._plugin_registrations["theme_basis"]
    assert reg.plugin.kind == "theme"
    assert reg.plugin.definition.id == "basis"
    # the mechanism plugin itself is a plain plugin
    assert app._plugin_registrations["theme"].plugin.kind == "plugin"


def test_themes_catalog_vs_plugin_listing():
    app = Basis()
    app.bootstrap()
    themes = _registry_listing(app, kinds=("theme",))
    assert "theme_basis" in themes
    entry = themes["theme_basis"]
    assert entry["kind"] == "theme"
    assert entry["theme"]["id"] == "basis"
    assert entry["theme"]["name"] == "Basis Default"
    assert entry["theme"]["modes"] == ["light", "dark"]
    # themes never appear in the plugin listing / plugin manager
    assert "theme_basis" not in _plugin_listing(app)
    assert "theme_basis" not in _registry_listing(app, kinds=("plugin",))


def test_themes_endpoints_partition():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    plugins = client.get("/basis/api/plugins").json()
    themes = client.get("/basis/api/themes").json()
    assert "theme_basis" not in plugins
    assert "theme_basis" in themes
    assert themes["theme_basis"]["theme"]["id"] == "basis"


# --- $theme control plane ---------------------------------------------------

def test_theme_store_is_app_bound():
    from basis.plugins.theme.store import ThemeStore
    assert ThemeStore._requires_app is True


def test_set_mode_action_sets_persist_cookie():
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    r = client.post("/basis/api/action", json={
        "path": "basis.plugins.theme.store.ThemeStore.set_mode",
        "store_name": "theme", "args": ["dark"], "kwargs": {},
    })
    assert r.status_code == 200
    assert r.json()["data"] == "mode dark"
    set_cookie = r.headers.get("set-cookie", "")
    assert "basis_theme=" in set_cookie
    assert "dark_mode" in set_cookie


def test_set_theme_preserves_persisted_mode():
    """Applying a theme via RPC must NOT reset the persisted color mode.

    ``apply_request`` (the ``basis_theme`` cookie) runs before the action in the
    RPC handler, so the server-side store starts from the saved prefs and the
    returned ``new_state`` keeps ``dark_mode`` (regression: switching themes
    used to revert dark → light on the client).
    """
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    r = client.post(
        "/basis/api/action",
        json={
            "path": "basis.plugins.theme.store.ThemeStore.set_theme",
            "store_name": "theme", "args": ["ambient"], "kwargs": {},
        },
        cookies={"basis_theme": json.dumps({"active_theme": "basis", "dark_mode": True})},
    )
    assert r.status_code == 200
    new_state = r.json()["new_state"]
    assert new_state["active_theme"] == "ambient"
    # the persisted dark mode survives the theme switch
    assert new_state["dark_mode"] is True
    # and the response cookie persists both prefs
    assert "dark_mode" in r.headers.get("set-cookie", "")


def test_set_mode_preserves_active_theme():
    """Toggling the mode via RPC must NOT reset the active theme — the cookie is
    applied first, so ``set_mode`` returns ``new_state`` that keeps it."""
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    r = client.post(
        "/basis/api/action",
        json={
            "path": "basis.plugins.theme.store.ThemeStore.set_mode",
            "store_name": "theme", "args": ["dark"], "kwargs": {},
        },
        cookies={"basis_theme": json.dumps({"active_theme": "ambient", "dark_mode": False})},
    )
    assert r.status_code == 200
    new_state = r.json()["new_state"]
    assert new_state["dark_mode"] is True
    # the active theme survives the mode toggle
    assert new_state["active_theme"] == "ambient"


def test_set_theme_unknown_raises():
    import asyncio
    from basis.plugins.theme.store import ThemeStore
    store = ThemeStore("theme_unknown_test")
    with pytest.raises(ValueError):
        asyncio.run(store.set_theme("nope"))


def test_set_theme_applies_default_definition():
    import asyncio
    from basis.plugins.theme.store import ThemeStore
    from basis.plugins.theme.default import DEFAULT_TOKENS
    store = ThemeStore("theme_apply_test")
    asyncio.run(store.set_theme("basis"))
    assert store.active_theme == "basis"
    assert store.accent_color == DEFAULT_TOKENS.accent_color


# --- no-FOUC: cookie applied to SSR + CSR initial state ---------------------

def _themed_page():
    import basis.plugins.theme  # noqa: F401  # registers <ui-theme-provider>

    app = Basis()
    app.bootstrap()

    class Root(Component):
        template = "<div><ui-theme-provider></ui-theme-provider></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    return app, DemoPage


def test_ssr_first_paint_uses_persisted_cookie():
    app, _ = _themed_page()
    client = TestClient(app)
    # default → light
    assert "color-scheme: light" in client.get("/demo").text
    # persisted cookie → dark on the SSR first paint (no FOUC)
    html = client.get("/demo", cookies={
        "basis_theme": json.dumps({"active_theme": "basis", "dark_mode": True})
    }).text
    assert "color-scheme: dark" in html
    state = json.loads(html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0])
    assert state["theme"]["dark_mode"] is True
    assert state["theme"]["active_theme"] == "basis"
    # the catalog hydrates too
    assert "themes" in state
    assert "theme_basis" in state["themes"]["items"]


def test_csr_initial_state_applies_persisted_cookie():
    import asyncio
    from basis.server.render import render_page

    app, page_cls = _themed_page()
    html = asyncio.run(render_page(
        SimpleNamespace(
            app=app,
            cookies={"basis_theme": json.dumps({"active_theme": "basis", "dark_mode": True})},
        ),
        page_cls,
        render_mode="csr",
    ))
    assert 'id="basis-initial-state"' in html
    state = json.loads(html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0])
    assert state["theme"]["dark_mode"] is True


# --- shared RegistryManager: the theme picker -------------------------------

def test_theme_picker_renders_catalog():
    import basis.plugins.ui.theme_picker.theme_picker  # noqa: F401  # registers <ui-theme-picker>

    app = Basis()
    app.bootstrap()

    class Root(Component):
        template = "<div><ui-theme-picker></ui-theme-picker></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    html = TestClient(app).get("/demo").text
    assert "Themes" in html
    assert "Basis Default" in html
    assert "light/dark" in html
    assert "Apply" in html


def test_plugin_manager_shares_registry_manager_base():
    from basis.plugins.ui.plugin_manager.plugin_manager import PluginManager
    from basis.plugins.ui.registry_manager.registry_manager import RegistryManager
    from basis.plugins.ui.theme_picker.theme_picker import ThemePicker
    assert issubclass(PluginManager, RegistryManager)
    assert issubclass(ThemePicker, RegistryManager)
    assert PluginManager.registry == "plugins"
    assert ThemePicker.registry == "themes"
    assert PluginManager.__tag__ == "ui-plugin-manager"
    assert ThemePicker.__tag__ == "ui-theme-picker"


# --- P4: theme packages (manifest validation, ambient dogfood, static, CLI) --

def test_invalid_theme_definition_raises_loudly():
    from basis.plugins.theme.schema import ThemeDefinition, ThemeTokens
    # bad id (not a valid slug)
    with pytest.raises(ValueError, match="id"):
        ThemeDefinition(id="bad id!", name="X")
    # invalid token value — a length in a color slot
    with pytest.raises(ValueError, match="accent_color"):
        ThemeDefinition(id="bad", name="X", tokens=ThemeTokens(accent_color="0.5rem"))
    # a valid minimal theme passes
    ThemeDefinition(id="ok", name="OK")


def test_ambient_theme_registered_and_switchable():
    import basis.plugins.theme  # noqa: F401  # registers <ui-theme-provider>

    app = Basis()
    app.bootstrap()
    themes = _registry_listing(app, kinds=("theme",))
    assert "theme_ambient" in themes
    assert themes["theme_ambient"]["theme"]["id"] == "ambient"

    class Root(Component):
        template = "<div><ui-theme-provider></ui-theme-provider></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    client = TestClient(app)

    # apply via RPC → persisted cookie
    r = client.post("/basis/api/action", json={
        "path": "basis.plugins.theme.store.ThemeStore.set_theme",
        "store_name": "theme", "args": ["ambient"], "kwargs": {},
    })
    assert r.status_code == 200
    assert "basis_theme=" in r.headers.get("set-cookie", "")

    # SSR with the ambient cookie renders the ambient (teal) accent
    html = client.get("/demo", cookies={
        "basis_theme": json.dumps({"active_theme": "ambient", "dark_mode": False})
    }).text
    assert "light-dark(#0E7490, #22D3EE)" in html  # ambient teal accent


def test_disable_active_theme_falls_back_to_default():
    import asyncio

    import basis.plugins.theme  # noqa: F401

    app = Basis()
    app.bootstrap()

    class Root(Component):
        template = "<div><ui-theme-provider></ui-theme-provider></div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    client = TestClient(app)
    cookie = {"basis_theme": json.dumps({"active_theme": "ambient", "dark_mode": False})}

    # active = ambient
    assert "light-dark(#0E7490, #22D3EE)" in client.get("/demo", cookies=cookie).text
    # disable the ambient theme plugin → the next render unwinds to the default
    asyncio.run(app.disable_plugin("theme_ambient"))
    html = client.get("/demo", cookies=cookie).text
    assert "light-dark(#6E5FD8, #9384F5)" in html  # basis indigo accent
    state = json.loads(html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0])
    assert state["theme"]["active_theme"] == "basis"


def test_theme_with_static_dir_serves_files(tmp_path):
    """A theme package that ships css/fonts serves them via its static mount
    (defaulted to the package path — the isomorphism rule)."""
    from basis.plugins.theme.schema import ThemeDefinition, ThemeTokens
    from basis.plugins.theme.theme import Theme

    pkg = tmp_path / "tmptheme"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "static").mkdir()
    (pkg / "static" / "theme.css").write_text("/* tmptheme extra css */")

    theme_plugin = Theme(
        definition=ThemeDefinition(id="tmptheme", name="Tmp Theme",
                                   tokens=ThemeTokens(accent_color="#123456")),
        static_dir=pkg,
    )
    # default static mount derives to the package path (VFS == filesystem)
    assert theme_plugin.static_mount == "/tmptheme"

    app = Basis()
    app.bootstrap()
    app.include_plugin(theme_plugin)
    r = TestClient(app).get("/tmptheme/static/theme.css")
    assert r.status_code == 200
    assert "tmptheme extra css" in r.text


def test_theme_cli_list_and_apply():
    from typer.testing import CliRunner

    from basis.cli.main import app as cli_app

    runner = CliRunner()
    result = runner.invoke(cli_app, ["theme", "list"])
    assert result.exit_code == 0
    assert "ambient" in result.output
    assert "Basis Ambient" in result.output
    assert "basis" in result.output

    result = runner.invoke(cli_app, ["theme", "apply", "ambient"])
    assert result.exit_code == 0
    assert "Basis Ambient (ambient) — valid." in result.output

    result = runner.invoke(cli_app, ["theme", "apply", "does-not-exist"])
    assert result.exit_code == 1
    assert "Unknown theme" in result.output
