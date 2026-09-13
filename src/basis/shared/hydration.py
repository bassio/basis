"""
basis/shared/hydration.py
-------------------------
Canonical hydration spec — the single source of truth for how server and
client agree on *which* nodes are reactive and *where* they live.

This module is the single-source ID algorithm shared by server and client.
It is intentionally duck-typed so the exact same functions run over two
different tree representations:

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

Paths are ``"<prefix>:" + ":".join(ints)``, e.g. ``b:0:1:2``.  The root
of a walk is ``<prefix>:0``.  A Page is stamped as two disjoint regions so
head and body ids never collide: ``<head>`` under ``h`` (``h:0`` is the
``<head>`` element) and ``<body>`` under ``b`` (``b:0`` is the ``<body>``
element, root of the app region).  The default prefix is ``"b"`` — the
body/app region — which is what a standalone (non-Page) subtree walk gets.

Text nodes cannot carry attributes, so reactive text is addressed via a
deterministic *text ordinal* stamped on the parent element (``data-hydration-text``
= comma-separated 0-based ordinals of its reactive text children, computed over
the *normalized* children).  See ``stamp_text_ordinals`` / ``text_ordinal``.

This module is the single source of truth for both render engines
(``server/render.py`` and ``shared/page.py``) and the client.
"""

from __future__ import annotations

from collections import defaultdict

# Marker attribute names shared by both sides.
HYDRATION_ID_ATTR = "data-hydration-id"
COMPONENT_HYDRATION_ID_ATTR = "data-component-hydration-id"
TEXT_ORDINALS_ATTR = "data-hydration-text"


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


def iter_tree_paths(root, prefix="b"):
    """Yield ``(node, path_str)`` for every countable node, depth-first
    pre-order.  The root is ``<prefix>:0`` (default ``b:0`` — the body/app
    region); children are numbered 0..N over ``normalized_children``.

    ``prefix`` names the walk's root region (HYDRATION-WHOLEPAGE.md No.2):
    each mounted/hydrated region supplies its own root with a distinct prefix
    (``h`` for the Page's ``<head>``, ``b`` for its ``<body>``/app region), so
    paths stay globally unique when more than one region shares a document.
    """
    stack = [(root, [0])]
    while stack:
        node, path = stack.pop()
        yield node, prefix + ":" + ":".join(map(str, path))
        normalized = list(normalized_children(node))
        # Push reversed so popping yields document order.
        for i, child in reversed(list(enumerate(normalized))):
            stack.append((child, path + [i]))


# ---------------------------------------------------------------------------
# Marker stamping
# ---------------------------------------------------------------------------

def apply_hydration_markers(root, binding_nodes, component_nodes, prefix="b"):
    """Stamp ``data-hydration-id`` / ``data-component-hydration-id``.

    * membership is set-based (O(nodes) instead of O(nodes x bindings));
    * stamping problems are surfaced in the returned report instead of being
      swallowed by a bare ``except: pass``.

    ``binding_nodes`` and ``component_nodes`` are iterables of element nodes
    (binding targets from ``marked_for_hydration()`` and component roots).
    ``prefix`` names the walk's root region (see ``iter_tree_paths``): the body/app
    subtree uses the default ``"b"``, and a Page's ``<head>`` region uses
    ``"h"``, keeping ids across regions differentiated.

    Returns a ``dict`` mapping path -> ``{"binding": bool, "component": bool}``
    for every stamped node (an audit trail for mismatch diagnostics).
    """
    binding_ids = {id(n) for n in binding_nodes}
    component_ids = {id(n) for n in component_nodes}
    report: dict[str, dict] = {}

    for node, path in iter_tree_paths(root, prefix=prefix):
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


