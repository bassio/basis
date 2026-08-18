"""
Void elements (e.g. ``<input>``, ``<img>``) have no end tag, so the server
tree builder must finalize them inside ``handle_starttag`` — otherwise the
void element stays as ``current_element`` and the parent's end tag never
matches, producing a ``None`` blueprint.  That broke SSR of any component
whose template contains a void element (e.g. ``ui/input``).
"""

from basis.server.tree_builder import html_to_element, html_to_element_tree
from basis.shared.element import Element, ElementString


def test_void_element_inside_div_builds_tree():
    root = html_to_element("<div><input></div>")
    assert isinstance(root, Element)
    assert root.tag == "div"
    assert len(root.children) == 1
    assert isinstance(root.children[0], Element)
    assert root.children[0].tag == "input"


def test_bare_void_element_builds_tree():
    root = html_to_element("<input>")
    assert isinstance(root, Element)
    assert root.tag == "input"


def test_void_element_with_attrs_preserved():
    root = html_to_element('<img src="x.png">')
    assert isinstance(root, Element)
    assert root.tag == "img"
    assert root.getAttribute("src") == "x.png"


def test_sibling_void_elements_and_text_order():
    root = html_to_element("<div>a<input><img></div>")
    assert root.tag == "div"
    assert [type(c).__name__ for c in root.children] == [
        "ElementString", "Element", "Element",
    ]
    assert root.children[0].value == "a"
    assert root.children[1].tag == "input"
    assert root.children[2].tag == "img"


def test_void_element_inside_nested_nonvoid():
    root = html_to_element("<div><span><input></span></div>")
    span = root.children[0]
    assert span.tag == "span"
    assert span.children[0].tag == "input"


def test_html_to_element_tree_not_none_for_void():
    tree = html_to_element_tree("<div><input></div>")
    assert tree is not None
    assert "component" in tree
