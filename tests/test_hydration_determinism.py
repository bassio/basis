"""
Deterministic hydration — canonical world tests.

These prove the canonical hydration world (preserved-text tree +
``basis/shared/hydration.py``) produces deterministic element paths and text
ordinals, keeps text/whitespace/comments intact, and that the client stamps
the SAME canonical paths (there is no second client walker — one address
scheme, ``data-hydration-id``).  Canonical is the only hydration mode (the
legacy mode has been removed).
"""
import pytest

from basis.server.tree_builder import html_to_element
from basis.shared.element import Element, ElementString, Comment
from basis.shared.hydration import (
    HYDRATION_ID_ATTR,
    HYDRATION_MISMATCH_EVENT,
    HYDRATION_REPORT_GLOBAL,
    HydrationReport,
    apply_hydration_markers,
    build_hydration_map,
    hydration_fallback_enabled,
    is_element,
    is_text,
    iter_tree_paths,
    node_text,
    set_hydration_fallback,
    stamp_text_ordinals,
    text_ordinal,
)


@pytest.fixture(autouse=True)
def _deterministic_hydration_mode():
    """Keep every test deterministic: disable the fallback override so it can
    never leak across tests."""
    set_hydration_fallback(False)
    yield
    set_hydration_fallback(None)


# ---------------------------------------------------------------------------
# Phase E — diagnostics report (shared shape)
# ---------------------------------------------------------------------------

def test_hydration_report_starts_clean():
    report = HydrationReport()
    assert report.is_clean is True
    assert report.mode == "canonical"
    assert report.to_dict() == {
        "mode": "canonical",
        "unhydrated_components": [],
        "unmatched_bindings": [],
        "fallback": None,
    }


def test_hydration_report_accumulates_and_serializes():
    report = HydrationReport()
    report.add_unhydrated_component("StatusBar", client_id="r:0:3", reason="x")
    report.add_unmatched_binding(
        "Root", "TextBinding", client_id="r:0:0", reason="text node not matched"
    )
    report.set_fallback("whole-app client re-render")

    assert report.is_clean is False
    data = report.to_dict()
    assert data["unhydrated_components"] == [
        {"tag": "StatusBar", "client_id": "r:0:3", "reason": "x"}
    ]
    assert data["unmatched_bindings"][0]["binding_type"] == "TextBinding"
    assert data["fallback"] == "whole-app client re-render"


def test_hydration_report_mode_defaults_to_canonical():
    assert HydrationReport().mode == "canonical"
    assert HydrationReport(mode="custom").mode == "custom"


def test_hydration_fallback_toggle():
    assert hydration_fallback_enabled() is False  # fixture disables it
    set_hydration_fallback(True)
    assert hydration_fallback_enabled() is True
    set_hydration_fallback(False)
    assert hydration_fallback_enabled() is False


def test_hydration_fallback_defaults_on_when_unset(monkeypatch):
    monkeypatch.delenv("BASIS_HYDRATION_FALLBACK", raising=False)
    set_hydration_fallback(None)
    assert hydration_fallback_enabled() is True


def test_hydration_fallback_can_opt_out(monkeypatch):
    monkeypatch.setenv("BASIS_HYDRATION_FALLBACK", "0")
    set_hydration_fallback(None)
    assert hydration_fallback_enabled() is False


def test_diagnostics_constants():
    assert HYDRATION_MISMATCH_EVENT == "basis-hydration-mismatch"
    assert HYDRATION_REPORT_GLOBAL == "__basisHydrationReport"


# --- Fallback re-render (moves the detached shadow mount into the live DOM)

class _FakeDomNode:
    """Minimal DOM stand-in supporting appendChild/replaceChildren with
    browser-like move semantics (appendChild detaches from the old parent)."""

    def __init__(self):
        self.childNodes = []
        self._parent = None

    def appendChild(self, child):
        if child._parent is not None:
            child._parent.childNodes.remove(child)
        child._parent = self
        self.childNodes.append(child)

    def replaceChildren(self, *children):
        for c in list(self.childNodes):
            c._parent = None
        self.childNodes.clear()
        for c in children:
            self.appendChild(c)