def build_hydration_map(root, prefix="b"):
    """Return ``{data-hydration-id value: node}`` for every countable node under
    ``root`` that carries the marker.

    Duck-typed (server ``Element`` and browser DOM).  This is the SSR-side
    lookup table the client uses to match bindings by canonical path in O(1),
    instead of scanning the tree with a ``querySelector`` per binding.
    ``prefix`` must match the prefix the region was stamped under (e.g. ``"h"``
    when building the map over a Page's live ``<head>``).
    """
    result = {}
    for node, _ in iter_tree_paths(root, prefix=prefix):
        if is_element(node) and node.hasAttribute(HYDRATION_ID_ATTR):
            hid = node.getAttribute(HYDRATION_ID_ATTR)
            if hid:
                result[hid] = node
    return result


# ---------------------------------------------------------------------------
# Relative-path matching (used by the structural loop re-pointer)
# ---------------------------------------------------------------------------
# All canonical-path tree matching lives in this module.  ``repoint_to_ssr``
# uses these to match a client loop item / body-binding node to its SSR
# counterpart by relative normalized pre-order path within a wrapper.

def _loop_relative_path_map(root):
    """{canonical relative path: node} for every countable node under ``root``
    (hydration policy: elements + non-whitespace text; comments/ws skipped)."""
    return {path: node for node, path in iter_tree_paths(root)}


def _find_node_path(path_map, node):
    """The canonical relative path of ``node`` in ``path_map``, or None.

    Identity is compared with ``==`` (not ``is``) per the Pyodide JsProxy
    constraint: two wrappers of the same DOM node are never ``is``-equal but
    ``==`` resolves via JS equality.  On the server Element model ``==`` is
    identity (``eq=False``), which is exactly what we want there too.
    """
    if node is None:
        return None
    for path, n in path_map.items():
        if n == node:
            return path
    return None


def _loop_owner_name(owner):
    cls = getattr(owner, "__class__", None)
    return getattr(cls, "__name__", None) or str(owner)


def _find_ssr_item_by_key(ssr_children, key):
    """First element under ``ssr_children`` whose ``data-item-key`` equals
    ``str(key)`` (the loop's reconciliation key)."""
    key_str = str(key)
    for c in ssr_children:
        if not is_element(c):
            continue
        try:
            k = c.getAttribute("data-item-key")
        except Exception:
            continue
        if k is None:
            continue
        if str(k) == key_str:
            return c
    return None


