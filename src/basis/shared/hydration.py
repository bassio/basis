"""
basis/shared/hydration.py
-------------------------
Canonical hydration spec — the single source of truth for how server and
client agree on *which* nodes are reactive and *where* they live.

This module is the Phase 5 #3 "single-source ID algorithm shared by server and
client".  It is intentionally duck-typed so the exact same functions run over
two different tree representations:

* server:  ``basis.shared.element`` (``Element`` / ``ElementString`` /
  ``Comment``) — no ``nodeType``, text in ``.value``;
* client:  the browser DOM (Pyodide) — ``nodeType`` 1/3/8, text in
  ``.textContent`` / ``.data``.

NODE POLICY (what counts toward hydration paths)
------------------------------------------------
* ELEMENT nodes always count.
* TEXT nodes count iff they contain at least one non-whitespace character.
* COMMENT nodes never count (and never get paths).
* Nodes are numbered in DOCUMENT ORDER over the *normalized* children
  (elements + non-whitespace text).  Whitespace-only text and comments stay in
  the tree but are ignored for numbering, so indentation or comments around a
  binding can never shift an ID.

Paths are ``"r:" + ":".join(ints)``, e.g. ``r:0:1:2``.  The root element is
``r:0``.

Text nodes cannot carry attributes, so reactive text is addressed via a
deterministic *text ordinal* stamped on the parent element (``data-basis-text``
= comma-separated 0-based ordinals of its reactive text children, computed over
the *normalized* children).  See ``stamp_text_ordinals`` / ``text_ordinal``.

The legacy implementation lives on in ``server/ssr.py`` and ``shared/page.py``
(``_apply_hydration_logic``).  This module is the Phase B replacement; it is
not wired into the live SSR path yet — parity is proven by the test suite
(``tests/test_hydration_determinism.py``) before the switch.
"""

from __future__ import annotations

from collections import defaultdict

# Marker attribute names shared by both sides.
HYDRATION_ID_ATTR = "data-hydration-id"
COMPONENT_HYDRATION_ID_ATTR = "data-component-hydration-id"
TEXT_ORDINALS_ATTR = "data-basis-text"


# ---------------------------------------------------------------------------
# Hydration mode (A/B toggle)
# ---------------------------------------------------------------------------
# The server can run in one of two worlds:
#   * canonical (DEFAULT) — preserved-text tree + the canonical set-based
#                algorithm + ``data-basis-text`` text ordinals;
#   * legacy              — stripped-text tree + the original DFS marker
#                algorithm (kept for A/B and rollback via BASIS_HYDRATION=legacy).
# ``BASIS_HYDRATION=legacy`` opts back into the legacy world at startup;
# ``set_hydration_mode()`` can flip it at runtime for tests/A-B.  The client
# detects which world produced the SSR page by the presence of
# ``data-basis-text`` (canonical) vs its absence (legacy), so it needs no env.
_canonical_override: bool | None = None


def _env_is_canonical() -> bool:
    try:
        import os
        mode = os.environ.get("BASIS_HYDRATION", "canonical").strip().lower()
        return mode == "canonical"
    except Exception:
        return True


def hydration_mode_is_canonical() -> bool:
    """Effective mode (runtime override wins over the env-derived default)."""
    return _env_is_canonical() if _canonical_override is None else _canonical_override


def set_hydration_mode(canonical: bool | None) -> None:
    """Override the hydration mode at runtime (``None`` re-follows the env)."""
    global _canonical_override
    _canonical_override = canonical


# ---------------------------------------------------------------------------
# Node classification (policy)
# ---------------------------------------------------------------------------

def is_comment(node) -> bool:
    """True for comment nodes in either representation."""
    node_type = getattr(node, "nodeType", None)
    if node_type is not None:          # browser DOM
        return node_type == 8          # COMMENT_NODE
    return type(node).__name__ == "Comment"   # server basis.shared.element.Comment