def test_fallback_rerender_moves_all_shadow_children():
    """The fallback must move EVERY shadow child (scoped <style> + app root)
    into the live SSR root, preserving styling."""
    from basis.client.component import _fallback_rerender

    ssr_root = _FakeDomNode()
    style = _FakeDomNode()
    app = _FakeDomNode()
    shadow = _FakeDomNode()
    shadow.appendChild(style)
    shadow.appendChild(app)

    report = HydrationReport()
    _fallback_rerender(ssr_root, shadow, report)

    assert report.fallback == "whole-app client re-render"
    assert ssr_root.childNodes == [style, app]
    assert shadow.childNodes == []


def test_fallback_rerender_noop_when_shadow_empty():
    from basis.client.component import _fallback_rerender

    report = HydrationReport()
    _fallback_rerender(_FakeDomNode(), _FakeDomNode(), report)
    assert report.fallback is None


def test_fallback_rerender_reports_failure():
    from basis.client.component import _fallback_rerender

    class _BrokenRoot:
        def replaceChildren(self, *children):
            raise RuntimeError("boom")

    shadow = _FakeDomNode()
    shadow.appendChild(_FakeDomNode())
    report = HydrationReport()
    _fallback_rerender(_BrokenRoot(), shadow, report)
    assert "fallback re-render failed" in (report.fallback or "")


def test_fallback_rerender_restores_shadow_bindings():
    """After the fallback moves the shadow mount into the live root, every
    component binding must be re-pointed at the shadow node it was created
    against. initialize_ssr repoints bindings at SSR nodes; when those SSR
    nodes are discarded the moved app would otherwise be left bound to
    detached nodes (dead events / dead reactivity)."""
    from basis.client.component import _fallback_rerender

    ssr_root = _FakeDomNode()
    style = _FakeDomNode()
    shadow = _FakeDomNode()
    shadow.appendChild(style)

    # A binding whose node was repointed to a detached SSR node.
    class _FakeBinding:
        def __init__(self, node):
            self.node = node
            self.anchor = None
            self.parent = None

    shadow_node = _FakeDomNode()
    detached_ssr_node = _FakeDomNode()

    class _FakeInstance:
        def __init__(self):
            self._element = None

        def set_selfbinding(self, node):
            self._element = node

    instance = _FakeInstance()
    binding = _FakeBinding(detached_ssr_node)  # repointed by initialize_ssr

    snapshot = [
        (instance, shadow_node, [(binding, shadow_node, None, None)]),
    ]

    report = HydrationReport()
    _fallback_rerender(ssr_root, shadow, report, snapshot=snapshot)

    assert report.fallback == "whole-app client re-render"
    assert instance._element is shadow_node
    assert binding.node is shadow_node


def describe(node):
    """Human-readable identity of a node for golden assertions."""
    if is_element(node):
        return ("tag", node.tag)
    if is_text(node):
        return ("#text", node_text(node))
    return ("#comment", node_text(node))


def tree_map(root):
    """{path: describe(node)} for every countable node (canonical policy)."""
    return {path: describe(node) for node, path in iter_tree_paths(root)}


def element_paths(root):
    """Set of paths for countable ELEMENT nodes (canonical policy)."""
    return {path for node, path in iter_tree_paths(root) if is_element(node)}


def find_text_nodes(root, contains=None):
    """All ElementString descendants in DOCUMENT ORDER, optionally filtered by
    substring."""
    out = []

    def walk(node):
        for c in getattr(node, "children", []):
            if isinstance(c, ElementString):
                if contains is None or contains in c.value:
                    out.append(c)
            elif isinstance(c, Element):
                walk(c)
            # comments are not text; ignore

    walk(root)
    return out


# ---------------------------------------------------------------------------
# Phase A — tree-builder text handling
# ---------------------------------------------------------------------------

