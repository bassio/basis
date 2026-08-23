"""
Constant expressions (``{False}``, ``{True}``, ``{5}``, …) are first-class
*expressions*, not static strings.

``is_expression`` is the canonical label ("does this value contain ``{...}``
fields?"), deliberately independent of whether those fields resolve to reactive
deps.  ``ChildBinding`` classifies by that label — so a braced constant is
parent-owned, never leaked to the child as the raw string ``"{False}"`` — and
the binding lifecycle evaluates a no-field (constant) expression once at mount,
so the rendered DOM attribute and the child prop carry the real typed value.
"""

import ast

import basis.shared.base_component  # noqa: F401  (registers BaseComponent builtin)

from basis.shared.component import Component
from basis.shared.bindings import ChildBinding, TextBinding, ALLOWED_BUILTINS
from basis.shared.expr import extract_dependencies, is_expression
from basis.shared.element import Element


class Gadget(Component):
    __tag__ = "x-gadget"
    first = ""
    second = ""
    label = ""

    def template(self):
        """<span>{first}|{second}|{label}</span>"""


class Holder(Component):
    def template(self):
        """<x-gadget first="{False}" second="{True}" label="hi"></x-gadget>"""


class TextHolder(Component):
    def template(self):
        """<div>{False}</div>"""


class Mixed(Component):
    """A constant binding next to a reactive one — the constant must stay put
    while the reactive sibling re-evaluates."""
    count = 0

    def template(self):
        """<div><span>{False}</span><span>{count}</span></div>"""


def _holder_and_gadget():
    holder = Holder.mount(Element("div", attrs={}, children=[]))
    cb = next(b for b in holder.__bindings__ if isinstance(b, ChildBinding))
    return holder, cb


def test_is_expression_labels_braced_constants_and_reactive():
    assert is_expression("{False}")
    assert is_expression("{True}")
    assert is_expression("{5}")
    assert is_expression("{'x'}")
    assert is_expression("{some_field}")
    assert is_expression("text {x}")
    assert not is_expression("plain")
    assert not is_expression("first")
    assert not is_expression("margin-right: 8px")
    assert not is_expression("")
    assert not is_expression(None)


def test_child_binding_classifies_constant_expressions_as_parent_owned():
    holder, cb = _holder_and_gadget()
    # Braced constants are expressions → NOT static attrs passed to mount().
    assert "first" not in cb._static_attrs
    assert "second" not in cb._static_attrs
    # A genuine static literal still flows through.
    assert cb._static_attrs["label"] == "hi"


def test_child_prop_receives_typed_constant_via_parent_binding():
    holder, cb = _holder_and_gadget()
    gadget = cb.childinstance
    # The parent's AttributeBinding evaluated the constant at mount and
    # prop-synced the real bool — never the raw "{False}" string.
    assert gadget.first is False
    assert gadget.second is True
    assert gadget.label == "hi"


def test_constant_expression_attribute_evaluated_on_parent_node():
    holder, cb = _holder_and_gadget()
    # update() ran once at mount (no reactive fields → evaluated at add time).
    assert cb.node.getAttribute("first") == "False"
    assert cb.node.getAttribute("second") == "True"


def test_constant_text_expression_evaluates_once_at_mount():
    text_holder = TextHolder.mount(Element("div", attrs={}, children=[]))
    tb = next(b for b in text_holder.__bindings__ if isinstance(b, TextBinding))
    # A `{False}` text node is a no-field expression — it now renders its value
    # instead of staying raw.
    assert tb.node.textContent == "False"


def test_constant_still_gets_a_real_ast_tree_even_with_zero_deps():
    # The expression is evaluated as Python (via the desugared AST), NOT by
    # string manipulation — extract_dependencies parses it even though nothing
    # is reactive about it.
    deps, trees = extract_dependencies("{False}", ALLOWED_BUILTINS)
    assert deps == []
    assert "False" in trees
    assert isinstance(trees["False"], ast.AST)


def test_constant_prop_is_python_bool_not_the_string():
    holder, cb = _holder_and_gadget()
    gadget = cb.childinstance
    # `first="False"` in SSR is the DOM attribute (strings).  The child's PROP
    # is the actual Python bool — the whole point of the fix.
    assert type(gadget.first) is bool
    assert gadget.first is False
    assert gadget.second is True
    assert type(cb.node.getAttribute("first")) is str
    assert cb.node.getAttribute("first") == "False"


def test_constant_binding_does_not_reevaluate_when_reactive_sibling_does():
    m = Mixed.mount(Element("div", attrs={}, children=[]))
    tb_const = next(b for b in m.__bindings__
                    if isinstance(b, TextBinding) and b.content == "{False}")
    tb_reac = next(b for b in m.__bindings__
                   if isinstance(b, TextBinding) and b.content == "{count}")
    # Constancy is inferred from the dependency set: the constant binding has
    # zero fields (nothing can ever mark it stale), the sibling has `count`.
    assert tb_const.fields == []
    assert tb_reac.fields == ["count"]
    assert tb_const.node.textContent == "False"
    assert tb_reac.node.textContent == "0"

    m.count = 5
    assert tb_const.node.textContent == "False"  # constant stays put
    assert tb_reac.node.textContent == "5"        # reactive sibling re-evaluates