def is_element(node) -> bool:
    """True for element nodes in either representation."""
    node_type = getattr(node, "nodeType", None)
    if node_type is not None:          # browser DOM
        return node_type == 1          # ELEMENT_NODE
    # server Element carries both attrs and children
    return hasattr(node, "attrs") and hasattr(node, "children")


def is_text(node) -> bool:
    """True for text nodes in either representation (comments excluded)."""
    if is_comment(node):
        return False
    node_type = getattr(node, "nodeType", None)
    if node_type is not None:          # browser DOM
        return node_type == 3          # TEXT_NODE
    # Server tree.  A server Element can carry a dynamic ``.value`` attribute
    # (e.g. a bound <input>), so ``hasattr(node, "value")`` alone would
    # misclassify elements as text — guard with ``is_element``.
    return hasattr(node, "value") and not is_element(node)


def node_text(node) -> str:
    """The raw text of a text (or comment) node."""
    if hasattr(node, "value"):         # server ElementString
        return node.value
    data = getattr(node, "data", None)  # DOM Text/Comment and server Comment
    if data is not None:
        return data
    return getattr(node, "textContent", "") or ""


def is_whitespace_text(node) -> bool:
    """True for text nodes whose content is entirely whitespace."""
    return is_text(node) and not node_text(node).strip()


# ---------------------------------------------------------------------------
# Tree iteration
# ---------------------------------------------------------------------------

def iter_children(node):
    """Yield a node's children in document order (both representations)."""
    child_nodes = getattr(node, "childNodes", None)
    if child_nodes is not None:        # browser DOM NodeList / server Element.childNodes
        yield from child_nodes
        return
    yield from getattr(node, "children", ())


def normalized_children(node):
    """Children that count toward hydration paths, in document order.

    Policy: elements + non-whitespace text.  Comments and whitespace-only text
    are preserved in the DOM but excluded from numbering.
    """
    for child in iter_children(node):
        if is_comment(child):
            continue
        if is_whitespace_text(child):
            continue
        yield child


def iter_tree_paths(root):
    """Yield ``(node, path_str)`` for every countable node, depth-first
    pre-order.  The root is ``r:0``; children are numbered 0..N over
    ``normalized_children``.
    """
    stack = [(root, [0])]
    while stack:
        node, path = stack.pop()
        yield node, "r:" + ":".join(map(str, path))
        normalized = list(normalized_children(node))
        # Push reversed so popping yields document order.
        for i, child in reversed(list(enumerate(normalized))):
            stack.append((child, path + [i]))


# ---------------------------------------------------------------------------
# Marker stamping (Phase B replacement for _apply_hydration_logic)
# ---------------------------------------------------------------------------

def apply_hydration_markers(root, binding_nodes, component_nodes):
    """Stamp ``data-hydration-id`` / ``data-component-hydration-id``.

    Unlike the legacy implementation:

    * membership is set-based (O(nodes) instead of O(nodes x bindings));
    * stamping problems are surfaced in the returned report instead of being
      swallowed by a bare ``except: pass``.

    ``binding_nodes`` and ``component_nodes`` are iterables of element nodes
    (binding targets from ``marked_for_hydration()`` and component roots).

    Returns a ``dict`` mapping path -> ``{"binding": bool, "component": bool}``
    for every stamped node (an audit trail for mismatch diagnostics).
    """
    binding_ids = {id(n) for n in binding_nodes}
    component_ids = {id(n) for n in component_nodes}
    report: dict[str, dict] = {}

    for node, path in iter_tree_paths(root):
        is_binding = id(node) in binding_ids
        is_component = id(node) in component_ids
        if not (is_binding or is_component):
            continue
        if is_binding:
            node.setAttribute(HYDRATION_ID_ATTR, path)
        if is_component:
            node.setAttribute(COMPONENT_HYDRATION_ID_ATTR, path)
        report[path] = {"binding": is_binding, "component": is_component}

    return report


# ---------------------------------------------------------------------------
# Deterministic text-node identity (text ordinals)
# ---------------------------------------------------------------------------

