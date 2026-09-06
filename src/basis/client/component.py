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


def _fallback_rerender(ssr_root, shadow, report, snapshot=None):
    """Whole-app client re-render fallback: replace the SSR content with the
    already-mounted client app, so the page stays reactive even when hydration
    could not match.

    EVERY child of the detached shadow root is moved into the live SSR root —
    not just the app element — because ``mount_app`` *prepends* scoped
    ``<style>`` elements into the shadow root, and losing them would render the
    moved app unstyled.

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
        ssr_root.replaceChildren()
        for child in children:
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

        # SSR path -> node lookup, built once.  mount_app_ssr passes a whole-tree
        # map; fall back to the component's own subtree otherwise.
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
                # (data-basis-text) computed over *normalized* children, so
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
                        # (even if currently empty, per data-basis-text).
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
                if report is not None and binding.instances:
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

    @classmethod
    def mount_app_ssr(cls, ssr_root=None, replace=False):
        # Flag the SSR-hydration mount phase so dynamic mounters (e.g.
        # <ui-region>) defer their real work until ``initialize_ssr`` re-points
        # them at the live SSR tree (see shared/component.in_ssr_hydration).
        from basis.shared.component import _set_ssr_hydration
        _set_ssr_hydration(True)
        try:
            return cls._mount_app_ssr_impl(ssr_root, replace)
        finally:
            _set_ssr_hydration(False)

    @classmethod
    def _mount_app_ssr_impl(cls, ssr_root=None, replace=False):
        shadow_element_div = document.createElement("div")
        shadow = shadow_element_div.attachShadow({ 'mode': 'open' })

        mounted_app_component = cls.mount_app(shadow, replace)
        # Stamp the client's own template tree with canonical hydration ids —
        # ONE address scheme, shared with the SSR tree (same iter_tree_paths).
        mounted_app_component._stamp_hydration_ids(
            element=mounted_app_component.__element__)

        child_bindings_recursive = [cb for cb in mounted_app_component.get_child_bindings(recursive=True)]
        child_component_instances = [cb.childinstance for cb in child_bindings_recursive]

        root_plus_child_component_instances = [mounted_app_component, *child_component_instances]
        if not ssr_root:
            ssr_root = document.body

        marked_for_hydration = ssr_root.querySelectorAll("[data-hydration-id]")
        marked_for_hydration_dict = {}
        for x in marked_for_hydration:
            hid = x.getAttribute("data-hydration-id")
            if hid:
                marked_for_hydration_dict[hid] = x
        
        # ---- Diagnostics ----
        report = HydrationReport(mode="canonical")
        fallback_needed = False

        # Snapshot the client-side (shadow) nodes before initialize_ssr repoints
        # every binding/`__element__` at SSR nodes.  If hydration fails and the
        # fallback re-render fires, we restore these so the moved shadow app
        # stays bound to the DOM it actually lives in (otherwise events and
        # reactivity dangle at detached SSR nodes).
        fallback_snapshot = []
        for child_instance in root_plus_child_component_instances:
            try:
                shadow_element = child_instance.__element__
                bindings = []
                for b in child_instance.__bindings__:
                    node = getattr(b, "node", None)
                    anchor = getattr(b, "anchor", None)
                    parent = getattr(b, "parent", None)
                    bindings.append((b, node, anchor, parent))
                fallback_snapshot.append((child_instance, shadow_element, bindings))
            except Exception:
                fallback_snapshot.append((child_instance, None, []))

        # Repoint every component's bindings at its live SSR node. This runs
        # inside a flush batch (P4 — HYDRATION-REPOINT-RACE-FIX-PLAN.md §5, I7):
        # no effect can drain mid-re-point onto a partially-adopted tree with
        # un-converged state. The MOUNT above stays unbatched so the shadow tree
        # renders (and structural effects — regions, loops — run) exactly as
        # before; only the adoption phase is held.
        #
        # On a clean hydration the single batch-exit drain applies any
        # post-adoption work (e.g. hydrate-indicator flipping to "ready")
        # against the fully re-pointed tree, in deterministic parent-before-
        # child order, so values equal the SSR-rendered ones. On the fallback
        # path the batch is DISCARDED: the fully-rendered shadow tree is about
        # to replace the SSR content, so re-point-phase work must never write to
        # SSR nodes that will be discarded.
        from basis.shared.reactive import batch

        with batch() as hyd_batch:
            for child_instance in root_plus_child_component_instances:
                hid = child_instance.hydration_id
                if hid \
                and (hid in marked_for_hydration_dict):
                    corresponding_ssr_root_node = marked_for_hydration_dict[hid]
                    try:
                        child_instance.initialize_ssr(corresponding_ssr_root_node, report=report,
                                                      ssr_map=marked_for_hydration_dict)
                    except Exception as exc:
                        # One broken component must not abort the whole report.
                        report.add_unhydrated_component(
                            child_instance.__class__.__name__, client_id=hid,
                            reason=f"initialize_ssr raised: {exc}",
                        )
                else:
                    # Component root not present in the SSR tree.  Normal when it is
                    # hidden by an if-binding on the server (its shadow node is then
                    # detached); otherwise it is a genuine mismatch.
                    if hid is not None:
                        hidden = not _shadow_contains(shadow, child_instance.__element__)
                        report.add_unhydrated_component(
                            child_instance.__class__.__name__, client_id=hid,
                            reason="hidden by if-binding" if hidden
                            else "component not present in SSR tree",
                        )
                        if not hidden:
                            fallback_needed = True
            if fallback_needed:
                # Repoint-phase work must not reach the live SSR nodes — the
                # shadow tree is about to replace them.
                hyd_batch.discard()

        if fallback_needed and hydration_fallback_enabled():
            _fallback_rerender(ssr_root, shadow, report, snapshot=fallback_snapshot)

        _emit_hydration_report(report)
        
        return mounted_app_component
    
    @client
    def _stamp_hydration_ids(self, element=None):
        """Stamp ``data-hydration-id`` on every countable element of the client
        template tree.

        Uses the SAME canonical-path algorithm as the server
        (``shared/hydration.iter_tree_paths``, duck-typed for the browser DOM),
        so there is exactly ONE address scheme: the client template node at
        canonical path P hydrates the SSR node at canonical path P.
        """
        if element is None:
            element = self.__template__
        for node, path in iter_tree_paths(element):
            if is_element(node):
                node.setAttribute(HYDRATION_ID_ATTR, path)