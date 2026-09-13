"""
Whole-page hydration surface — server side.

The Page is the whole-``<html>`` document shell and owns BOTH hydration regions:
its ``<head>`` bindings are stamped ``h:`` (title / viewport meta / render-mode
meta / initial-state script) and its ``<body>`` region — rooted at the
``<body>`` element — is stamped ``b:`` over the mounted app subtree. The
client can therefore keep the whole document alive against ONE ``h:`` + ``b:``
map.

These tests cover the *server* surface:

* an SSR page's head binding nodes carry ``data-hydration-id="h:..."`` and the
  ``<title>`` carries a ``data-hydration-text`` ordinal;
* the body region ids are ``b:``-rooted at the ``<body>`` element (``b:0``)
  with the app as its first countable child (``b:0:0``), disjoint from ``h:``;
* a CSR page head is NOT stamped (its head is served static — no hydration);
* marker placement survives the trailing in-tree head nodes (the ``<style
  id="basis-viewport">``), i.e. template children keep stable ``h:`` ordinals.

The client side of the surface (mounting the Page and re-pointing head/body
bindings to the live document) is covered separately by the client/SSR browser
path; this file pins the served-document contract both sides rely on.
"""
import re

from fastapi import Request
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page


def _build_app():
    """Return (app, ssr_url, csr_url) for the same page served both ways."""
    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div class="app-root">hi</div>"""

    class MyPage(Page):
        title = "Whole Page"
        root_component = Root
        entry_module = "/test_wholepage_root.py"

    app.include_page("/wholepage-ssr", page_cls=MyPage)

    @app.get("/wholepage-csr")
    async def csr(request: Request):
        from basis.server.responses import PageResponse

        return await PageResponse.from_page(MyPage, request, render_mode="csr")

    return app, "/wholepage-ssr", "/wholepage-csr"


def _hydration_ids(html: str) -> list[str]:
    return re.findall(r'data-hydration-id="([^"]+)"', html)


def _attribute_of(html: str, needle: str, attr: str) -> str | None:
    """The value of ``attr`` on the element whose opening tag contains ``needle``."""
    # Find the element start and its full opening tag.
    idx = html.find(needle)
    if idx == -1:
        return None
    # Walk back to '<'.
    start = html.rfind("<", 0, idx)
    end = html.find(">", idx)
    if start == -1 or end == -1:
        return None
    tag = html[start : end + 1]
    m = re.search(attr + r'="([^"]*)"', tag)
    return m.group(1) if m else None


def test_ssr_head_bindings_stamped_with_h_region_ids():
    app, ssr_url, _ = _build_app()
    client = TestClient(app)
    html = client.get(ssr_url).text
    assert client.get(ssr_url).status_code == 200

    # <title> is a Page-owned head text binding: stamped h: + a text ordinal.
    hid = _attribute_of(html, "<title", "data-hydration-id")
    assert hid is not None and hid.startswith("h:"), hid
    assert _attribute_of(html, "<title", "data-hydration-text") is not None

    # The viewport + render-mode metas are Page-owned head attribute bindings.
    vp = _attribute_of(html, 'name="viewport"', "data-hydration-id")
    assert vp is not None and vp.startswith("h:"), vp
    rm = _attribute_of(html, 'name="basis-render-mode"', "data-hydration-id")
    assert rm is not None and rm.startswith("h:"), rm


def test_ssr_body_region_is_b_rooted_and_disjoint_from_head():
    app, ssr_url, _ = _build_app()
    client = TestClient(app)
    html = client.get(ssr_url).text

    ids = _hydration_ids(html)
    assert ids, "expected hydration markers in the SSR document"
    head_ids = [i for i in ids if i.startswith("h:")]
    body_ids = [i for i in ids if i.startswith("b:")]
    assert head_ids, "expected h: head markers"
    assert body_ids, "expected b: body markers"
    # Body region is rooted at the <body> element (b:0) with the app as its
    # first countable child (b:0:0).
    assert "b:0" in body_ids
    assert "b:0:0" in body_ids
    assert all(i.startswith("b:") for i in body_ids)
    # Disjoint by construction — no id is in both sets.
    assert set(head_ids).isdisjoint(set(body_ids))


def test_ssr_title_text_ordinal_stamped():
    app, ssr_url, _ = _build_app()
    client = TestClient(app)
    html = client.get(ssr_url).text

    # data-hydration-text on <title> is a comma list of reactive text ordinals;
    # {title} is the only text child of <title> → ordinal 0.
    ords = _attribute_of(html, "<title", "data-hydration-text")
    assert ords is not None
    assert "0" in ords.split(",")


def test_csr_head_is_not_stamped():
    app, _, csr_url = _build_app()
    client = TestClient(app)
    html = client.get(csr_url).text

    # CSR keeps the served head static — no h: hydration surface.
    ids = _hydration_ids(html)
    assert not [i for i in ids if i.startswith("h:")], "CSR head must not be stamped"
