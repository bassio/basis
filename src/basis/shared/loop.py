"""
basis/shared/loop.py
--------------------
The loop engine: pure reconciliation diffing (``Reconciler``), per-item body
construction (``LoopBodyBuilder``), key derivation (``derive_keys``), the LIS
helper (``get_lis_indices``), and the thin per-item holder ``LoopItem``.

``LoopBinding`` (in ``bindings.py``) is a thin executor over this engine:
it resolves the collection, derives keys, asks ``Reconciler`` for the op plan,
and applies the ops to the DOM.  Keeping the decision logic DOM-free makes it
unit-testable and gives the whole feature one mental model:

    resolve collection -> derive keys -> reconcile -> apply ops

This module must not import ``bindings.py`` (the binding classes import this
module); everything here is duck-typed against the server ``Element`` model and
the browser DOM, and against ``LoopItem`` / ``LoopBinding`` by attribute.
"""

from dataclasses import dataclass

from basis.shared.expr import ALLOWED_BUILTINS, LoopScope, _FORMATTER, safe_format


# ---------------------------------------------------------------------------
# Key derivation
# ---------------------------------------------------------------------------

def derive_keys(collection_value, key):
    """Reconciliation keys for a resolved collection.

    With ``key``: read the field off each item (dicts via ``.get``, objects via
    ``getattr``), falling back to the item ITSELF when the field is absent so
    scalar items get distinct keys (Svelte ``(item)`` style).  Unhashable keys
    fall back to their position.  Without ``key``: positional indices.
    """
    if key is None:
        return list(range(len(collection_value)))
    keys = []
    for i, item in enumerate(collection_value):
        if isinstance(item, dict):
            k_val = item.get(key)
        else:
            try:
                k_val = getattr(item, key)
            except AttributeError:
                k_val = item
        # Keep keys hashable for set/dict reconciliation.
        try:
            hash(k_val)
        except TypeError:
            k_val = i
        keys.append(k_val)
    return keys


# ---------------------------------------------------------------------------
# LIS
# ---------------------------------------------------------------------------

def get_lis_indices(arr: list[int]) -> list[int]:
    """Indices of the longest increasing subsequence in O(n log n).

    Example: ``[1, 3, 0, 2, 4]`` -> ``[0, 1, 4]`` (values 1, 3, 4).
    """
    if not arr:
        return []
    p = [0] * len(arr)
    m = [0] * (len(arr) + 1)
    l = 0
    for i in range(len(arr)):
        # Binary search for the smallest value in m >= arr[i].
        lo, hi = 1, l
        while lo <= hi:
            mid = (lo + hi) // 2
            if arr[m[mid]] < arr[i]:
                lo = mid + 1
            else:
                hi = mid - 1
        new_l = lo
        p[i] = m[new_l - 1]
        m[new_l] = i
        if new_l > l:
            l = new_l
    # Backtrack.
    res = [0] * l
    k = m[l]
    for i in range(l - 1, -1, -1):
        res[i] = k
        k = p[k]
    return res


# ---------------------------------------------------------------------------
# Reconciliation diff (pure)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Op:
    """One reconciliation step for the executor to apply.

    ``kind`` is ``"remove"`` | ``"create"`` | ``"update"`` | ``"move"``;
    ``index`` is the key's position in the new collection order.
    """
    kind: str
    key: object
    index: int = -1


class Reconciler:
    """Pure diff between the previous instance keys and the new collection keys.

    No DOM and no state — just the decision the executor acts on.  Classic
    keyed reconciliation: remove stale keys, create/update in new order, then
    move the reused keys that the LIS stable subsequence does not cover.
    """

    @staticmethod
    def diff(old_keys, new_keys):
        """``list[Op]`` in apply order.

        ``old_keys`` are the keys currently in ``binding.instances``; ``new_keys``
        are the keys of the resolved collection (unkeyed loops use positional
        indices as keys, so every key always "exists" and is reused by index).
        """
        new_list = list(new_keys)
        new_set = set(new_list)
        old_index = {k: i for i, k in enumerate(old_keys)}

        ops = [Op("remove", k) for k in old_keys if k not in new_set]

        sources = [-1] * len(new_list)
        for i, k in enumerate(new_list):
            if k in old_index:
                sources[i] = old_index[k]
                ops.append(Op("update", k, i))
            else:
                ops.append(Op("create", k, i))

        if any(s != -1 for s in sources):
            stable = set()
            j = 0
            lis = get_lis_indices([s for s in sources if s != -1])
            for i, s in enumerate(sources):
                if s != -1:
                    if j in lis:
                        stable.add(i)
                    j += 1
            for i, s in enumerate(sources):
                if s != -1 and i not in stable:
                    ops.append(Op("move", new_list[i], i))
        return ops


# ---------------------------------------------------------------------------
# Per-item holder
# ---------------------------------------------------------------------------