TEMPLATES = {
    "flat": "<div><span>Score: {score}</span></div>",
    "indented": "<div>\n    <span>{a}</span>\n    <span>{b}</span>\n</div>",
    "inline_comment": "<p>Hello <b>{name}</b>!<!-- note -->Bye</p>",
    "nested": "<section><h2>Hi</h2><p>{body}</p></section>",
}


def test_tree_builder_preserves_text_content():
    root = html_to_element("<span>Best: <b>{best}</b></span>")
    assert root.__html__() == "<span>Best: <b>{best}</b></span>"


def test_tree_builder_keeps_whitespace_only_text_nodes():
    root = html_to_element("<div>\n    <span></span>\n</div>")
    texts = [c.value for c in find_text_nodes(root)]
    assert texts == ["\n    ", "\n"]


def test_tree_builder_merges_text_runs_across_entities():
    # HTMLParser delivers entity-decoded text; it must end up as ONE text node.
    root = html_to_element("<p>a &amp; b</p>")
    texts = [c.value for c in find_text_nodes(root)]
    assert texts == ["a & b"]


def test_tree_builder_does_not_merge_across_tags():
    root = html_to_element("<p>a <b>x</b> b</p>")
    texts = [c.value for c in find_text_nodes(root)]
    assert texts == ["a ", "x", " b"]


# ---------------------------------------------------------------------------
# Phase B — canonical golden paths
# ---------------------------------------------------------------------------

GOLDEN = {
    "flat": {
        "r:0": ("tag", "div"),
        "r:0:0": ("tag", "span"),
        "r:0:0:0": ("#text", "Score: {score}"),
    },
    "indented": {
        "r:0": ("tag", "div"),
        "r:0:0": ("tag", "span"),
        "r:0:0:0": ("#text", "{a}"),
        "r:0:1": ("tag", "span"),
        "r:0:1:0": ("#text", "{b}"),
    },
    "inline_comment": {
        "r:0": ("tag", "p"),
        "r:0:0": ("#text", "Hello "),
        "r:0:1": ("tag", "b"),
        "r:0:1:0": ("#text", "{name}"),
        "r:0:2": ("#text", "!"),
        "r:0:3": ("#text", "Bye"),
    },
    "nested": {
        "r:0": ("tag", "section"),
        "r:0:0": ("tag", "h2"),
        "r:0:0:0": ("#text", "Hi"),
        "r:0:1": ("tag", "p"),
        "r:0:1:0": ("#text", "{body}"),
    },
}


@pytest.mark.parametrize("name", list(GOLDEN))
def test_golden_paths_in_new_world(name):
    root = html_to_element(TEMPLATES[name])
    assert tree_map(root) == GOLDEN[name]


# ---------------------------------------------------------------------------
# Item 7 — client stamping IS the canonical algorithm (no second walker)
# ---------------------------------------------------------------------------

def test_client_stamping_uses_canonical_paths():
    """The client template node at canonical path P hydrates the SSR node at
    canonical path P.  Stamping the client tree with iter_tree_paths (what
    client/component.py._stamp_hydration_ids does) must put the SAME
    data-hydration-id on every element as the server would, and every
    SSR-marked (binding/component) target must be addressable at that path."""
    for name in TEMPLATES:
        root = html_to_element(TEMPLATES[name])
        # Mirror _stamp_hydration_ids: stamp every countable element.
        for node, path in iter_tree_paths(root):
            if is_element(node):
                node.setAttribute(HYDRATION_ID_ATTR, path)
        stamped = {
            path for node, path in iter_tree_paths(root)
            if is_element(node)
            and node.getAttribute(HYDRATION_ID_ATTR) == path
        }
        # Every countable element carries exactly its canonical path.
        assert stamped == element_paths(root), name
        # Every SSR hydration marker (binding/component target) is a subset of
        # the client-stamped element paths — one address space.
        markers = apply_hydration_markers(
            root, binding_nodes=[root], component_nodes=[root]
        )
        assert set(markers) <= element_paths(root), name


