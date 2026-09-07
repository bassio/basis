"""
In-tree component chrome (HYDRATION-WHOLEPAGE.md §4.1 P3, additive step) —
server surface.

Pages render component stylesheets IN-TREE in the ``<head>`` (a keyed loop
over ``Page.component_style_items``) instead of ``mount_app`` injecting them
into the ``<body>``; the stylesheet body is bound via ``text-content`` (raw
text inside ``<style>`` is never binding-parsed) and survives intact. §4.1 P5
unified every boot path through a Page, so synthesized ``@app.page`` shells
render in-tree styles too — there is no legacy body injection left.

These tests pin:

* a real Page's SSR head carries per-component ``<style data-component-class>``
  (main + ``@extra_style`` blocks) with intact CSS, and its body has NONE;
* the ``<head>`` element itself is stamped ``h:0`` (so a head LoopBinding can
  re-point its parent);
* components defined under the client-only namespace (``basis.client.*``) are
  excluded from the in-tree items (server/client parity for the hydrated head);
* a synthesized ``@app.page`` shell renders the same in-tree head styles.
"""
import re

from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component, extra_style
from basis.shared.page import Page


class ChromeRoot(Component):
    """<div class="chrome-root-el">hi</div>"""

    def style(self):
        """chrome-root-el { color: rgb(1, 2, 3); }"""

    @extra_style
    def tweak(self):
        """chrome-root-el::after { content: 'x'; }"""


def _count(html: str, needle: str) -> int:
    return html.count(needle)


def test_real_page_renders_component_styles_in_head_not_body():
    app = Basis()
    app.bootstrap()

    class MyPage(Page):
        title = "Chrome"
        root_component = ChromeRoot
        entry_module = "/test_chrome_root.py"

    app.include_page("/chrome", page_cls=MyPage)
    html = TestClient(app).get("/chrome").text

    head = html.split("</head>", 1)[0]
    body = html.split("</head>", 1)[1]

    # Main stylesheet: present in <head>, intact, with data-component-class.
    main = re.search(
        r'<style data-component-class="ChromeRoot"[^>]*>(.*?)</style>', head, re.S
    )
    assert main is not None
    assert "rgb(1, 2, 3)" in main.group(1)
    # @extra_style block: its own <style> in <head>.
    extra = re.search(
        r'<style data-component-class="ChromeRoot" data-extra-style="tweak"[^>]*>'
        r"(.*?)</style>",
        head,
        re.S,
    )
    assert extra is not None
    assert "content: 'x'" in extra.group(1)
    # No component styles injected into the body.
    assert _count(body, "data-component-class") == 0
    # No binding-evaluation error leaked into the head styles.
    assert "[Error" not in head


def test_real_page_head_root_stamped_h0():
    app = Basis()
    app.bootstrap()

    class MyPage(Page):
        title = "Chrome"
        root_component = ChromeRoot
        entry_module = "/test_chrome_root.py"

    app.include_page("/chrome-h0", page_cls=MyPage)
    html = TestClient(app).get("/chrome-h0").text
    head = html.split("</head>", 1)[0]
    # The <head> element itself is the h: region root (so a head LoopBinding's
    # parent resolves during client re-point).
    assert re.search(r"<head[^>]*data-hydration-id=\"h:0\"", head) is not None


def test_server_enumeration_is_registry_complete():
    """Server-side ``component_style_items`` returns the full ordered set (the
    server DEFINES the page's chrome); client/server parity is enforced on the
    client by mirroring the served head, not by excluding namespaces here."""
    from basis.shared.page import _served_head_component_style_names

    class MyPage(Page):
        root_component = ChromeRoot
        entry_module = "/test_chrome_root.py"

    page = MyPage.load()
    names = [item["name"] for item in page.component_style_items()]

    assert "ChromeRoot" in names
    # On the server (no PyScript `document`) the served-head mirror is a no-op,
    # so enumeration is registry-complete — no namespace heuristic.
    assert _served_head_component_style_names() is None


def test_served_head_mirror_filters_client_enumeration():
    """The client renders exactly the component styles the served head lists, so
    a client-only registry extra (a dormant self-injecting component) is kept
    out of the head loop without any module-namespace exclusion."""
    from basis.shared.page import _filter_style_sources

    sources = [
        (object(), "Alpha", None, "a{}"),
        (object(), "Beta", None, "b{}"),
        (object(), "Gamma", "x", "c{}"),
    ]
    # Served head only shipped Alpha + Gamma's extra → client mirrors that.
    kept = _filter_style_sources(sources, {"Alpha", "Gamma"})
    assert [(s[1], s[2]) for s in kept] == [("Alpha", None), ("Gamma", "x")]
    # No served set (server) → no filtering.
    assert len(_filter_style_sources(sources, None)) == 3


def test_synthesized_page_renders_styles_in_tree_like_real_page():
    app = Basis()

    @app.page(path="/synth")
    class SynthChromeRoot(Component):
        """<div class="synth-el">hi</div>"""

        def style(self):
            """synth-el { color: rgb(9, 8, 7); }"""

    html = TestClient(app).get("/synth").text
    head = html.split("</head>", 1)[0]
    body = html.split("</head>", 1)[1]

    # §4.1 P5: synthesized @app.page shells are whole-document pages now — they
    # render component styles IN-TREE in their <head> (component_style_items)
    # exactly like a real Page; the legacy mount_app body injection is gone.
    assert _count(body, "data-component-class") == 0
    assert re.search(
        r'<style data-component-class="SynthChromeRoot"[^>]*>.*?rgb\(9, 8, 7\)',
        head,
        re.S,
    )
    # No binding-evaluation error leaked into the head styles.
    assert "[Error" not in head
