"""
Declarative root app — server surface.

A ``Page`` mounts its ``root_component`` as a NESTED ``ChildBinding`` under a
hyphenated host tag in its ``<body>`` app slot — "the root is just another
component" — not by the engine imperatively mounting it at the
``basis:app-root`` comment.

These tests pin:

* the served body contains the root under its hyphen tag as the first countable
  body child (``b:0:0``), with NO ``basis:app-root`` comment marker;
* the root's own template content lives INSIDE the host;
* real-Page styles still ship in-tree in the ``<head>`` (nothing body-injected);
* a root WITHOUT a declared hyphen tag mounts under a kebab-derived host tag
  (``display: contents`` so it adds no box) — every boot path is declarative.
"""
import re

from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page


class DeclRoot(Component):
    __tag__ = "decl-root"

    def style(self):
        """decl-el { color: rgb(11, 22, 33); }"""

    def template(self):
        """<div class="decl-el">hi from decl root</div>"""


def test_hyphen_tagged_root_mounts_declaratively_under_its_tag():
    app = Basis()
    app.bootstrap()

    class MyPage(Page):
        title = "Decl"
        root_component = DeclRoot
        entry_module = "/test_decl_root.py"

    app.include_page("/decl", page_cls=MyPage)
    html = TestClient(app).get("/decl").text
    head = html.split("</head>", 1)[0]
    body = html.split("</head>", 1)[1]

    # No app-root comment marker survives (server strips comment whitespace:
    # the parsed comment is ``basis:app-root``, serialized ``<!--basis:app-root-->``).
    assert "<!--basis:app-root-->" not in html
    # The root sits under its hyphen tag as the body's first countable child.
    m = re.search(r"<decl-root[^>]*data-hydration-id=\"b:0:0\"[^>]*>", body)
    assert m is not None, body[:1200]
    # The root's own template content lives INSIDE the host (as a stamped
    # component child of the host).
    assert '<div class="decl-el"' in body
    host_span = body[m.start():]
    assert host_span.index('<div class="decl-el"') < host_span.index("</decl-root>")
    # Real-Page styles stay in-tree in the <head> — nothing body-injected.
    assert re.search(r'<style data-component-class="DeclRoot"', head) is not None
    assert re.search(r'data-component-class="DeclRoot"', body) is None


def test_non_hyphen_tagged_root_mounts_under_derived_tag():
    app = Basis()
    app.bootstrap()

    class PlainRoot(Component):
        def template(self):
            """<div class="plain-el">legacy root</div>"""

    class MyPage(Page):
        title = "Plain"
        root_component = PlainRoot
        entry_module = "/test_plain_root.py"

    app.include_page("/plain", page_cls=MyPage)
    html = TestClient(app).get("/plain").text

    # A root that does NOT declare a hyphenated __tag__ still mounts
    # declaratively — the framework derives a kebab-case host tag from the class
    # name (PlainRoot → plain-root) and gives it `display: contents` so it adds
    # no box. No app-root comment marker survives.
    assert "<!--basis:app-root-->" not in html
    m = re.search(
        r'<plain-root[^>]*style="display: contents"[^>]*data-hydration-id="b:0:0"[^>]*>',
        html,
    )
    assert m is not None, html[:1200]
    # The root's own template content lives INSIDE the derived host, stamped as
    # a component child of it (b:0:0:0).
    assert (
        re.search(
            r'<div[^>]*class="plain-el"[^>]*data-hydration-id="b:0:0:0"[^>]*>',
            html,
        )
        is not None
    )
    host_span = html[m.start():]
    assert host_span.index('<div class="plain-el"') < host_span.index("</plain-root>")


def test_static_page_no_root_has_no_app():
    app = Basis()
    app.bootstrap()

    class StaticPage(Page):
        title = "Static"
        root_component = None

    app.include_page("/static-decl", page_cls=StaticPage)
    html = TestClient(app).get("/static-decl").text
    body = html.split("</head>", 1)[1]
    # No declarative (or imperative) root mount for a static page; the inert
    # app-root slot marker stays in the base body template (legacy, no host).
    assert "decl-root" not in body
    assert "<!--basis:app-root-->" in body