def repoint_loop_to_ssr(binding, ssr_parent, report=None):
    """Structural (canonical-path) re-pointing of a loop to the live SSR tree.

    ``binding`` is a duck-typed ``LoopBinding`` (needs ``parent``, ``instances``
    and ``component_instance``); ``ssr_parent`` is the SSR element that
    corresponds to the loop's parent (for an owner-level loop the caller
    resolves it via the canonical ``data-hydration-id`` map; for an inner loop
    the enclosing item's re-pointing resolves it structurally from the outer
    item's relative-path map).  Each item wrapper is matched by ``data-item-key``
    under ``ssr_parent``; each plain item's body binding nodes are matched by
    their relative normalized pre-order path within the wrapper (the client
    clone and the SSR item are built from the same body template, so their
    relative path sets are identical).  Nested ``LoopBinding``s recurse, and
    custom-element loop children keep their ``__basis_instance__`` /
    ``ChildBinding`` on the live wrapper.

    Returns the list of body bindings that were re-pointed and own a DOM
    listener (any binding with ``attach``), so the client can re-attach their
    handlers (shared code cannot create JS proxies).
    """
    binding.parent = ssr_parent
    repointed_attachments = []
    ssr_children = [c for c in normalized_children(ssr_parent)]
    for it in list(binding.instances.values()):
        ssr_item = _find_ssr_item_by_key(ssr_children, it.key)
        if ssr_item is None:
            if report is not None:
                report.add_unmatched_binding(
                    _loop_owner_name(binding.component_instance), "LoopItem",
                    client_id=str(it.key), expected_ssr_id=str(it.key),
                    reason=f"loop item key={it.key!r} not found under SSR parent",
                )
            continue
        old_node = it.node
        it.node = ssr_item
        if it.instance is not None:
            # Custom-element loop child: keep the ChildBinding + instance link
            # on the live wrapper (the child's own initialize_ssr hydrates its
            # subtree when it is a component root).
            if it.child_binding is not None:
                it.child_binding.node = ssr_item
            try:
                setattr(ssr_item, '__basis_instance__', it.instance)
            except Exception:
                pass
            continue
        # Plain LoopItem: re-point each body binding by relative path.
        client_paths = _loop_relative_path_map(old_node)
        ssr_paths = _loop_relative_path_map(ssr_item)
        for b in it.bindings:
            if type(b).__name__ == "LoopBinding":
                # Inner loop: resolve its SSR parent structurally from its
                # client parent's relative path within this item, recurse.
                inner_path = _find_node_path(client_paths, b.parent)
                inner_ssr_parent = ssr_paths.get(inner_path) if inner_path else None
                if inner_ssr_parent is None:
                    # When the inner loop's parent is NOT part of the client
                    # item's own subtree (``inner_path`` is None) it sits inside
                    # an if-hidden branch that the SSR item also omitted — the
                    # inner loop is DORMANT until that branch is revealed, not a
                    # hydration mismatch (mirrors how the enclosing IfBinding
                    # below treats a hidden if-node as legitimately absent).
                    # Only an inner loop whose parent IS in the client item yet
                    # missing from the SSR item is a genuine divergence worth
                    # reporting.
                    if report is not None and inner_path:
                        report.add_unmatched_binding(
                            _loop_owner_name(binding.component_instance),
                            "LoopBinding",
                            client_id=inner_path,
                            expected_ssr_id=inner_path,
                            reason="inner loop parent not found in SSR item",
                        )
                    continue
                repointed_attachments.extend(
                    repoint_loop_to_ssr(b, inner_ssr_parent, report))
            elif type(b).__name__ == "IfBinding":
                # A hidden if-node is legitimately absent from the rendered tree
                # on BOTH sides — re-point the node when present and always
                # re-point the anchor.
                rel = _find_node_path(client_paths, b.node)
                if rel:
                    ssr_node = ssr_paths.get(rel)
                    if ssr_node is not None:
                        b.node = ssr_node
                rel_a = _find_node_path(client_paths, b.anchor)
                if rel_a:
                    ssr_anchor = ssr_paths.get(rel_a)
                    if ssr_anchor is not None:
                        b.anchor = ssr_anchor
            else:
                rel = _find_node_path(client_paths, b.node)
                ssr_node = ssr_paths.get(rel) if rel else None
                if ssr_node is None:
                    # Not in the client's own tree (e.g. an if-hidden subtree) ->
                    # also absent from SSR; nothing to do.
                    continue
                b.node = ssr_node
                if hasattr(b, "attach"):
                    repointed_attachments.append(b)
    return repointed_attachments


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
    """Stamp ``data-hydration-text='i,j'`` on each parent that owns reactive text.

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
# Entry point used by both SSR renderers
# ---------------------------------------------------------------------------

def _collect_component_hydration(app):
    """Every hydration target owned by the subtree rooted at ``app``.

    Returns ``(binding_nodes, text_nodes, component_nodes)``:
    * ``binding_nodes`` — every marked-for-hydration node across the app's
      recursive bindings (incl. loop item wrappers / loop-body bindings);
    * ``text_nodes`` — every ``TextBinding`` node plus loop-body text binding
      nodes (exposed for ordinal stamping);
    * ``component_nodes`` — the root element of ``app`` plus every recursively
      mounted child component's root (custom-element loop children included).
    """
    binding_nodes = []
    text_nodes = []
    for b in app.get_bindings(recursive=True):
        binding_nodes.extend(b.marked_for_hydration())
        if type(b).__name__ == "TextBinding":
            text_nodes.append(b.node)
        elif type(b).__name__ == "LoopBinding":
            # Loop body TextBindings live in LoopItem.bindings (not reachable
            # via get_bindings recursion) — expose them for ordinal stamping.
            text_nodes.extend(b.text_binding_nodes())
    component_nodes = [app.__element__]
    component_nodes.extend(
        cb.childinstance.__element__
        for cb in app.get_child_bindings(recursive=True)
    )
    return binding_nodes, text_nodes, component_nodes


def apply_hydration_to_page(page, body_app=None):
    """Stamp the whole-document hydration surface over the Page's OWN regions —
    ``<head>`` (``h:``) and ``<body>`` (``b:``) — in one coordinated pass.

    The Page is the whole-``<html>`` document shell. Under whole-page hydration
    BOTH regions are Page-owned:

    * the **``<head>`` region** (prefix ``h:``) covers the Page's head bindings
      — ``<title>{title}``, the viewport / ``basis-render-mode`` meta, the
      initial-state script, the in-tree component-style loop;
    * the **``<body>`` region** (prefix ``b:``) roots at the ``<body>`` element
      and covers the Page's body bindings AND the mounted app subtree, so the
      whole document hydrates against ONE map (``h:`` + ``b:``).

    ``body_app`` is the declaratively-mounted root app (when the page has one);
    its subtree's binding targets / component roots join the ``b:`` walk. When
    it is ``None`` (static page), only the head region is stamped.

    ``page`` is the mounted ``Page`` instance (``__element__`` = the ``<html>``
    root). Returns the marker report (path -> flags) for diagnostics.
    """
    html_root = page.__element__
    head_node = None
    body_node = None
    for child in html_root.children:
        tag = getattr(child, "tagName", "").lower()
        if tag == "head":
            head_node = child
        elif tag == "body":
            body_node = child
    report = {}

    # Page-owned binding nodes + text nodes (head AND body bindings). Passing
    # every node to each region's membership set is safe: a region's walk only
    # stamps the nodes it actually visits, so a body node never leaks into the
    # ``h:`` report (and vice-versa).
    page_binding_nodes = []
    page_text_nodes = []
    for b in getattr(page, "__bindings__", ()):
        page_binding_nodes.extend(b.marked_for_hydration() or ())
        if type(b).__name__ == "TextBinding":
            page_text_nodes.append(b.node)

    # ── HEAD region (h:) ────────────────────────────────────────────────────
    if head_node is not None:
        # Stamp <head> itself as the h: region root so a head LoopBinding (the
        # component_style_items loop) can re-point its parent — <head>
        # belongs to no component, so it would never otherwise be stamped.
        head_node.setAttribute(HYDRATION_ID_ATTR, "h:0")
        report.update(
            apply_hydration_markers(head_node, page_binding_nodes, [], prefix="h")
        )
        stamp_text_ordinals(head_node, page_text_nodes)

    # ── BODY region (b:) ────────────────────────────────────────────────────
    if body_node is not None:
        body_binding_nodes = list(page_binding_nodes)
        body_text_nodes = list(page_text_nodes)
        body_component_nodes = []
        if body_app is not None:
            app_bindings, app_texts, app_components = _collect_component_hydration(
                body_app
            )
            body_binding_nodes.extend(app_bindings)
            body_text_nodes.extend(app_texts)
            body_component_nodes = app_components
        # Stamp <body> itself as the b: region root (b:0) so a Page body
        # LoopBinding (e.g. a user-stylesheet <link> loop) can re-point its
        # parent — <body> belongs to no component, mirroring the h:0 rule.
        body_node.setAttribute(HYDRATION_ID_ATTR, "b:0")
        report.update(
            apply_hydration_markers(
                body_node, body_binding_nodes, body_component_nodes, prefix="b"
            )
        )
        stamp_text_ordinals(body_node, body_text_nodes)
    return report


# ---------------------------------------------------------------------------
# Hydration diagnostics
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

    def __init__(self, mode="canonical"):
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
