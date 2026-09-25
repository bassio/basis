"""Tests for ``@extra_style`` (additive component CSS) and the CSS-aware formatter.

``@extra_style`` lets a subclass add style blocks without copying the parent's
whole ``style()``; the CSS-aware formatter lets ``style()`` / ``@extra_style``
use the same pythonic ``{expr}`` fields as ``template()`` while CSS structural
braces pass through literally. The module also holds the ``@scoped`` contract that
keeps a stylesheet valid for every tag a family ships.
"""

from __future__ import annotations

import re

from _catalogue import AUDITED, COMMENT
from basis.plugins.regions.region import Region
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


# ── the @scoped contract across the shipped catalogue ──────────────────────

def _style_owning_families():
    """Audited classes grouped by the class that owns the stylesheet they use."""
    families: dict = {}
    for _name, cls in AUDITED.items():
        owner = cls
        while "style" not in owner.__dict__ and len(owner.__mro__) > 1:
            owner = owner.__mro__[1]
        families.setdefault(owner, set()).add(cls)
    return families


def test_a_family_that_ships_alias_tags_scopes_its_stylesheet():
    """``<shell-sidebar-left>`` is a ``Sidebar``; ``<ui-theme-picker>`` is a
    ``RegistryManager``. Both inherit the base's stylesheet.

    A host rule keyed on the *base* tag leaves an alias's host a real box — the flex item
    becomes the host — and a rule listing the alias tags by hand has to be kept in step
    with every new alias. ``@scoped`` wraps the stylesheet in the tag of the class the
    stylesheet is resolved *for*, so one ``:scope`` rule is correct for the whole family.
    """
    aliases = {
        owner: members
        for owner, members in _style_owning_families().items()
        if len({member.__tag__ for member in members}) > 1
    }
    assert aliases, "no audited family ships alias tags — this guard has gone stale"

    for owner, members in aliases.items():
        for cls in (owner, *members):
            assert f"@scope ({cls.__tag__})" in cls._get_style_string(), (
                f"{cls.__name__} ships <{cls.__tag__}> but its stylesheet is not scoped "
                "to that tag"
            )


def _selector_terms(css):
    """Every selector in *css*, one per comma-separated item (keyframe steps excluded)."""
    for head in re.findall(r"([^{}]+)\{", css):
        lines = head.strip().splitlines()
        if not lines:
            continue
        text = lines[-1].strip()
        if text.startswith("@"):
            continue
        for item in (part.strip() for part in text.split(",")):
            if item and not re.fullmatch(r"(\d+%|from|to)", item):
                yield item


def test_no_stylesheet_names_its_own_tag():
    """A component addresses its own root as ``:scope``, never by tag.

    A bare tag term fits exactly one tag, and inside a scoped stylesheet it is worse than
    redundant: a scoped selector may not name an element outside the scope root, so a
    term that reaches an ancestor (``.shell-stack > shell-activity-bar > …``) makes the
    whole rule match nothing — silently. ``:scope`` is the root, so one rule covers every
    tag a family ships (``<shell-sidebar-left>``) and can still carry ancestor context.

    The region primitive is included because it is a component like any other, even
    though the touch/mobile audits do not walk its package.
    """
    candidates = {**AUDITED, "basis.plugins.regions.region.Region": Region}

    offenders = sorted(
        {
            cls.__tag__
            for cls in candidates.values()
            if any(
                re.search(
                    rf"(?<![\w.-]){re.escape(cls.__tag__)}(?![\w-])", term
                )
                for term in _selector_terms(COMMENT.sub("", cls._get_style_string() or ""))
            )
        }
    )
    assert not offenders, f"stylesheets naming their own tag: {offenders}"


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


def test_mount_with_providers_no_longer_injects_component_styles():
    """``mount_with_providers`` is a plain low-level mount — it does not inject
    component ``<style>`` elements into the container (styles live in-tree in the
    Page ``<head>`` ``component_style_items`` loop)."""
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
    MountExtraStyleComp.mount_with_providers(container, replace=False)

    def _is_style(el):
        return getattr(el, "tagName", "") == "style"

    # No component <style> is injected into the container (only the component's
    # own template root is mounted).
    assert [c for c in container.children if _is_style(c)] == []

    # The ordering contract that used to live in the injection (main stylesheet
    # before its @extra_style blocks, so the extra wins at equal specificity)
    # now lives in _ordered_style_sources — the producer of the in-tree head
    # loop. Main first, then the extra block.
    ordered = MountExtraStyleComp._ordered_style_sources()
    ours = [(n, e) for (_c, n, e, _css) in ordered if n == "MountExtraStyleComp"]
    assert ("MountExtraStyleComp", None) in ours
    assert ("MountExtraStyleComp", "add") in ours
    assert ours.index(("MountExtraStyleComp", None)) < ours.index(
        ("MountExtraStyleComp", "add")
    )


# ── Page.stylesheets (override layer) ──────────────────────────────────────

def test_page_stylesheets_rendered_after_app_content():
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
    # The app mounts as a DIRECT <body> child (no #basis-ssr-root wrapper,
    # HYDRATION-WHOLEPAGE.md No.1); the user stylesheet must still land AFTER
    # the app's component content so it wins the cascade at equal specificity.
    # (Anchor on the app's rendered text — the root element also carries
    # hydration-marker attributes, so it is not a literal <div>hi</div>.)
    assert resp.text.index(">hi<") < resp.text.index("/static/app.css")


def test_page_stylesheets_default_empty():
    from basis.shared.page import Page

    assert Page.stylesheets == ()


# ── ThemeStore hydration + seed ────────────────────────────────────────────

def test_theme_store_serializes_dark_mode_seed():
    from basis.plugins.theme import ThemeStore

    t = ThemeStore("theme_serialize_test")
    t.dark_mode = True
    assert t.serialize().get("dark_mode") is True


def test_theme_store_snapshot_overrides_constructed_defaults(monkeypatch):
    from basis.plugins.theme import ThemeStore
    from basis.shared.store import install_initial_state

    install_initial_state({"theme_hydration_test": {"dark_mode": True}})
    t = ThemeStore("theme_hydration_test")
    assert t.dark_mode is True
