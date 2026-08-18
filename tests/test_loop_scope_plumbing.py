"""
The LoopScope item-overlay primitive and the `scope` plumbing through
safe_eval / safe_format.
"""

from basis.shared.bindings import LoopScope, safe_eval, safe_format
from basis.shared.component import Component
from basis.shared.reactive import computed
from basis.shared.element import Element

ALLOWED = {
    'False': False, 'True': True, 'None': None,
    'len': len, 'str': str, 'int': int, 'list': list, 'dict': dict,
}


class _Owner:
    mode = "light"

    def __getattr__(self, name):
        # cheap stand-in; real owners are Component instances
        raise AttributeError(name)


def _eval(expr, context, scope=None):
    return safe_eval(expr, context, ALLOWED, scope=scope)


def test_scope_shadows_context():
    """A loop-variable name in scope wins over the same name on the owner."""
    ctx = _Owner()
    scope = LoopScope({"d": {"n": 7}})
    assert _eval("d['n']", ctx, scope) == 7


def test_scope_falls_through_to_context():
    """A name not in scope resolves live on the owner (the binding's context)."""
    ctx = _Owner()
    scope = LoopScope({"d": {"n": 7}})
    assert _eval("mode", ctx, scope) == "light"


def test_scope_none_is_noop():
    """scope=None (the default) leaves resolution exactly as before."""
    ctx = _Owner()
    assert _eval("mode", ctx) == "light"
    # With no sink registered, a missing name yields the legacy "[Error: ...]"
    # string (never a raise) — unchanged from before the scope plumbing.
    bad = _eval("missing_name", ctx)
    assert isinstance(bad, str) and bad.startswith("[Error: ")


def test_nested_scope_chain():
    """Inner scope sees its own var, then the outer loop's var, then the owner."""
    ctx = _Owner()
    outer = LoopScope({"grp": {"g": "A"}})
    inner = LoopScope({"it": {"name": "a1"}}, parent=outer)
    assert _eval("it['name']", ctx, inner) == "a1"
    assert _eval("grp['g']", ctx, inner) == "A"
    assert _eval("mode", ctx, inner) == "light"


def test_outer_mutation_is_live_for_inner_scopes():
    """Mutating an outer scope's vars in place is seen by inner scopes (chain)."""
    ctx = _Owner()
    outer = LoopScope({"grp": {"g": "A"}})
    inner = LoopScope({"it": {"name": "a1"}}, parent=outer)
    assert _eval("grp['g']", ctx, inner) == "A"
    outer.vars["grp"] = {"g": "B"}          # outer item reused with new value
    assert _eval("grp['g']", ctx, inner) == "B"


def test_scope_through_safe_format():
    """safe_format threads scope for plain names ($/# handled via desugar)."""
    from basis.shared.component import Component as C  # registry shape

    class Owner(Component):
        mode = "light"

        def template(self):
            """<div>{mode}</div>"""

    ctx = Owner.mount(Element("div", attrs={}, children=[]))
    scope = LoopScope({"d": {"n": 1}})

    out = safe_format(
        "{d['n']}/{mode}", ctx, ALLOWED,
        scope=scope,
    )
    assert out == "1/light"