class LoopItem:
    """Per-item render unit for a loop.

    NOT a Component: no DAG, no lifecycle, no subscriptions.  It holds the
    cloned body node, the body's bindings (bound to the OWNER, carrying this
    item's LoopScope), the mutable per-item scope, and the reconciliation key.

    For CUSTOM-ELEMENT loop children it also holds the mounted component
    (``instance``) and its ChildBinding, so ONE entry type drives removal,
    movement and hydration for both kinds of loop child.
    """
    __slots__ = ("node", "bindings", "scope", "key",
                 "instance", "child_binding", "_effect_names")

    def __init__(self, node, bindings, scope, key,
                 instance=None, child_binding=None):
        self.node = node
        self.bindings = bindings
        self.scope = scope
        self.key = key
        self.instance = instance            # mounted custom-element child, else None
        self.child_binding = child_binding  # its ChildBinding (custom children only)
        self._effect_names = []

    def render(self):
        """Re-run every body binding (initial render / reuse / scope mutation)."""
        for b in self.bindings:
            update = getattr(b, "update", None)
            if update is not None:
                update()

    def dispose(self, dag):
        """Teardown before removal: destroy body bindings (detach listeners,
        unmount children), then unregister this item's owner-DAG effects."""
        for b in self.bindings:
            destroy = getattr(b, "destroy", None)
            if destroy is not None:
                destroy()
        for name in self._effect_names:
            dag.remove_effect(name)
        self._effect_names = []


# ---------------------------------------------------------------------------
# Body builder
# ---------------------------------------------------------------------------

class LoopBodyBuilder:
    """Builds per-item ``LoopItem`` bodies for a loop.

    Owns the template clone, the per-item body bindings (owner-bound, with a
    per-item ``LoopScope`` overlay), the owner-DAG effect registration, and the
    prop dicts passed to custom-element children.  Construction only — the
    executor inserts the item and registers its ChildBinding.
    """

    def __init__(self, component_instance, body_blueprints, item, enclosing_scope, clone):
        self.component_instance = component_instance
        self.body_blueprints = body_blueprints
        self.item = item
        self.enclosing_scope = enclosing_scope
        self.clone = clone

    def new_clone(self):
        """A fresh body clone with the loop-control attributes stripped."""
        cloned = self.clone.cloneNode(True)
        for a in ("for", "in", "key"):
            cloned.removeAttribute(a)
        return cloned

    def child_props(self, item_value):
        """Per-item prop dict for a custom-element loop child: the loop variable
        plus every attribute on the template that contains a ``{expr}``
        (loop-control attributes are never passed down as props)."""
        props = {self.item: item_value}
        if "-" not in str.lower(self.clone.tagName):
            return props
        for c_attr in self.clone.getAttributeNames():
            if c_attr in ("for", "in", "key") or c_attr in props:
                continue
            c_attr_value = self.clone.getAttribute(c_attr)
            has_expr = any(
                fname is not None for _, fname, _, _ in _FORMATTER.parse(c_attr_value)
            )
            if has_expr:
                props[c_attr] = safe_format(
                    c_attr_value, props, ALLOWED_BUILTINS,
                    component=self.component_instance,
                    binding_type="LoopBinding",
                    template=c_attr_value,
                )
            else:
                props[c_attr] = c_attr_value
        return props

    def build(self, item_value, key):
        """Build a plain-element ``LoopItem``: a fresh body clone, its
        owner-bound body bindings with a per-item scope overlay, and the
        owner-DAG effects registered.  The item is detached — the executor
        inserts it and renders it."""
        scope = LoopScope({self.item: item_value}, parent=self.enclosing_scope)
        cloned = self.new_clone()
        body_nodes = self.component_instance.__class__._loop_body_nodes(cloned)
        bindings = []
        for bp in self.body_blueprints:
            if bp.binding_class.__name__ == "LoopBinding":
                # A nested loop lives inside the outer item's body — chain this
                # item's scope as the inner loop's enclosing scope so its `in=`
                # (e.g. `{grp['items']}`) and body resolve against
                # {inner_item, outer_item, owner}.
                binding = bp.binding_class.from_blueprint(
                    self.component_instance, body_nodes[bp.node_index], bp,
                    enclosing_scope=scope)
            else:
                binding = bp.binding_class.from_blueprint(
                    self.component_instance, body_nodes[bp.node_index], bp)
            if binding is not None:
                binding.scope = scope
                binding.activate()
                bindings.append(binding)
        item = LoopItem(node=cloned, bindings=bindings, scope=scope, key=key)
        for binding in bindings:
            self._register_owner_effect(binding, scope, item)
        return item

    def _scope_var_names(self, scope):
        """All loop-variable names visible through a scope chain."""
        names = set()
        s = scope
        while s is not None:
            names.update(s.vars.keys())
            s = s.parent
        return names

    def _register_owner_effect(self, binding, scope, item):
        """Register a body binding's update on the OWNER's DAG, keyed by its
        owner-deps fields (fields minus every loop-var name in the scope chain).
        This is what makes owner state changes re-render loop bodies live."""
        owner = self.component_instance
        owner_fields = [f for f in binding.fields
                        if f not in self._scope_var_names(scope)]
        if owner_fields and hasattr(binding, "update"):
            effect_name = f"loop_effect_{id(binding)}"
            owner._dag.add_effect(effect_name, binding.update, owner_fields)
            item._effect_names.append(effect_name)