def text_ordinal(parent, text_node) -> int | None:
    """0-based ordinal of ``text_node`` among ``parent``'s countable children.

    Counting rule (must match ``stamp_text_ordinals`` and the client matcher):
    elements count; text nodes count unless they are whitespace-only AND not the
    query node.  A reactive text node counts even when its *current* value is
    empty/whitespace, because its *template* content is non-empty — this is what
    lets empty-valued bindings (e.g. cleared form errors) still be located.

    Returns ``None`` if the node is not a countable text child of ``parent``.

    Identity is compared with ``==`` (not ``is``): on the server Element model
    ``eq=False`` makes this identity; in Pyodide two ``JsProxy`` wrappers of the
    same DOM node are NOT ``is``-identical but ``==`` resolves via JS equality.
    """
    i = 0
    for child in iter_children(parent):
        if is_comment(child):
            continue
        if is_text(child):
            if is_whitespace_text(child) and child != text_node:
                continue
            if child == text_node:
                return i
            i += 1
        else:  # element
            i += 1
    return None


def stamp_text_ordinals(root, text_nodes):
    """Stamp ``data-basis-text='i,j'`` on each parent that owns reactive text.

    ``text_nodes`` are the live text nodes of each ``TextBinding`` (server:
    ElementString; client: DOM Text node).  The ordinal is computed over
    *normalized* children, so whitespace/comment nodes around a binding can
    never shift it — this is the deterministic text identity that replaces the
    fragile ``position_in_shadow`` matching in ``client/component.py``.
    """
    by_parent: dict = defaultdict(list)
    for node in text_nodes:
        parent = node.parentNode or getattr(node, "parent", None)
        if parent is not None:
            by_parent[parent].append(node)

    for parent, nodes in by_parent.items():
        node_ids = [id(n) for n in nodes]
        ordinals = []
        i = 0
        for child in iter_children(parent):
            if is_comment(child):
                continue
            if is_text(child):
                # Reactive text nodes count even when rendered empty; other
                # whitespace-only text (indentation) is skipped.
                if is_whitespace_text(child) and id(child) not in node_ids:
                    continue
                if id(child) in node_ids:
                    ordinals.append(i)
                i += 1
            else:  # element
                i += 1
        if ordinals:
            parent.setAttribute(
                TEXT_ORDINALS_ATTR, ",".join(str(o) for o in ordinals)
            )


# ---------------------------------------------------------------------------
# Legacy algorithm (faithful ports — the default branch until parity lands)
# ---------------------------------------------------------------------------

def legacy_map_hydration_ids(root):
    """Faithful port of the legacy DFS previously nested in the old
    ``_apply_hydration_logic`` (duplicated in server/ssr.py and shared/page.py).

    The old algorithm strips comments from the child list but does NOT skip
    whitespace-only text — it was only correct because the legacy tree-builder
    had already deleted those nodes.
    """
    stack = [(root, 0, [0])]
    result = {}
    while stack:
        obj, depth, path = stack.pop()
        path_str = "r:" + ":".join(map(str, path))
        result[path_str] = obj
        children = getattr(obj, "children", [])
        valid_children = [c for c in children if type(c).__name__ != "Comment"]
        for i, child in reversed(list(enumerate(valid_children))):
            stack.append((child, depth + 1, path + [i]))
    return result


def legacy_apply_hydration_logic(app, root_component_plus_child_components):
    """Faithful port of the legacy marker-stamping loop (O(nodes x bindings),
    silent ``except: pass``).  Kept byte-for-byte as the default branch.
    """
    hydration_ids_dict = legacy_map_hydration_ids(app.__element__)
    root_component_plus_child_nodes = [
        comp.__element__ for comp in root_component_plus_child_components
    ]
    all_bindings_recursive = list(app.get_bindings(recursive=True))
    all_bindings_nodes_for_hydration = []
    for b in all_bindings_recursive:
        all_bindings_nodes_for_hydration.extend(b.marked_for_hydration())

    for hid, node in hydration_ids_dict.items():
        try:
            if any(node is target for target in all_bindings_nodes_for_hydration):
                node.setAttribute(HYDRATION_ID_ATTR, hid)
            if any(node is target for target in root_component_plus_child_nodes):
                node.setAttribute(COMPONENT_HYDRATION_ID_ATTR, hid)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Canonical entry point used by both SSR renderers