def test_canonical_paths_are_whitespace_stable():
    """Adding/removing surrounding whitespace must not move sibling IDs."""
    base = html_to_element("<div><span>{a}</span><span>{b}</span></div>")
    padded = html_to_element(
        "<div>\n    <span>{a}</span>\n    <span>{b}</span>\n</div>"
    )
    assert element_paths(base) == {"r:0", "r:0:0", "r:0:1"}
    assert element_paths(padded) == {"r:0", "r:0:0", "r:0:1"}


# ---------------------------------------------------------------------------
# Phase B — deterministic text ordinals
# ---------------------------------------------------------------------------

TEXT_ORDINAL_TEMPLATE = (
    "<div>\n    {a}\n    <b>{b}</b>\n    {c}\n    <span></span>\n</div>"
)


def test_text_ordinal_ignores_whitespace_and_comments():
    root = html_to_element(TEXT_ORDINAL_TEMPLATE)
    div = root
    # Canonical text runs are coalesced: '{a}' lives inside '\n    {a}\n    '.
    text_a = find_text_nodes(div, "{a}")[0]
    text_b = find_text_nodes(div, "{b}")[0]
    text_c = find_text_nodes(div, "{c}")[0]
    b = next(c for c in div.children if isinstance(c, Element))

    # Whitespace around the bindings must not shift the ordinals.  Note the
    # <b> element is countable too, so the second text node is ordinal 2.
    assert text_ordinal(div, text_a) == 0
    assert text_ordinal(div, text_c) == 2
    # Inside <b>, its own text is ordinal 0.
    assert text_ordinal(b, text_b) == 0
    # A whitespace-only node is skipped when counting OTHER nodes (so text_a=0,
    # text_c=2 above), but when queried directly it is treated as the reactive
    # target and counted — that is what locates empty-valued bindings, whose
    # template text is non-empty but whose rendered value is whitespace.
    ws = next(
        c for c in div.children if isinstance(c, ElementString) and not c.value.strip()
    )
    assert text_ordinal(div, ws) == 4


def test_stamp_text_ordinals_is_deterministic():
    root = html_to_element(TEXT_ORDINAL_TEMPLATE)
    text_a = find_text_nodes(root, "{a}")[0]
    text_c = find_text_nodes(root, "{c}")[0]

    stamp_text_ordinals(root, [text_a, text_c])

    assert root.getAttribute("data-basis-text") == "0,2"
    # The ordinals are stable no matter how the template is indented.
    padded = html_to_element(
        "<div>\n\n    {a}\n\n    <b>{b}</b>\n\n    {c}\n</div>"
    )
    assert padded.getAttribute("data-basis-text") is None
    stamp_text_ordinals(padded, [find_text_nodes(padded, "{a}")[0],
                                 find_text_nodes(padded, "{c}")[0]])
    assert padded.getAttribute("data-basis-text") == "0,2"


# ---------------------------------------------------------------------------
# Phase B — set-based marker stamping
# ---------------------------------------------------------------------------

def test_apply_hydration_markers_stamps_bindings_and_components():
    root = html_to_element(TEMPLATES["indented"])
    spans = [c for c in root.children if isinstance(c, Element)]

    # Every component root carries a SelfBinding, so it is in BOTH sets.
    report = apply_hydration_markers(
        root, binding_nodes=[root, *spans], component_nodes=[root]
    )

    assert root.getAttribute("data-component-hydration-id") == "r:0"
    assert root.getAttribute("data-hydration-id") == "r:0"
    assert spans[0].getAttribute("data-hydration-id") == "r:0:0"
    assert spans[1].getAttribute("data-hydration-id") == "r:0:1"
    assert report == {
        "r:0": {"binding": True, "component": True},
        "r:0:0": {"binding": True, "component": False},
        "r:0:1": {"binding": True, "component": False},
    }


