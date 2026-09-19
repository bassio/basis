"""
A component rendered by a loop is a child component: reachable, stamped, adoptable.

Both loop shapes are covered, because they reach their child by different routes — a loop
written ON the component element registers the child's ChildBinding on the owner, while a
component inside a plain wrapper owns one from its item — and both routes have to be walked
by everything that walks components: the SSR stamp, the ``server_load`` gather, and the
client's adoption pass.

The stamp is what the client matches against, so a loop child that is reachable but
unstamped still cannot hydrate: its own bindings would look for ids the server never wrote.
"""

from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.element import Element
from basis.shared.page import Page


class Row(Component):
    __tag__ = "t-loop-row"
    label = ""

    def template(self):
        """
        <div class="t-row"><span class="t-row-label">{label}</span></div>
        """


class BothShapes(Component):
    """The same child component under both loop shapes."""

    items = [{"k": 1, "name": "Alpha"}, {"k": 2, "name": "Beta"}]

    def template(self):
        """
        <div>
            <section class="one">
                <t-loop-row for="it" in="{items}" key="k" label="{it['name']}"></t-loop-row>
            </section>
            <section class="two">
                <div for="it" in="{items}" key="k">
                    <t-loop-row label="{it['name']}"></t-loop-row>
                </div>
            </section>
        </div>
        """


class NestedShape(Component):
    """A component one loop deeper: an inner plain loop inside an outer plain item."""

    groups = [{"g": "A", "items": [{"k": 1, "name": "a1"}, {"k": 2, "name": "a2"}]},
              {"g": "B", "items": [{"k": 1, "name": "b1"}]}]

    def template(self):
        """
        <div>
            <div for="grp" in="{groups}" key="g">
                <div for="it" in="{grp['items']}" key="k">
                    <t-loop-row label="{it['name']}"></t-loop-row>
                </div>
            </div>
        </div>
        """


def _mount(cls):
    return cls.mount(Element("div", attrs={}, children=[]))


def _child_instances(component):
    return [cb.childinstance for cb in component.get_child_bindings(recursive=True)]


class HiddenBranch(Component):
    """A loop of children on a branch neither side renders."""

    items = [{"k": 1, "name": "Alpha"}]

    def template(self):
        """
        <div>
            <section if="{False}">
                <div for="it" in="{items}" key="k">
                    <t-loop-row label="{it['name']}"></t-loop-row>
                </div>
            </section>
        </div>
        """


def test_child_bindings_include_children_on_a_hidden_branch():
    """A hidden branch's loop children have no SSR counterpart, so the client has to
    find them and then leave them alone — finding them is the walk's half, and it is
    what the browser lane's clean report for the hidden section rests on."""
    mounted = _mount(HiddenBranch)
    assert len(_child_instances(mounted)) == 1


def test_child_bindings_reach_a_component_in_both_loop_shapes():
    mounted = _mount(BothShapes)
    children = _child_instances(mounted)

    assert len(children) == 4, "one child per item, in both shapes"
    assert all(isinstance(c, Row) for c in children)
    assert len({id(c) for c in children}) == 4, "each child is reached exactly once"


def test_child_bindings_recurse_into_nested_loops():
    mounted = _mount(NestedShape)
    children = _child_instances(mounted)

    assert len(children) == 3
    assert len({id(c) for c in children}) == 3
    assert sorted(c.label for c in children) == ["a1", "a2", "b1"]


def test_get_bindings_descends_into_loop_children():
    """The child's own bindings join the recursive walk, so the stamp lands on the
    nodes the child will look for when it hydrates."""
    mounted = _mount(BothShapes)
    texts = [
        b.node
        for b in mounted.get_bindings(recursive=True)
        if type(b).__name__ == "TextBinding"
    ]

    # Both shapes contribute their items' labels; without the loop descent only the
    # loop-on-the-component shape's two would be here.
    assert sorted(n.textContent for n in texts) == ["Alpha", "Alpha", "Beta", "Beta"]


def test_the_ssr_stamp_covers_a_component_inside_a_plain_loop_wrapper():
    """The server stamps the whole child subtree, not just the loop's own furniture."""
    app = Basis()
    app.bootstrap()

    class LoopChildPage(Page):
        title = "Loop child"
        root_component = BothShapes
        entry_module = "/t_loop_child_root.py"

    app.include_page("/loop-child", page_cls=LoopChildPage)
    html = TestClient(app).get("/loop-child").text

    section = html[html.find('class="two"') : html.find("</section>", html.find('class="two"'))]
    assert 'class="t-row"' in section, section

    # The child's template root is a binding node like any other — the id the
    # client matches on is the one its own SelfBinding marks.
    root_tag = section[section.find('class="t-row"') - 20 :][:400]
    assert "data-hydration-id" in root_tag, root_tag
    # Its text binding carries the ordinal the client locates the text node by.
    assert "data-hydration-text" in section, section
