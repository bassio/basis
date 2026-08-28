"""Tests for ``@extra_style`` (additive component CSS) and the CSS-aware formatter.

``@extra_style`` lets a subclass add style blocks without copying the parent's
whole ``style()``; the CSS-aware formatter lets ``style()`` / ``@extra_style``
use the same pythonic ``{expr}`` fields as ``template()`` while CSS structural
braces pass through literally.
"""

from __future__ import annotations

from basis.shared.component import Component, extra_style, scoped
from basis.shared.element import Element
from basis.shared.expr import ALLOWED_BUILTINS, _CSS_FORMATTER, format_css_style


# ── CSS-aware formatter ────────────────────────────────────────────────────

def test_css_structural_braces_pass_through():
    css = ".a { color: red; }\nbody { margin: 0; }"
    assert format_css_style(css, None, ALLOWED_BUILTINS) == css


def test_css_fields_interpolate_from_class_context():
    class C:
        accent = "#7c5cff"
        spacing = 8

    css = ".a { background: {accent}; padding: {spacing}px; }"
    out = format_css_style(css, C, ALLOWED_BUILTINS)
    assert out == ".a { background: #7c5cff; padding: 8px; }"


def test_css_fields_nested_in_media_block():
    class C:
        bp = "600px"

    css = "@media (max-width: {bp}) { .a { color: red; } }"
    out = format_css_style(css, C, ALLOWED_BUILTINS)
    assert out == "@media (max-width: 600px) { .a { color: red; } }"


def test_css_failed_field_keeps_raw_text():
    class C:
        pass

    css = ".a { color: {missing}; }"
    assert format_css_style(css, C, ALLOWED_BUILTINS) == css


def test_css_non_expression_values_stay_literal():
    class C:
        pass

    css = ".a { transform: rotate({90deg}); width: {100%}; }"
    assert format_css_style(css, C, ALLOWED_BUILTINS) == css


def test_css_escaped_braces_collapse():
    css = '.a { content: "{{x}}"; }'
    assert format_css_style(css, None, ALLOWED_BUILTINS) == '.a { content: "{x}"; }'


def test_css_formatter_parse_yields_field_tuples():
    segs = list(_CSS_FORMATTER.parse(".a { color: {accent}; } b"))
    fields = [f for _l, f, _s, _c in segs if f is not None]
    assert fields == ["accent"]
    # The literal text is split around the field.
    assert any(".a { color: " in l for l, _f, _s, _c in segs)


# ── @extra_style ───────────────────────────────────────────────────────────

def test_extra_style_extraction_and_inheritance():
    class Base(Component):
        __tag__ = "base-extra"

        def template(self):
            """<div>hi</div>"""

        def style(self):
            """.x { color: red; }"""

        @extra_style
        def tweaks(self):
            """.x { padding: 4px; }"""

    class Child(Base):
        pass

    assert Base._get_extra_style_names() == ["tweaks"]
    assert Child._get_extra_style_names() == ["tweaks"]  # inherited
    assert ".x { padding: 4px; }" in Base._get_extra_style_strings()[0]
    assert Child._get_extra_style_strings() == Base._get_extra_style_strings()


def test_extra_style_dynamic_fields():
    class C(Component):
        __tag__ = "dyn-extra"
        accent = "#111"

        def template(self):
            """<div>hi</div>"""

        @extra_style
        def add(self):
            """.x { background: {accent}; }"""

    out = C._get_extra_style_strings()[0]
    assert ".x { background: #111; }" in out


def test_extra_style_scoped():
    class C(Component):
        __tag__ = "sc-extra"

        def template(self):
            """<div>hi</div>"""

        @scoped
        @extra_style
        def add(self):
            """.x { color: blue; }"""

    out = C._get_extra_style_strings()[0]
    assert out.startswith("@scope (sc-extra) {")
    assert "color: blue;" in out


def test_extra_style_classmethod():
    class C(Component):
        __tag__ = "cm-extra"

        def template(self):
            """<div>hi</div>"""

        @extra_style
        @classmethod
        def extra(cls):
            """body { margin: 0; }"""

    assert C._get_extra_style_names() == ["extra"]
    assert C._get_extra_style_strings() == ["body { margin: 0; }"]


def test_main_style_interpolates_class_attrs():
    class C(Component):
        __tag__ = "dyn-main"
        accent = "#222"

        def template(self):
            """<div>hi</div>"""

        def style(self):
            """.x { background: {accent}; }"""

    assert ".x { background: #222; }" in C._get_style_string()


def test_mount_app_injects_extra_style_after_main():
    class MountExtraStyleComp(Component):
        __tag__ = "mount-extra"

        def template(self):
            """<div>hi</div>"""

        def style(self):
            """.x { color: red; }"""

        @extra_style
        def add(self):
            """.x { color: blue; }"""

    container = Element("div", {}, [])
    MountExtraStyleComp.mount_app(container, replace=False)

    def _is_style(el):
        return getattr(el, "tagName", "") == "style"

    styles = [c for c in container.children if _is_style(c)]
    mine = [s for s in styles
            if s.getAttribute("data-component-class") == "MountExtraStyleComp"]
    main = [s for s in mine if not s.getAttribute("data-extra-style")]
    extras = [s for s in mine if s.getAttribute("data-extra-style")]

    assert len(main) == 1
    assert len(extras) == 1
    assert extras[0].getAttribute("data-extra-style") == "add"
    # The extra block lands after the main stylesheet so it wins at equal
    # specificity.
    assert container.children.index(main[0]) < container.children.index(extras[0])


# ── Page.stylesheets (override layer) ──────────────────────────────────────

def test_page_stylesheets_rendered_after_ssr_root():
    from fastapi.testclient import TestClient

    from basis.server.app import Basis
    from basis.shared.page import Page

    class Root(Component):
        """<div>hi</div>"""

    app = Basis()
    app.bootstrap()

    class MyPage(Page):
        title = "Styles"
        root_component = Root
        entry_module = "/test_root.py"
        stylesheets = ("/static/app.css",)

    app.include_page("/stylesheets", page_cls=MyPage)

    resp = TestClient(app).get("/stylesheets")
    assert resp.status_code == 200
    assert '<link rel="stylesheet" href="/static/app.css"' in resp.text
    # The override layer must land AFTER the SSR root (where component <style>
    # elements are injected) so it wins the cascade at equal specificity.
    assert resp.text.index("basis-ssr-root") < resp.text.index("/static/app.css")


def test_page_stylesheets_default_empty():
    from basis.shared.page import Page

    assert Page.stylesheets == ()


# ── ThemeStore hydration guard + seed ──────────────────────────────────────

def test_theme_store_serializes_dark_mode_seed():
    from basis.plugins.theme import ThemeStore

    t = ThemeStore("theme_serialize_test")
    t.dark_mode = True
    assert t.serialize().get("dark_mode") is True


def test_theme_store_guard_skips_defaults_when_hydrated(monkeypatch):
    from basis.plugins.theme import ThemeStore
    from basis.shared import store as store_module

    real_init = store_module.Store.__init__

    def hydrated_init(self, name):
        real_init(self, name)
        # Simulate SSR hydration running inside Store.__init__ (it reads
        # #basis-initial-state): a persisted dark seed arrives as dark_mode=True
        # and the hydrated flag is set before ThemeStore.__init__'s body runs.
        self.__dict__["dark_mode"] = True
        self.__dict__["_hydrated_from_ssr"] = True

    monkeypatch.setattr(store_module.Store, "__init__", hydrated_init)
    t = ThemeStore("theme_hydration_test")
    assert t.dark_mode is True  # NOT clobbered by the built-in default