def test_build_hydration_map_keys_by_stamped_path():
    """The SSR path->node map indexes the same canonical paths the server
    stamped — the client matches bindings against this single map instead of
    scanning with querySelector per binding."""
    root = html_to_element(TEMPLATES["indented"])
    spans = [c for c in root.children if isinstance(c, Element)]
    apply_hydration_markers(
        root, binding_nodes=[root, *spans], component_nodes=[root]
    )

    ssr_map = build_hydration_map(root)
    assert set(ssr_map.keys()) == {"r:0", "r:0:0", "r:0:1"}
    assert ssr_map["r:0"] is root
    assert ssr_map["r:0:0"] is spans[0]
    assert ssr_map["r:0:1"] is spans[1]


def test_build_hydration_map_ignores_unmarked_nodes():
    """Nodes without data-hydration-id are not in the map."""
    root = html_to_element("<div><span>a</span><span>b</span></div>")
    assert build_hydration_map(root) == {}


# ---------------------------------------------------------------------------
# Phase C/D — wiring: canonical SSR markers, client ordinal matching
# ---------------------------------------------------------------------------

def test_ssr_emits_markers_and_text_ordinals():
    """Full SSR render must emit hydration markers AND the deterministic
    ``data-basis-text`` ordinal, with text preserved."""
    from fastapi.testclient import TestClient
    from basis.server.app import Basis, _synthesize_page
    from basis.shared.component import Component

    app = Basis()
    app.bootstrap()

    class Root(Component):
        # A defined field: the text binding succeeds, so the canonical tree's
        # authored whitespace around the binding is preserved in the SSR output.
        # (With `message` undefined the error sink renders the field as an
        # empty value and the whole text run aborts to "" — an error condition
        # where whitespace legitimately disappears.)  Note: the docstring MUST
        # be the first class statement for Python to bind it as __doc__.
        """
        <div>
            <span>Ready</span>
            {message}
        </div>
        """

        message = "Hello"

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    # Root is both a SelfBinding node and a component root.
    assert 'data-hydration-id="r:0"' in resp.text
    assert 'data-component-hydration-id="r:0"' in resp.text
    # Deterministic text ordinal: {message} is normalized-child #1 of the div
    # (the <span> is #0), so the parent carries data-basis-text="1".
    assert 'data-basis-text="1"' in resp.text
    # Canonical tree preserves the authored whitespace between the elements
    # (the successful binding renders "Hello" inside that preserved run).
    assert "<span>Ready</span>\n    " in resp.text
    assert "Hello" in resp.text


def test_ssr_stamps_loop_body_nodes_and_text_ordinals():
    """A plain loop's body nodes carry data-hydration-id AND data-basis-text in
    the SSR output, so the client's hydration pass (via ``all_body_bindings()``)
    can match and re-point them — making plain loop bodies reactive on /ssr."""
    from fastapi.testclient import TestClient
    from basis.server.app import Basis, _synthesize_page
    from basis.shared.component import Component

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <div>
            <div for="it" in="{items}" key="k">{it['name']}</div>
        </div>
        """

        items = [{"k": 1, "name": "Alpha"}, {"k": 2, "name": "Beta"}]

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_loop_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    # Loop item wrappers are stamped with canonical hydration ids.
    assert 'data-hydration-id="r:0:0"' in resp.text
    assert 'data-hydration-id="r:0:1"' in resp.text
    # Each item body parent carries the text ordinal for its {it['name']} node.
    assert 'data-basis-text="0"' in resp.text
    assert "Alpha" in resp.text and "Beta" in resp.text


def test_ssr_stamps_nested_loop_body_nodes_and_text_ordinals():
    """Phase 5-extension (server side): a NESTED loop's INNER item wrappers and
    body nodes carry data-hydration-id AND data-basis-text in the SSR output
    (the recursion in ``marked_for_hydration`` / ``text_binding_nodes``), so
    the client's structural matcher can re-point inner loop bodies on /ssr."""
    from fastapi.testclient import TestClient
    from basis.server.app import Basis, _synthesize_page
    from basis.shared.component import Component

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """
        <div>
            <div for="grp" in="{groups}" key="g">
                <span>{grp['g']}:</span>
                <div for="it" in="{grp['items']}" key="name">{it['name']}</div>
            </div>
        </div>
        """

        groups = [{"g": "A", "items": [{"name": "a1"}, {"name": "a2"}]},
                  {"g": "B", "items": [{"name": "b1"}]}]

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_nested_loop_root.py"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200

    # Outer item wrappers.
    assert 'data-hydration-id="r:0:0"' in resp.text   # outer A
    assert 'data-hydration-id="r:0:1"' in resp.text   # outer B
    # Inner item wrappers (children of outer A: span at :0, items a1/a2 at :1/:2;
    # outer B's single inner item at r:0:1:1).
    assert 'data-hydration-id="r:0:0:1"' in resp.text  # inner a1
    assert 'data-hydration-id="r:0:0:2"' in resp.text  # inner a2
    assert 'data-hydration-id="r:0:1:1"' in resp.text  # inner b1
    # Inner bodies + span labels carry text ordinals for their reactive text.
    assert resp.text.count('data-basis-text="0"') >= 5
    # Everything renders.
    for needle in ("A:", "B:", "a1", "a2", "b1"):
        assert needle in resp.text


