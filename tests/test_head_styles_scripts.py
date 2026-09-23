"""``$head.styles`` / ``$head.scripts`` — the head ``<style>``/``<script>`` channels.

Plugins and components contribute CSS bodies and scripts the page cannot author (a
request-dependent ``@font-face`` block, a script URL only the plugin knows); the base
template renders them through keyed head loops, so whole-page hydration keeps the loops
alive — the same mechanism ``$head.metas``/``$head.links`` ride through.

They differ from ``links`` in one way worth pinning: neither a style nor a script has an
identity of its own, so their dedup key is a digest of the content (see
``basis.shared.head._content_key``) — and that digest, not the content, is what the loop
stamps into the DOM.
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.head import HeadStore
from basis.shared.page import Page
from basis.shared.store import Store

#: The two bodies carry distinct needles so a test can point at one element.
FONT_CSS = "@font-face { font-family: 'Proof'; src: url(/proof.woff2); }"
PRINT_CSS = "@media print { a[href]::after { content: ' <' attr(href) '>'; } }"
INLINE_JS = "console.log('inline', 1 < 2 && 3 > 2);"


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


class HeadBodyContributor(Store):
    """Stands in for a plugin that owns head styles/scripts.

    ``apply_request`` is the per-request seam: ``Store._registry`` is cleared between
    requests, so anything contributed once at boot would not survive into a render.
    """

    def apply_request(self, request) -> None:
        head = Store._registry.get("head")
        if head is None:
            return
        head.add_style(FONT_CSS)
        head.add_style(FONT_CSS)  # the same body twice — one item
        head.add_style(PRINT_CSS, media="print")
        head.add_script("/plugin.js", type="module")
        head.add_script(code=INLINE_JS)


class NastyScriptContributor(Store):
    """A script whose own body carries a raw-text close sequence."""

    def apply_request(self, request) -> None:
        head = Store._registry.get("head")
        if head is not None:
            head.add_script(code='var x = "</script>";')


def _page(contributor: Store | None = None):
    app = Basis()
    app.bootstrap()
    if contributor is not None:
        app.include_store(contributor.get_store_name())

    class Root(Component):
        template = "<div>hi</div>"

    class DemoPage(Page):
        title = "demo"
        root_component = Root

    app.include_page("/demo", page_cls=DemoPage)
    return app


def _head_of(html: str) -> str:
    return html.split("</head>")[0]


def _initial_state_of(html: str) -> dict:
    return json.loads(
        html.split('id="basis-initial-state"')[1].split(">", 1)[1].split("</script>")[0]
    )


def _demo_page():
    """The fixture app with the standard head-body contributor."""
    return _page(HeadBodyContributor("head_body"))


def _element_of(head: str, needle: str) -> str:
    """The first head ``<style>``/``<script>`` element whose markup contains *needle*."""
    for match in re.finditer(r"<(style|script)\b[^>]*>.*?</\1>", head, re.S):
        if needle in match.group(0):
            return match.group(0)
    raise AssertionError(f"no head element carrying {needle!r}")


def test_a_contributed_style_renders_its_body_intact():
    app = _demo_page()
    head = _head_of(TestClient(app).get("/demo").text)

    # The body is CSS, not an escaped attribute value: an ``attr()`` selector and the
    # quotes around it survive serialization.
    assert _element_of(head, "@font-face").endswith(FONT_CSS + "</style>")
    assert PRINT_CSS in head
    assert "&lt;" not in head


def test_a_style_carries_its_media_and_omits_it_when_unset():
    app = _demo_page()
    head = _head_of(TestClient(app).get("/demo").text)

    assert 'media="print"' in _element_of(head, "@media print")
    # The font body declares no media: the loop's bindings are fixed, so an unset
    # attribute disappears rather than rendering a sentinel.
    assert "media" not in _element_of(head, "@font-face")
    assert "None" not in head


def test_the_same_body_contributed_twice_is_one_item():
    app = _demo_page()
    state = _initial_state_of(TestClient(app).get("/demo").text)

    assert [s["css"] for s in state["head"]["styles"]] == [FONT_CSS, PRINT_CSS]


def test_the_key_is_a_content_digest_not_the_body():
    """The key reaches the DOM as ``data-item-key``, so a large stylesheet must not
    repeat itself in an attribute."""
    app = _demo_page()
    html = TestClient(app).get("/demo").text
    head, state = _head_of(html), _initial_state_of(html)

    for item in state["head"]["styles"]:
        assert re.fullmatch(r"style:[0-9a-f]{12}", item["key"])
        assert item["css"] not in item["key"]
    assert f'data-item-key="{state["head"]["styles"][0]["key"]}"' in head


def test_an_external_script_carries_its_attributes_and_no_body():
    app = _demo_page()
    head = _head_of(TestClient(app).get("/demo").text)
    element = _element_of(head, "/plugin.js")

    assert 'src="/plugin.js"' in element
    assert 'type="module"' in element
    assert element.endswith("></script>")


def test_an_inline_script_renders_its_code_and_no_src():
    app = _demo_page()
    head = _head_of(TestClient(app).get("/demo").text)
    element = _element_of(head, "console.log")

    assert element.endswith(INLINE_JS + "</script>")
    assert "src=" not in element
    assert "type=" not in element


def test_a_script_body_cannot_close_its_own_element():
    """Raw-text content is emitted verbatim, so a ``</script>`` inside the code would
    end the element early and spill the rest of the code as markup."""
    app = _page(NastyScriptContributor("nasty"))
    element = _element_of(_head_of(TestClient(app).get("/demo").text), "var x")

    assert 'var x = "<\\/script>";' in element


def test_defer_and_async_are_presence_attributes():
    head = HeadStore("head")
    head.add_script("/a.js")
    head.add_script("/b.js", defer=True)
    head.add_script("/c.js", async_=True)

    plain, deferred, asynchronous = head.scripts_for()
    assert (plain["defer"], plain["async"]) == (None, None)
    assert (deferred["defer"], deferred["async"]) == ("", None)
    assert (asynchronous["defer"], asynchronous["async"]) == (None, "")


def test_a_script_needs_exactly_one_source():
    head = HeadStore("head")

    with pytest.raises(ValueError, match="exactly one of"):
        head.add_script("/a.js", code="var x = 1;")
    with pytest.raises(ValueError, match="exactly one of"):
        head.add_script()


def test_the_scripts_serialize_into_the_initial_state_in_the_loop_shape():
    app = _demo_page()
    state = _initial_state_of(TestClient(app).get("/demo").text)

    external, inline = state["head"]["scripts"]
    assert external == {
        "key": external["key"],
        "src": "/plugin.js",
        "code": None,
        "type": "module",
        "defer": None,
        "async": None,
    }
    assert re.fullmatch(r"script:[0-9a-f]{12}", external["key"])
    assert inline == {
        "key": inline["key"],
        "src": None,
        "code": INLINE_JS,
        "type": None,
        "defer": None,
        "async": None,
    }


def test_every_loop_item_carries_a_hydration_id():
    app = _demo_page()
    head = _head_of(TestClient(app).get("/demo").text)

    for needle in ("@font-face", "/plugin.js", "console.log"):
        assert "data-hydration-id" in _element_of(head, needle)


def test_a_disposer_takes_the_contribution_back():
    head = HeadStore("head")
    dispose_style = head.add_style(FONT_CSS)
    dispose_script = head.add_script("/plugin.js")

    dispose_style()
    dispose_script()

    assert head.styles_for() == []
    assert head.scripts_for() == []


def test_no_contributor_renders_no_style_or_script_item():
    app = _page()
    html = TestClient(app).get("/demo").text
    head, state = _head_of(html), _initial_state_of(html)

    assert 'data-item-key="style:' not in head
    assert 'data-item-key="script:' not in head
    assert state["head"]["styles"] == []
    assert state["head"]["scripts"] == []
    # The channels are independent: the theme's theme-color is still there.
    assert [m["name"] for m in state["head"]["metas"]] == ["theme-color"]