# ---------------------------------------------------------------------------

def apply_hydration_to_component(app, root_component_plus_child_components):
    """Canonical marker + text-ordinal stamping for a mounted app.

    ``app`` is the mounted root component; ``root_component_plus_child_components``
    is the list of component instances whose root elements get stamped
    ``data-component-hydration-id``.  Returns the marker report (path -> flags).
    """
    binding_nodes = []
    text_nodes = []
    for b in app.get_bindings(recursive=True):
        binding_nodes.extend(b.marked_for_hydration())
        if type(b).__name__ == "TextBinding":
            text_nodes.append(b.node)
    component_nodes = [
        comp.__element__ for comp in root_component_plus_child_components
    ]
    report = apply_hydration_markers(
        app.__element__, binding_nodes, component_nodes
    )
    stamp_text_ordinals(app.__element__, text_nodes)
    return report


# ---------------------------------------------------------------------------
# Hydration diagnostics (Phase E)
# ---------------------------------------------------------------------------
# The client emits these when hydration cannot match every node/binding.  The
# payload shape lives here (shared) so server tests and the client agree.
HYDRATION_MISMATCH_EVENT = "basis-hydration-mismatch"
HYDRATION_REPORT_GLOBAL = "__basisHydrationReport"


class HydrationReport:
    """Accumulates hydration mismatches for diagnostics.

    Pure data — no DOM dependency — so it can be produced on the client
    (Pyodide) and inspected by tests/tooling.  ``to_dict()`` is the shape used
    for ``window.__basisHydrationReport`` and the event ``detail``.
    """

    def __init__(self, mode=None):
        if mode is None:
            mode = "canonical" if hydration_mode_is_canonical() else "legacy"
        self.mode = mode
        self.unhydrated_components = []
        self.unmatched_bindings = []
        self.fallback = None

    def add_unhydrated_component(self, tag, client_id=None, reason=""):
        self.unhydrated_components.append(
            {"tag": tag, "client_id": client_id, "reason": reason}
        )

    def add_unmatched_binding(
        self, component, binding_type, client_id=None, expected_ssr_id=None, reason=""
    ):
        self.unmatched_bindings.append(
            {
                "component": component,
                "binding_type": binding_type,
                "client_id": client_id,
                "expected_ssr_id": expected_ssr_id,
                "reason": reason,
            }
        )

    def set_fallback(self, description):
        self.fallback = description

    @property
    def is_clean(self):
        return not (self.unhydrated_components or self.unmatched_bindings)

    @property
    def has_fallback(self):
        return self.fallback is not None

    def to_dict(self):
        return {
            "mode": self.mode,
            "unhydrated_components": list(self.unhydrated_components),
            "unmatched_bindings": list(self.unmatched_bindings),
            "fallback": self.fallback,
        }

    def to_json(self) -> str:
        import json

        return json.dumps(self.to_dict())


_fallback_override: bool | None = None


def hydration_fallback_enabled() -> bool:
    """Whether the client should re-render on a genuine hydration mismatch.

    Default ON (the graceful-degradation safety net for canonical default);
    opt out with ``BASIS_HYDRATION_FALLBACK=0`` or ``set_hydration_fallback()``.
    It only fires on genuine component-root mismatches (healthy pages are
    unaffected), and re-renders the page client-side, sacrificing SSR for that
    page load.
    """
    if _fallback_override is not None:
        return _fallback_override
    try:
        import os
        return os.environ.get("BASIS_HYDRATION_FALLBACK", "1").strip().lower() not in (
            "0", "false", "no", "off",
        )
    except Exception:
        return True


def set_hydration_fallback(enabled: bool | None) -> None:
    """Override the fallback mode at runtime (``None`` re-follows the env)."""
    global _fallback_override
    _fallback_override = enabled