# --- Browser-DOM stand-in: verifies hydration.py duck-typing as the client
# --- uses it (nodeType/textContent/childNodes), so the ordinal matching works
# --- identically in Pyodide.

class _FakeNode:
    def __init__(self, node_type, text=None):
        self.nodeType = node_type          # 1 element / 3 text / 8 comment
        self._text = text
        self.childNodes = []
        self.parentNode = None
        self._attrs = {}

    @property
    def data(self):
        return self._text

    @property
    def textContent(self):
        return self._text

    def appendChild(self, child):
        child.parentNode = self
        self.childNodes.append(child)

    def getAttribute(self, name):
        return self._attrs.get(name)

    def setAttribute(self, name, value):
        self._attrs[name] = value


def _fake_element(tag):
    return _FakeNode(1, text=None)


def _fake_text(value):
    return _FakeNode(3, text=value)


def test_client_text_ordinal_matching_on_dom_like_nodes():
    """The client-side canonical branch (Phase D) must resolve the SSR text
    node by ordinal, computed over normalized children, exactly as it will run
    on browser DOM nodes in Pyodide."""
    from basis.shared.hydration import normalized_children

    # Client shadow tree for <div>\n    {a}\n    <b>{b}</b>\n    {c}\n</div>
    div = _fake_element("div")
    div.appendChild(_fake_text("\n    {a}\n    "))
    b = _fake_element("b")
    div.appendChild(b)
    b.appendChild(_fake_text("{b}"))
    div.appendChild(_fake_text("\n    {c}\n"))
    texts = [c for c in div.childNodes if c.nodeType == 3]

    # Ordinals ignore the surrounding whitespace; <b> is countable (#1).
    assert text_ordinal(div, texts[0]) == 0
    assert text_ordinal(div, texts[1]) == 2
    assert text_ordinal(b, b.childNodes[0]) == 0

    # SSR tree (same structure) with the canonical data-basis-text marker.
    ssr_div = _fake_element("div")
    ssr_div.appendChild(_fake_text("\n    {a}\n    "))
    ssr_b = _fake_element("b")
    ssr_div.appendChild(ssr_b)
    ssr_b.appendChild(_fake_text("{b}"))
    ssr_div.appendChild(_fake_text("\n    {c}\n"))
    ssr_div.setAttribute("data-basis-text", "0,2")

    # Reproduce the client branch in initialize_ssr for the {c} text binding.
    own = text_ordinal(div, texts[1])
    target = None
    for i, child in enumerate(normalized_children(ssr_div)):
        if i == own:
            target = child
            break
    assert target is ssr_div.childNodes[2]
    assert target.data == "\n    {c}\n"
