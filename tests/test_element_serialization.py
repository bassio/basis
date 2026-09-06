"""HTML serialization escaping for the server element model.

The element model stores text raw (mirroring the browser's ``textContent``) and
escapes ONLY at HTML serialization time (``__html__``). This guards the SSR
output against a ``TextBinding`` value that contains markup (e.g. a code sample
``"<b>hi</b>"``) being written raw and re-parsed as elements by the browser —
the bug the basis-website code-example demo hit.
"""
from basis.shared.element import Comment, Element, ElementString, element_fn


def test_text_node_html_is_escaped_but_str_stays_raw():
    t = ElementString(value='<b>hi</b> & "quote"')
    # Raw in the model (DOM / Python semantics).
    assert t.textContent == '<b>hi</b> & "quote"'
    assert str(t) == '<b>hi</b> & "quote"'
    # Escaped only when serialized to HTML. Quotes are left raw in TEXT (they
    # are only special inside attribute values), so only & < > are escaped.
    assert t.__html__() == '&lt;b&gt;hi&lt;/b&gt; &amp; "quote"'


def test_plain_text_is_unchanged():
    """Safe text must NOT be over-escaped (round-trips byte-identically)."""
    t = ElementString(value="Hello, world! 123")
    assert t.__html__() == "Hello, world! 123"


def test_element_renders_escaped_text_children():
    el = element_fn("div", ElementString("before <em>mid</em> after"))
    assert el.outerHTML == "<div>before &lt;em&gt;mid&lt;/em&gt; after</div>"


def test_element_renders_escaped_attribute_values():
    el = Element(tag="div", attrs={"title": 'a "quoted" & <tag> value'}, children=[])
    out = el.__html__()
    assert 'title="a &quot;quoted&quot; &amp; &lt;tag&gt; value"' in out


def test_comment_markup_is_not_escaped():
    c = Comment(data=" note -- here ")
    assert c.__html__() == "<!-- note -- here -->"


def test_ssr_text_binding_with_markup_round_trips_as_text():
    """The website scenario end-to-end: a field whose value contains markup must
    serialize ESCAPED in the SSR HTML (no raw element), and re-parsing that HTML
    must recover the original raw text with no nested element (browser-parse
    equivalence — hydration matches on the parsed DOM, so this is safe)."""
    import re

    from fastapi.testclient import TestClient

    from basis.server.app import Basis
    from basis.server.tree_builder import html_to_element
    from basis.shared.page import _synthesize_page
    from basis.shared.component import Component

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <pre><code>{source}</code></pre>
        """

        source = 'class Counter(Component):\n    """<button onclick="{increment}">Count: {count}</button>"""'

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_code_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    # SSR must contain the ESCAPED form — never a raw <button> element.
    assert "&lt;button" in resp.text
    assert "<button" not in resp.text

    # Browser-parse equivalence: parse the serialized <code> content and check
    # it is a single text node whose value equals the original source.
    m = re.search(r"<code[^>]*>(.*?)</code>", resp.text, re.S)
    assert m is not None, "code element not found in SSR output"
    wrapper = html_to_element(f"<wrapper>{m.group(1)}</wrapper>")
    assert wrapper.tagName == "wrapper"
    # Exactly one child, a text node (ElementString), with the raw value.
    children = wrapper.childNodes
    assert len(children) == 1
    child = children[0]
    assert not isinstance(child, Element)
    assert child.get_value() == Root.source


# ── raw-text elements (script / style) ─────────────────────────────────────
# Per the HTML spec these are raw-text elements: content is literal raw text
# (no character references, no tags), so text must be emitted verbatim — NOT
# html.escape'd — guarding only the closing-tag sequence.

def test_script_text_is_serialized_raw_not_escaped():
    el = element_fn("script", ElementString('const s = "a & b < c";'))
    assert el.outerHTML == '<script>const s = "a & b < c";</script>'


def test_style_text_is_serialized_raw_not_escaped():
    el = element_fn("style", ElementString('.x::after { content: "a & b"; }'))
    assert el.outerHTML == '<style>.x::after { content: "a & b"; }</style>'


def test_script_closing_sequence_is_neutralized():
    """A literal ``</script>`` inside script content must not close the element:
    it becomes ``<\\/script>`` (not a raw-text close in HTML; ``\\/`` is valid
    inside JS string content)."""
    el = element_fn("script", ElementString('const x = "</script>";'))
    out = el.outerHTML
    assert out == '<script>const x = "<\\/script>";</script>'
    # Only the element's own closing tag remains (the inner one is neutralized).
    assert out.count("</script>") == 1


def test_style_closing_sequence_is_neutralized_case_insensitive():
    """The raw-text end-tag match is case-insensitive (per the HTML parser)."""
    el = element_fn("style", ElementString("a { x: 1 } </STYLE>"))
    out = el.outerHTML
    assert out == "<style>a { x: 1 } <\\/STYLE></style>"
    assert "</STYLE>" not in out


def test_pre_is_still_escaped():
    """``<pre>`` is a NORMAL (markup) element — its text must remain escaped."""
    el = element_fn("pre", ElementString("a < b & c"))
    assert el.outerHTML == "<pre>a &lt; b &amp; c</pre>"


def test_script_raw_text_round_trips_through_html_parse():
    """Browser-parse equivalence: parsing a raw-text ``<script>`` recovers the
    raw text exactly (the HTML parser reads raw-text content literally)."""
    from basis.server.tree_builder import html_to_element

    raw = 'const s = "a & b"; // 1 < 2 stays text when re-parsed\n'
    el = element_fn("script", ElementString(raw))
    parsed = html_to_element(el.outerHTML)
    assert parsed.tagName == "script"
    children = parsed.childNodes
    assert len(children) == 1
    assert isinstance(children[0], ElementString)
    assert children[0].get_value() == raw
