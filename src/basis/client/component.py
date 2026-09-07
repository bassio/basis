from dataclasses import dataclass
from functools import wraps

try:
    from pyscript import window, document, ffi, fetch

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False

from basis.shared.bindings import (
    ChildBinding,
    EventBinding,
    IfBinding,
    LoopBinding,
    SelfBinding,
    TextBinding,
)

from basis.shared.base_component import BaseComponent
from basis.shared.hydration import (
    HYDRATION_ID_ATTR,
    HYDRATION_MISMATCH_EVENT,
    HYDRATION_REPORT_GLOBAL,
    TEXT_ORDINALS_ATTR,
    HydrationReport,
    build_hydration_map,
    hydration_fallback_enabled,
    is_element,
    iter_tree_paths,
    text_ordinal,
)

def client(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if PYSCRIPT:
            return func(*args, **kwargs)

    return wrapper


def _shadow_contains(shadow_root, element):
    """True if ``element`` is still attached inside the detached shadow root.
    A component hidden by an if-binding has had its node removed, so it is not
    contained — this distinguishes "legitimately hidden" from a genuine
    hydration mismatch."""
    try:
        return element is not None and shadow_root.contains(element)
    except Exception:
        return False


def _connected_to_tree_root(node):
    """True if ``node``'s ancestor chain reaches the mounted (staged) tree's
    document/fragment root — i.e. it is genuinely part of the tree, not stranded
    inside a removed (if-hidden) branch.

    An if-hide removes only the TOP of the hidden subtree, so descendants keep
    their intra-subtree ``parentNode`` links even though the whole branch is
    detached — a one-level ``parentNode`` check would wrongly call that
    connected.  Walk the full ancestor chain: the node is connected iff it
    reaches a document/fragment root (the mounted tree's top); if it dead-ends
    on a stranded element, the branch was removed (an if-hidden subtree that
    also never got stamped).  Pyodide hands back JsNull proxies (not None) for
    absent parents — rely on ``nodeType`` membership, not ``is not None``."""
    try:
        n = node
        while n is not None:
            parent = getattr(n, "parentNode", None)
            if not parent:
                # Top of the chain: connected iff it is a document (9) or
                # document-fragment (11) root — not a stranded element (1).
                return getattr(n, "nodeType", None) in (9, 11)
            n = parent
        return False
    except Exception:
        return False


def _emit_hydration_report(report):
    """Surface a hydration report: global for tooling, a DOM event, and a loud
    dev warning when anything failed to match."""
    try:
        data = ffi.to_js(report.to_dict())
        setattr(window, HYDRATION_REPORT_GLOBAL, data)
        # Mirror as a JSON data-attribute for easy tooling/inspection.
        document.documentElement.setAttribute(
            "data-" + HYDRATION_REPORT_GLOBAL, report.to_json()
        )
    except Exception:
        pass

    if report.is_clean:
        return

    try:
        detail = ffi.to_js(report.to_dict())
        event = window.CustomEvent.new(
            HYDRATION_MISMATCH_EVENT, {"detail": detail, "bubbles": True}
        )
        document.dispatchEvent(event)
    except Exception:
        pass

    try:
        n_unhydrated = len(report.unhydrated_components)
        n_bindings = len(report.unmatched_bindings)
        window.console.warn(
            f"[basis] hydration mismatch: {n_unhydrated} unhydrated component(s), "
            f"{n_bindings} unmatched binding(s) — see window.__basisHydrationReport"
        )
        if report.unmatched_bindings:
            window.console.table(ffi.to_js(report.unmatched_bindings))
    except Exception:
        pass


def _build_html_document_blueprint(cls):
    """Build the client Page blueprint: a ``<template>`` whose content is a
    single ``<html>`` element containing ``<head>`` + ``<body>``.

    A browser ``<template>.innerHTML`` parse runs in *fragment* mode and DROPS
    the document-level ``<html>/<head>/<body>`` wrappers (flattening the head
    and body children into one list), so a Page's whole-document template
    cannot be staged through the generic blueprint path. Parse the whole
    document with a structure-preserving parser instead: ``DOMParser`` keeps
    ``<html>/<head>/<body>`` intact and parses each region's inner content the
    same way the server's parser did (whitespace, comments and raw-text
    entities preserved), which is what keeps the two-region (``h:`` head /
    ``r:`` body-app) canonical paths stable across server and client.

    An ``XMLSerializer`` round-trip is deliberately NOT used to rebuild the
    document: serializing the parsed content would add ``xmlns=`` noise on
    every element and double-encode entities inside raw-text (``<script>`` /
    ``<style>``) bodies — corrupting e.g. the ``initial_state_json`` script.
    """
    template = document.createElement("template")
    parser = window.DOMParser.new()
    parsed = parser.parseFromString(cls.__templatestr__, "text/html")
    html_el = parsed.documentElement
    if html_el is not None:
        # Move the parsed <html> into the template content (blueprint
        # convention: __blueprint__ is a <template> whose
        # .content.firstElementChild is the component root).
        template.content.appendChild(html_el)
    return template


def _head_region(html_el):
    """The ``<head>`` element of a client-side ``<html>`` node (first HEAD
    element child), or None."""
    for child in getattr(html_el, "children", ()):
        if getattr(child, "nodeName", "").lower() == "head":
            return child
    return None


def _body_region(html_el):
    """The ``<body>`` element of a client-side ``<html>`` node (first BODY
    element child), or None."""
    for child in getattr(html_el, "children", ()):
        if getattr(child, "nodeName", "").lower() == "body":
            return child
    return None


def _stamp_region_ids(root, prefix):
    """Stamp ``data-hydration-id`` on EVERY countable element under ``root``
    with a region prefix (e.g. ``h:`` over a staged ``<head>``).

    This is a FULL stamp (all elements), NOT a binding-membership stamp:
    Pyodide hands back a distinct JsProxy wrapper per DOM access, so
    ``id()``-based membership sets can never match the walk's wrappers against
    a binding's stored node references. Full-stamp + canonical-path matching
    (client template node at path P hydrates the SSR node at path P) is exactly
    how the body region works.
    """
    for node, path in iter_tree_paths(root, prefix=prefix):
        if is_element(node):
            node.setAttribute(HYDRATION_ID_ATTR, path)


def _stamp_live_region_text_ordinals(staged_page, live_map):
    """Stamp ``data-hydration-text`` on the LIVE parents of the Page's text
    bindings (CSR whole-shell adoption).

    The served CSR document is STATIC — the server never stamps it — but the
    ``TextBinding`` re-pointer locates a bound text node by reading the *live*
    parent's ``data-hydration-text`` ordinals. The staged page is a faithful
    client-built clone of the same template with BOTH regions stamped (``h:``
    head + ``b:`` body), so for each Page ``TextBinding`` we take its staged
    parent's canonical path, resolve the matching live parent in ``live_map``,
    and stamp the text's normalized ordinal there — reproducing, client-side,
    the ordinal the SSR server stamps for whichever region the binding lives in.
    """
    for b in getattr(staged_page, "__bindings__", ()):
        if type(b).__name__ != "TextBinding":
            continue
        try:
            node = b.node
            staged_parent = getattr(node, "parentNode", None)
            if staged_parent is None:
                continue
            path = staged_parent.getAttribute(HYDRATION_ID_ATTR)
            live_parent = live_map.get(path) if path else None
            if live_parent is None:
                continue
            ordinal = text_ordinal(staged_parent, node)
            if ordinal is None:
                continue
            ords = set()
            if live_parent.hasAttribute(TEXT_ORDINALS_ATTR):
                existing = live_parent.getAttribute(TEXT_ORDINALS_ATTR)
                if getattr(existing, "split", None) is not None:
                    for part in str(existing).split(","):
                        part = part.strip()
                        if part:
                            try:
                                ords.add(int(part))
                            except ValueError:
                                pass
            ords.add(ordinal)
            live_parent.setAttribute(
                TEXT_ORDINALS_ATTR, ",".join(str(o) for o in sorted(ords))
            )
        except Exception:
            continue


def _hydrate_page_head(page_cls, report=None, *, stamp_live=True):
    """Stage the Page's ``<head>`` region and re-point its head bindings at the
    LIVE ``document.head`` (HYDRATION-WHOLEPAGE.md §4.1 P2 shared head pass).

    Used by the CSR boot (``Page.mount_document_csr``): the served CSR head is
    STATIC (the server never stamps it), so:

    1. Mount the Page detached in a ``DocumentFragment`` (a browser
       ``<template>.innerHTML`` parse drops the ``<html>/<head>/<body>``
       wrappers, so the client blueprint keeps them via DOMParser) and FULL-stamp
       its staged ``<head>`` with the ``h:`` region prefix.
    2. Stamp the LIVE ``<head>`` the way SSR would have — every element's
       canonical ``h:`` path (``_stamp_region_ids``) plus ``data-hydration-text`` on
       the parents of the Page's head text bindings
       (``_stamp_live_region_text_ordinals``).
    3. Re-point the staged Page's head bindings at the live ``document.head``
       via the canonical ``h:`` map. Re-point never writes → no FOUC / no
       double head; values the server resolved (expanded pyscript URLs, the
       serialized initial-state script) survive untouched, but the title/meta
       bindings become live.

    Returns the staged Page instance (its head bindings re-pointed at the live
    ``<head>``), or ``None`` if mounting failed.
    """
    from basis.shared.hydration import HydrationReport, build_hydration_map

    report = report if report is not None else HydrationReport(mode="canonical")
    staged_page = None
    try:
        fragment = document.createDocumentFragment()
        staged_page = page_cls.mount(fragment, replace=False)
        staged_head = _head_region(staged_page.__element__)
        if staged_head is not None:
            _stamp_region_ids(staged_head, "h")
        if stamp_live:
            _stamp_region_ids(document.head, "h")
        head_map = build_hydration_map(document.head, prefix="h")
        if stamp_live:
            _stamp_live_region_text_ordinals(staged_page, head_map)
        staged_page.initialize_ssr(
            document.documentElement, report=report, ssr_map=head_map
        )
        # Pin the staged Page instance to the LIVE <html> root so it (and its
        # re-pointed head bindings) is not collected: Pyodide keeps a Python
        # object alive while a JsProxy reference to it exists. This mirrors how
        # the body pipeline pins component instances (``__basis_instance__`` on
        # their live nodes via ChildBinding); without it the Page — whose
        # selfbinding node is the live <html> — would be GC'd after the staged
        # reference drops and its head bindings would go dead. Dev tooling can
        # also reach the live page here (``document.documentElement.__basis_instance__``).
        try:
            setattr(document.documentElement, "__basis_instance__", staged_page)
        except Exception:
            pass
    except Exception as exc:
        report.add_unhydrated_component(
            page_cls.__name__,
            client_id="head",
            reason=f"page head hydration raised: {exc}",
        )
    return staged_page


def _hydrate_page_document_ssr(page_cls):
    """Whole-page SSR hydration driver (HYDRATION-WHOLEPAGE.md §4.1 P4/P5).

    ONE staged owned document: mount the whole ``Page`` (``<html>`` with
    ``<head>`` and ``<body>``) detached, mount the root component as a nested
    child of the staged ``<body>`` (``Page.mount_root_app`` — a declarative
    ``ChildBinding`` under its host tag, exactly as the server served it),
    FULL-stamp the staged ``<head>`` (``h:``) and ``<body>`` (``b:``) regions,
    then adopt every owner — the ``Page`` itself (its head AND body bindings)
    plus each app component — against ONE live map built from ``document.head``
    (``h:``) and ``document.body`` (``b:``). Nothing is ever inserted into the
    live document: the SSR tree is adopted in place, and the single report is
    surfaced once at the end.

    Every page boot path (real ``Page`` subclasses AND synthesized ``@app.page``
    shells) hydrates through here — the separate app-rooted ``r:`` body
    pipeline is gone (§4.1 P5, migrate-always: ``r:`` → ``b:``).
    """
    from basis.shared.hydration import HydrationReport, build_hydration_map
    from basis.shared.component import _set_ssr_hydration

    report = HydrationReport(mode="canonical")
    staged_page = None
    try:
        # Stage the whole Page (a browser <template>.innerHTML parse drops the
        # <html>/<head>/<body> wrappers, so the client blueprint keeps them via
        # DOMParser — _build_html_document_blueprint).
        fragment = document.createDocumentFragment()
        staged_page = page_cls.mount(fragment, replace=False)
        staged_html = staged_page.__element__
        staged_head = _head_region(staged_html)
        staged_body = _body_region(staged_html)

        # SSR-hydration phase: dynamic mounters (e.g. <ui-region>) defer their
        # real work until on_hydrated() (fired by initialize_ssr) re-points them
        # at the live SSR tree.
        _set_ssr_hydration(True)
        try:
            root_component = getattr(page_cls, "root_component", None)
            mounted_app = None
            instances = []
            if root_component is not None and staged_body is not None:
                # Mount the app as a NESTED child of the staged <body> so the
                # whole document is ONE owned tree — head h: + body b: incl.
                # the app subtree. Component styles live in-tree in the served
                # <head>, so nothing is re-injected.
                #
                # §4.1 S1/S3 declarative root mount: the Page owns its root as
                # a nested ChildBinding under a hyphenated host tag (declared or
                # kebab-derived) — every page root mounts this way, the exact
                # shape the server serves. The legacy imperative staged
                # mount_app path is gone (§4.1 P5).
                mounted_app = staged_page.mount_root_app()
                instances = [mounted_app]
                instances.extend(
                    cb.childinstance
                    for cb in mounted_app.get_child_bindings(recursive=True)
                )

            # Full-stamp the staged regions with the canonical algorithm the
            # server used for the live document (one address scheme).
            if staged_head is not None:
                _stamp_region_ids(staged_head, "h")
            if staged_body is not None:
                _stamp_region_ids(staged_body, "b")

            # ONE live document map: head h: + body b: (server-stamped).
            live_map = {}
            live_map.update(build_hydration_map(document.head, prefix="h"))
            live_map.update(build_hydration_map(document.body, prefix="b"))

            # Adopt the Page's own bindings (head h: + body b:) at the live
            # <html>, then every app component against the same map.
            staged_page.initialize_ssr(
                document.documentElement, report=report, ssr_map=live_map
            )
            if instances:
                _adopt_instances(
                    instances,
                    live_map,
                    document.body,
                    staged_body if staged_body is not None else fragment,
                    report,
                )
                # Pin the app root to its live node (mirrors ChildBinding):
                # keep the instance (and its re-pointed bindings) alive across
                # Pyodide GC, and let dev tooling reach it.
                try:
                    live_root = live_map.get(mounted_app.hydration_id)
                    if live_root is not None:
                        setattr(live_root, "__basis_instance__", mounted_app)
                except Exception:
                    pass
        finally:
            _set_ssr_hydration(False)

        # Pin the staged Page (its selfbinding node is the live <html>) so it
        # and its re-pointed bindings are not collected; dev tooling can reach
        # the live page at document.documentElement.__basis_instance__.
        try:
            setattr(document.documentElement, "__basis_instance__", staged_page)
        except Exception:
            pass
    except Exception as exc:
        report.add_unhydrated_component(
            page_cls.__name__,
            client_id="page",
            reason=f"whole-page hydration raised: {exc}",
        )
    _emit_hydration_report(report)
    return staged_page


def _adopt_instances(instances, live_map, ssr_root, staging_root, report):
    """Adopt staged component instances onto their live SSR nodes.

    Repoints every instance's bindings at its live SSR node via the canonical
    ``live_map``, inside a flush batch (no effect drains mid-re-point onto a
    partially-adopted tree — HYDRATION-REPOINT-RACE-FIX-PLAN.md §5 I7). The
    pre-hydration snapshot lets a fallback re-render rebind the moved staged
    tree (otherwise events/reactivity dangle at detached nodes).

    ``staging_root`` is the detached container that holds the mounted app (a
    bare shadow root for the standalone ``r:`` pipeline, or the staged Page
    ``<body>`` for whole-document ``b:`` hydration); ``ssr_root`` is the live
    container the app lives in (the fallback's target).
    """
    fallback_needed = False
    fallback_snapshot = []
    for child_instance in instances:
        try:
            shadow_element = child_instance.__element__
            bindings = []
            for b in child_instance.__bindings__:
                bindings.append(
                    (
                        b,
                        getattr(b, "node", None),
                        getattr(b, "anchor", None),
                        getattr(b, "parent", None),
                    )
                )
            fallback_snapshot.append((child_instance, shadow_element, bindings))
        except Exception:
            fallback_snapshot.append((child_instance, None, []))

    from basis.shared.reactive import batch

    with batch() as hyd_batch:
        for child_instance in instances:
            hid = child_instance.hydration_id
            if hid and hid in live_map:
                corresponding_ssr_root_node = live_map[hid]
                try:
                    child_instance.initialize_ssr(
                        corresponding_ssr_root_node,
                        report=report,
                        ssr_map=live_map,
                    )
                except Exception as exc:
                    # One broken component must not abort the whole report.
                    report.add_unhydrated_component(
                        child_instance.__class__.__name__,
                        client_id=hid,
                        reason=f"initialize_ssr raised: {exc}",
                    )
            else:
                # Component root not present in the live tree. Normal when it is
                # hidden by an if-binding on the server (its staged node is then
                # detached); otherwise it is a genuine mismatch.
                if hid is not None:
                    hidden = not _shadow_contains(
                        staging_root, child_instance.__element__
                    )
                    report.add_unhydrated_component(
                        child_instance.__class__.__name__,
                        client_id=hid,
                        reason=(
                            "hidden by if-binding"
                            if hidden
                            else "component not present in SSR tree"
                        ),
                    )
                    if not hidden:
                        fallback_needed = True
        if fallback_needed:
            # Re-point-phase work must not reach the live SSR nodes — the staged
            # tree is about to replace them.
            hyd_batch.discard()

    if fallback_needed and hydration_fallback_enabled():
        _fallback_rerender(ssr_root, staging_root, report, snapshot=fallback_snapshot)
    return fallback_needed


def _fallback_rerender(ssr_root, shadow, report, snapshot=None):
    """Whole-app client re-render fallback: replace the SSR content with the
    already-mounted client app, so the page stays reactive even when hydration
    could not match.

    EVERY child of the detached staging tree is moved into the live SSR root —
    not just the app element — so the whole staged subtree (component styles
    render in-tree in the Page head, so a whole-document fallback keeps the
    staged app and its owned nodes together).

    ``snapshot`` (optional) holds, for every component instance, its
    pre-hydration shadow element and the shadow node each binding pointed at.
    ``initialize_ssr`` repoints all bindings/``__element__`` at SSR nodes; once
    those SSR nodes are discarded by ``replaceChildren`` the moved shadow app
    would be left pointing at detached nodes (dead events / dead reactivity).
    So on fallback we restore every binding and the instance element to the
    shadow nodes that now live in the DOM.
    """
    try:
        if ssr_root is None:
            return
        children = list(shadow.childNodes)
        if not children:
            return

        # The app is a DIRECT child of <body> (no #basis-ssr-root wrapper,
        # HYDRATION-WHOLEPAGE.md No.1), so we must NOT replaceChildren(body):
        # that would wipe non-app body siblings — e.g. the user stylesheet
        # <link>s Page.render() appends at the END of <body>. Remove only the
        # app-owned nodes (injected component <style>s + the marked component
        # roots), move the shadow app in, then re-append the non-app siblings
        # AFTER it so the user stylesheet still loads last (the "your CSS comes
        # later" cascade contract).
        def _is_app_owned(node):
            if getattr(node, "nodeType", None) != 1:  # element only
                return False
            if node.hasAttribute("data-component-class"):
                return True
            return (
                node.hasAttribute("data-hydration-id")
                or node.hasAttribute("data-component-hydration-id")
                or node.hasAttribute("data-hydration-text")
            )

        owned, non_owned = [], []
        for child in list(ssr_root.childNodes):
            (owned if _is_app_owned(child) else non_owned).append(child)
        for child in owned:
            ssr_root.removeChild(child)
        for child in children:
            ssr_root.appendChild(child)
        for child in non_owned:
            ssr_root.appendChild(child)

        if snapshot:
            for instance, shadow_element, bindings in snapshot:
                try:
                    instance.set_selfbinding(shadow_element)
                except Exception:
                    pass
                for binding, node, anchor, parent in bindings:
                    try:
                        if node is not None and hasattr(binding, "node"):
                            binding.node = node
                        if anchor is not None and hasattr(binding, "anchor"):
                            binding.anchor = anchor
                        if parent is not None and hasattr(binding, "parent"):
                            binding.parent = parent
                    except Exception:
                        pass

        report.set_fallback("whole-app client re-render")
    except Exception as exc:
        report.set_fallback(f"fallback re-render failed: {exc}")


class Component(BaseComponent):

    @classmethod
    def _initialize_blueprint(cls):
        ###Client
        init_template = cls._create_element('template')
        init_template.innerHTML = cls.__templatestr__
        setattr(cls, "__blueprint__", init_template)
    
    @classmethod
    def _analyze_template(cls):

        cloned_blueprint = cls.clone_blueprint()
        cloned_content = cloned_blueprint.content
        
        # Reuse _get_nodes for consistent indexing
        nodes = cls._get_nodes(cloned_content)
        
        for node_index, node in enumerate(nodes):
            blueprints = cls._analyze_node(node, node_index)
            if blueprints:
                cls.__binding_blueprints__.extend(blueprints)
    
    @classmethod
    @client
    def clone_blueprint(cls):
        cloned = document.importNode(cls.__blueprint__, True)
        return cloned
    
    @property
    @client
    def __template__(self):
        if '_template' not in self.__dict__:
            cloned_blueprint = self.__class__.clone_blueprint()
            cloned_content = cloned_blueprint.content
            self.__dict__['_template'] = cloned_content
        return self.__dict__['_template']

    @classmethod
    def _register_custom_element(cls):
        """Register the class as a custom element (once), or refresh its config on HMR re-imports."""
        if "-" not in cls.__tag__:
            return

        config = ffi.to_js({
            '__templatestr__': cls.__templatestr__,
            'pyClassName': cls.__name__,
            'pyTag': cls.__tag__,
            '__shadow__': getattr(cls, '__shadow__', False),
        })

        existing = window.customElements.get(cls.__tag__)
        if existing is None:
            custom_element = window.CustomElementFactory(config)
            window.customElements.define(cls.__tag__, custom_element)
            setattr(cls, 'custom_element', custom_element)
        else:
            # Already defined — most likely an HMR re-import of the same module.
            # Keep the existing JS class (custom elements can't be redefined) but
            # refresh its config so NEW instances render the updated template.
            setattr(cls, 'custom_element', existing)
            try:
                existing.config = config
                window.__basisElementConfigs[cls.__tag__] = config
            except Exception:
                pass

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        #client
        cls._register_custom_element()

    def __init__(self):
        super().__init__()


    @classmethod
    def _get_nodes_all(cls, element):

        walker = document.createTreeWalker(element, window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT | window.NodeFilter.SHOW_COMMENT)

        nodes = []
        current_node = walker.nextNode()
        while current_node:
            nodes.append(current_node)
            current_node = walker.nextNode()

        return nodes

    @classmethod
    def _get_nodes_skip_loops(cls, element):

        walker = document.createTreeWalker(element, window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT | window.NodeFilter.SHOW_COMMENT)

        nodes = []
        current_node = walker.nextNode()
        while current_node:
            nodes.append(current_node)

            is_loop = False
            if current_node.nodeType == 1:  # Element node
                try:
                    if current_node.hasAttribute('for') and current_node.hasAttribute('in'):
                        is_loop = True
                except:
                    pass

            if is_loop:
                next_node = walker.nextSibling()
                while not next_node:
                    parent = walker.parentNode()
                    if not parent or parent == element:
                        next_node = None
                        break
                    next_node = walker.nextSibling()
                current_node = next_node
            else:
                current_node = walker.nextNode()

        return nodes

    @classmethod
    def _get_nodes(cls, element, skip_loop_descendants=True):
        if skip_loop_descendants:
            return cls._get_nodes_skip_loops(element)
        return cls._get_nodes_all(element)

    @client
    def _create_comment(self, comment_text):
        return document.createComment(comment_text)
    
    @client
    def _create_document_fragment(self):
        return document.createDocumentFragment()

    @classmethod
    def _create_element(cls, tag):
        return document.createElement(tag)

    @client
    def _create_function_proxy(self, f):
        if not getattr(f, "__is_py_event__", False):
            from basis.shared.component import py_event
            f = py_event(f)
        return ffi.create_proxy(f)

    @client   
    def _create_update_handler(self, f, input_type):
        handler = super()._create_update_handler(f, input_type)
        return self._create_function_proxy(handler)

    def initialize_ssr(self, ssr_root, report=None, *, ssr_map=None, **kwargs):
        """Hydrate this component instance against the live SSR tree.

        The client stamps ``data-hydration-id`` on its own template tree with
        the SAME canonical-path algorithm the server uses
        (``shared/hydration.iter_tree_paths``), so hydration is one sentence:
        *client template node at canonical path P hydrates the SSR node at
        canonical path P.*

        Every owner binding is re-pointed in a single pass
        (``_repoint_binding``); bindings that own a DOM listener are
        re-attached in a second pass (``attach`` — shared code cannot create
        JS proxies).  Loop bodies and nested loops are re-pointed structurally
        by ``LoopBinding.repoint_to_ssr`` (data-item-key + relative canonical
        paths), which also handles custom-element loop children (component
        roots hydrated by their own ``initialize_ssr`` via ChildBinding).
        """
        self.set_selfbinding(ssr_root)

        # SSR path -> node lookup, built once.  Whole-document hydration passes
        # a whole-document map (head h: + body b:); fall back to the
        # component's own subtree otherwise.
        if ssr_map is None:
            ssr_map = build_hydration_map(ssr_root)

        report = report if report is not None else HydrationReport()
        repointed_attachments = []

        for binding in list(self.__bindings__):
            if isinstance(binding, SelfBinding):
                # SelfBinding's node is the component root — already pointed at
                # the SSR root by set_selfbinding(); nothing to re-point.
                continue
            self._repoint_binding(binding, ssr_map, report, repointed_attachments)

        # Re-attach listener-owning bindings (EventBinding, ModelBinding,
        # FormModelBinding, ...) to their live SSR nodes.
        for rb in repointed_attachments:
            attach = getattr(rb, "attach", None)
            if attach is not None:
                attach(rb.node)
                try:
                    rb.node.setAttribute("data-hydrated", "true")
                except Exception:
                    pass

        with self.refrain() as refrained:
            for k, v in kwargs.items():
                setattr(refrained, k, v)

        # Post-hydration hook: bindings now point at the live SSR nodes, so the
        # component can do imperative setup against the real DOM (e.g. the
        # region primitive re-mounting its contributions).
        self.on_hydrated()

    def _repoint_binding(self, binding, ssr_map, report, repointed_attachments):
        """Re-point one owner binding to its live SSR node.

        The binding's addressable nodes (``node`` / ``parent`` / ``anchor``)
        carry the client-stamped ``data-hydration-id``; the SSR lookup map is
        keyed by the SAME canonical paths, so a matched path IS the live node.
        Bindings that own a DOM listener are appended to
        ``repointed_attachments`` for the trailing re-attach pass.
        """
        name = self.__class__.__name__

        if isinstance(binding, IfBinding):
            # The if-node may be legitimately absent from BOTH trees when hidden
            # by its condition — that is not a mismatch.
            path = binding.node.getAttribute(HYDRATION_ID_ATTR)
            matched = ssr_map.get(path) if path else None
            if matched:
                binding.node = matched
                binding.is_visible = True
            else:
                binding.is_visible = False
                if report is not None and path:
                    report.add_unmatched_binding(
                        name, "IfBinding",
                        client_id=path, expected_ssr_id=path,
                        reason="if-node not found in SSR tree (hidden on server?)",
                    )
            anchor_path = binding.anchor.getAttribute(HYDRATION_ID_ATTR)
            matched_anchor = ssr_map.get(anchor_path) if anchor_path else None
            if matched_anchor:
                binding.anchor = matched_anchor
            return

        if isinstance(binding, TextBinding):
            parent_path = binding.node.parentNode.getAttribute(HYDRATION_ID_ATTR)
            matched_parent = ssr_map.get(parent_path) if parent_path else None

            matched_text = False
            own = None
            ssr_ordinals = None
            if matched_parent:
                # The SSR parent carries a deterministic text-ordinal marker
                # (data-hydration-text) computed over *normalized* children, so
                # whitespace/comment nodes can never shift it.
                ssr_ordinals = matched_parent.getAttribute(TEXT_ORDINALS_ATTR)
                # In Pyodide, getAttribute returns a JsNull proxy (not Python
                # None) when the attribute is absent — check capability, not
                # ``is not None``.
                if getattr(ssr_ordinals, "split", None) is not None:
                    own = text_ordinal(binding.node.parentNode, binding.node)
                    if own is not None:
                        # Count children the same way the server stamped the
                        # ordinals: elements + non-ws text + reactive text nodes
                        # (even if currently empty, per data-hydration-text).
                        binding_ordinals = {
                            int(x) for x in ssr_ordinals.split(",") if x.strip()
                        }
                        counter = 0
                        for child in matched_parent.childNodes:
                            if child.nodeType == 1:  # element
                                counter += 1
                            elif child.nodeType == 3:  # text
                                is_binding = counter in binding_ordinals
                                is_ws = not (child.textContent or "").strip()
                                if is_binding or not is_ws:
                                    if counter == own:
                                        binding.node = child
                                        matched_text = True
                                        break
                                    counter += 1

            # A null/absent parent path means the text node sits inside an
            # if-node hidden by its condition (removed from the shadow) — it is
            # legitimately absent from the SSR tree, not a mismatch.
            if report is not None and parent_path and not matched_text:
                report.add_unmatched_binding(
                    name, "TextBinding",
                    client_id=parent_path, expected_ssr_id=parent_path,
                    reason=(
                        f"text node not matched (parent_found={matched_parent is not None}, "
                        f"basis_text={ssr_ordinals!r}, own={own!r})"
                    ),
                )
            return

        if isinstance(binding, LoopBinding):
            parent_path = None
            try:
                parent_path = binding.parent.getAttribute(HYDRATION_ID_ATTR)
            except Exception:
                parent_path = None
            ssr_parent = ssr_map.get(parent_path) if parent_path else None
            if ssr_parent is None:
                # A loop's parent missing from the SSR tree is either a DORMANT
                # loop (its branch was if-hidden on the client BEFORE the staged
                # region was full-stamped, so the server omitted that branch too)
                # or a genuine mismatch.  Distinguish them by where the parent is
                # on the CLIENT's OWN tree:
                #   * carries a hydration path  -> visible on the client yet
                #     absent from the SSR tree  -> genuine mismatch (report).
                #   * connected to the staged tree root but NO path -> present
                #     yet unstamped.  The client full-stamps every staged
                #     element (``_stamp_region_ids``), so this only happens if
                #     stamping regressed or the node was added after the stamp —
                #     surface it rather than swallow it as "hidden".
                #   * detached from the staged tree root (no path) -> the client
                #     removed the branch (an if-hide); dormant until its branch
                #     reveals -> not a mismatch (skip — mirrors IfBinding /
                #     TextBinding skipping unstamped hidden targets).  Note
                #     "detached" must mean NOT connected to the tree root: an
                #     if-hide removes only the top of the subtree, so the loop's
                #     container can still have a ``parentNode`` inside the
                #     removed branch.
                if (
                    report is not None
                    and binding.instances
                    and (parent_path or _connected_to_tree_root(binding.parent))
                ):
                    report.add_unmatched_binding(
                        name, "LoopBinding",
                        client_id=parent_path or "?",
                        expected_ssr_id=parent_path or "?",
                        reason="loop parent not found in SSR tree",
                    )
                return
            # Structural re-point: item wrappers by data-item-key, body bindings
            # by relative canonical path, recursing into nested loops.
            # Custom-element children keep their ChildBinding/instance on the
            # live wrapper here (their own initialize_ssr hydrates the subtree).
            repointed_attachments.extend(binding.repoint_to_ssr(ssr_parent, report))
            return

        if isinstance(binding, ChildBinding):
            if binding.loop_binding:
                # Custom-element loop children are re-pointed by the owning
                # LoopBinding.repoint_to_ssr — nothing to do here.
                return
            path = binding.node.getAttribute(HYDRATION_ID_ATTR)
            matched = ssr_map.get(path) if path else None
            if matched:
                binding.node = matched
                # Attach the component instance so parent AttributeBindings can
                # sync props to the live node.
                setattr(matched, '__basis_instance__', binding.childinstance)
            elif report is not None and path:
                report.add_unmatched_binding(
                    name, "ChildBinding",
                    client_id=path, expected_ssr_id=path,
                    reason="child component root not found in SSR tree",
                )
            return

        # Generic: any other binding with a directly addressable node
        # (EventBinding, AttributeBinding, ModelBinding, ...).  SelfBinding is
        # excluded by the caller.
        path = binding.node.getAttribute(HYDRATION_ID_ATTR)
        matched = ssr_map.get(path) if path else None
        if matched:
            binding.node = matched
            if hasattr(binding, "attach"):
                repointed_attachments.append(binding)
        elif report is not None and path:
            report.add_unmatched_binding(
                name, type(binding).__name__,
                client_id=path, expected_ssr_id=path,
                reason="binding node not found in SSR tree",
            )

    @property
    def hydration_id(self):
        """The canonical hydration path of this component's root element
        (``data-hydration-id``, stamped on both the client template tree and
        the SSR tree with the same algorithm)."""
        try:
            hid = self.__element__.getAttribute(HYDRATION_ID_ATTR)
            return hid if hid else None
        except Exception:
            return None
