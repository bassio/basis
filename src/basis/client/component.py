from dataclasses import dataclass
from functools import wraps

try:
    from pyscript import window, document, ffi, fetch

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False

from basis.shared.bindings import SelfBinding, ChildBinding, EventBinding, IfBinding, TextBinding, LoopBinding

from basis.shared.base_component import BaseComponent
from basis.shared.hydration import (
    HYDRATION_MISMATCH_EVENT,
    HYDRATION_REPORT_GLOBAL,
    HydrationReport,
    hydration_fallback_enabled,
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
    dev warning when anything failed to match (Phase E / Phase 5 #3)."""
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


def _fallback_rerender(ssr_root, shadow, report):
    """Whole-app client re-render fallback: replace the SSR content with the
    already-mounted client app, so the page stays reactive even when hydration
    could not match.

    EVERY child of the detached shadow root is moved into the live SSR root —
    not just the app element — because ``mount_app`` *prepends* scoped
    ``<style>`` elements into the shadow root, and losing them would render the
    moved app unstyled.
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

    def initialize_ssr(self, ssr_root, report=None, **kwargs):
        
        self.set_selfbinding(ssr_root)

        all_bindings = [b for b in self.__bindings__]
        event_bindings = [eb for eb in all_bindings if isinstance(eb, EventBinding)]
        if_bindings = [ib for ib in all_bindings if isinstance(ib, IfBinding)]
        text_bindings = [tb for tb in all_bindings if isinstance(tb, TextBinding)]
        loop_bindings = [lb for lb in all_bindings if isinstance(lb, LoopBinding)]
        child_bindings = [eb for eb in all_bindings if isinstance(eb, ChildBinding)]
        other_bindings = [ob for ob in all_bindings if ob not in event_bindings + if_bindings + text_bindings + loop_bindings + child_bindings]


        # print(f"DEBUG HYDRATION: initialize_ssr for {self.__class__.__name__}, bindings count: {len(all_bindings)}")
        for eb in event_bindings:
            
            eb_node_cid = eb.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{eb_node_cid}']")
            if matched_ssr_node:
                eb_node_new = matched_ssr_node
                # print(f"DEBUG HYDRATION: MATCHED event binding's {eb.event} ({eb.target_fn}) node: {eb_node_new.outerHTML}")
            elif ssr_root.getAttribute("data-hydration-id") == eb_node_cid:
                eb_node_new = ssr_root
                # print(f"DEBUG HYDRATION: MATCHED event binding root node's {eb.event} ({eb.target_fn})")
            else:
                eb_node_new = eb.node #just keep the old node then !
                # Null client-id -> node is inside a hidden if-node: legitimately
                # absent from the SSR tree, not a mismatch.
                if report is not None and eb_node_cid:
                    report.add_unmatched_binding(
                        self.__class__.__name__, "EventBinding",
                        client_id=eb_node_cid, expected_ssr_id=eb_node_cid,
                        reason="no matching data-hydration-id in SSR tree",
                    )

            eb.node = eb_node_new

            if isinstance(eb.target_fn, str):
                event_method = getattr(self, eb.target_fn)
                event_method_final = self._create_function_proxy(event_method)
                eb.node.removeAttribute(eb.event)
                if hasattr(eb.node, "addEventListener"):
                    eb.node.addEventListener(eb.event.removeprefix("on"), event_method_final)
                else:
                    setattr(eb.node, eb.event, event_method_final)
            else:
                self_event_method = eb.target_fn
                eb.node.removeAttribute(eb.event)
                if hasattr(eb.node, "addEventListener"):
                    eb.node.addEventListener(eb.event.removeprefix("on"), self_event_method)
                else:
                    setattr(eb.node, eb.event, self_event_method)
            
            eb.node.setAttribute("data-hydrated", "true")
            
        for ib in if_bindings:
            ib_node_cid = ib.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{ib_node_cid}']")
            if matched_ssr_node:
                ib.node = matched_ssr_node
                ib.is_visible = True
            elif ib_node_cid and (ssr_root.getAttribute("data-hydration-id") == ib_node_cid):
                ib.node = ssr_root
                ib.is_visible = True
            else:
                ib.is_visible = False
                # A null/absent client-id means the if-node was removed from the
                # shadow (hidden by its condition) — legitimately absent, not a
                # mismatch.  (Truthiness excludes both Python None and JsNull.)
                if report is not None and ib_node_cid:
                    report.add_unmatched_binding(
                        self.__class__.__name__, "IfBinding",
                        client_id=ib_node_cid, expected_ssr_id=ib_node_cid,
                        reason="if-node not found in SSR tree (hidden on server?)",
                    )

            anchor_cid = ib.anchor.getAttribute("data-client-id")
            matched_ssr_anchor = ssr_root.querySelector(f"[data-hydration-id='{anchor_cid}']")
            if matched_ssr_anchor:
                ib.anchor = matched_ssr_anchor
            elif anchor_cid and (ssr_root.getAttribute("data-hydration-id") == anchor_cid):
                ib.anchor = ssr_root
            

        for tb in text_bindings:
            tb_node_parent_cid = tb.node.parentNode.getAttribute("data-client-id")
            matched_ssr_node_parent = ssr_root.querySelector(f"[data-hydration-id='{tb_node_parent_cid}']")
            if not matched_ssr_node_parent \
            and tb_node_parent_cid and (ssr_root.getAttribute("data-hydration-id") == tb_node_parent_cid):
                matched_ssr_node_parent = ssr_root

            matched_text = False
            own = None
            ssr_ordinals = None
            if matched_ssr_node_parent:
                # Canonical path (Phase D): the SSR parent carries a deterministic
                # text-ordinal marker (data-basis-text) computed over *normalized*
                # children, so whitespace/comment nodes can never shift it.
                ssr_ordinals = matched_ssr_node_parent.getAttribute("data-basis-text")
                # In Pyodide, getAttribute returns a JsNull proxy (not Python
                # None) when the attribute is absent — check capability, not
                # ``is not None``, so legacy pages (no data-basis-text) fall
                # through to positional matching instead of crashing.
                if getattr(ssr_ordinals, "split", None) is not None:
                    own = text_ordinal(tb.node.parentNode, tb.node)
                    if own is not None:
                        # Count children the same way the server stamped the
                        # ordinals: elements + non-ws text + reactive text nodes
                        # (even if currently empty, per data-basis-text).
                        binding_ordinals = {
                            int(x) for x in ssr_ordinals.split(",") if x.strip()
                        }
                        counter = 0
                        for child in matched_ssr_node_parent.childNodes:
                            if child.nodeType == 1:  # element
                                counter += 1
                            elif child.nodeType == 3:  # text
                                is_binding = counter in binding_ordinals
                                is_ws = not (child.textContent or "").strip()
                                if is_binding or not is_ws:
                                    if counter == own:
                                        tb.node = child
                                        matched_text = True
                                        break
                                    counter += 1
                else:
                    # Legacy path: match the text node by its positional index
                    # within the parent's childNodes (unchanged behaviour).
                    position_in_shadow = None
                    for i, child_node in enumerate(tb.node.parentNode.childNodes):
                        if child_node == tb.node:
                            position_in_shadow = i
                    for i, childNode in enumerate(matched_ssr_node_parent.childNodes):
                        if childNode.nodeType == 3:
                            if i == position_in_shadow:
                                tb.node = childNode
                                matched_text = True

            # A null/absent parent client-id means the text node sits inside an
            # if-node hidden by its condition (removed from the shadow) — it is
            # legitimately absent from the SSR tree, not a mismatch.
            if report is not None and tb_node_parent_cid and not matched_text:
                report.add_unmatched_binding(
                    self.__class__.__name__, "TextBinding",
                    client_id=tb_node_parent_cid, expected_ssr_id=tb_node_parent_cid,
                    reason=(
                        f"text node not matched (parent_found={matched_ssr_node_parent is not None}, "
                        f"basis_text={ssr_ordinals!r}, own={own!r})"
                    ),
                )
                        
        # print(f"DEBUG HYDRATION: loop_bindings count: {len(loop_bindings)}")
        for lb in loop_bindings:
            lb.parent
            lb_child_bindings = [cb for cb in child_bindings if cb.loop_binding is lb]
            # print(f"DEBUG HYDRATION: loop_binding {lb.collection}, child_bindings count: {len(lb_child_bindings)}")
            for cb in lb_child_bindings:
                klb_child_node_cid = cb.node.getAttribute("data-client-id")
                matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{klb_child_node_cid}']")
                # print(f"DEBUG HYDRATION:   child component {cb.childinstance.__class__.__name__}, client_id: {klb_child_node_cid}, matched_ssr_node: {matched_ssr_node is not None}")
                if matched_ssr_node:
                    cb.node = matched_ssr_node
                    # CRITICAL: Attach the component instance for loop items
                    setattr(matched_ssr_node, '__basis_instance__', cb.childinstance)
                    lb.parent = matched_ssr_node.parentNode
                elif report is not None and klb_child_node_cid:
                    report.add_unmatched_binding(
                        self.__class__.__name__, "ChildBinding(loop)",
                        client_id=klb_child_node_cid, expected_ssr_id=klb_child_node_cid,
                        reason="loop child not found in SSR tree",
                    )

        for cb in child_bindings:
            if cb.loop_binding:
                continue

            cb_node_cid = cb.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{cb_node_cid}']")
            if matched_ssr_node:
                cb.node = matched_ssr_node
                # CRITICAL: Attach the component instance so parent AttributeBindings can sync props
                setattr(matched_ssr_node, '__basis_instance__', cb.childinstance)
            elif cb_node_cid and (ssr_root.getAttribute("data-hydration-id") == cb_node_cid):
                cb.node = ssr_root
                setattr(ssr_root, '__basis_instance__', cb.childinstance)
            elif report is not None and cb_node_cid:
                report.add_unmatched_binding(
                    self.__class__.__name__, "ChildBinding",
                    client_id=cb_node_cid, expected_ssr_id=cb_node_cid,
                    reason="child component root not found in SSR tree",
                )

        for ob in other_bindings:
            # Bindings already repointed to an SSR node (e.g. SelfBinding via
            # set_selfbinding) carry data-hydration-id, not data-client-id —
            # they are already hydrated, so skip them.
            if hasattr(ob.node, "hasAttribute") and ob.node.hasAttribute("data-hydration-id"):
                continue
            ob_node_cid = ob.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{ob_node_cid}']")
            if matched_ssr_node:
                ob.node = matched_ssr_node
            elif ob_node_cid and (ssr_root.getAttribute("data-hydration-id") == ob_node_cid):
                ob.node = ssr_root
            elif report is not None and ob_node_cid:
                # A ComponentSubscription points at the SUBSCRIBER's root
                # element (``subscriber.__element__``), which can live OUTSIDE
                # this component's SSR subtree.  That node is hydrated by the
                # subscriber's own initialize_ssr, so a match anywhere in the
                # SSR tree means it is handled — not a mismatch.  (Its ``node``
                # is also a read-only property, so repointing here is neither
                # possible nor necessary.)
                if type(ob).__name__ == "ComponentSubscription":
                    try:
                        elsewhere = document.querySelector(
                            f"[data-hydration-id='{ob_node_cid}']"
                        )
                    except Exception:
                        elsewhere = None
                    if elsewhere:
                        continue
                report.add_unmatched_binding(
                    self.__class__.__name__, type(ob).__name__,
                    client_id=ob_node_cid, expected_ssr_id=ob_node_cid,
                    reason="binding node not found in SSR tree",
                )

        with self.refrain() as refrained:
            for k, v in kwargs.items():
                setattr(refrained, k, v)

    @property
    def client_id(self):
        try:
            cid = self.__element__.getAttribute('data-client-id')
            if cid:
                return cid
            else:
                return None

        except:
            return None
        
    def get_descendant_client_ids(self):
        
        client_id_node_mapping = {}

        for node in self.__element__.querySelectorAll("[data-client-id]"):
            cid = node.getAttribute("data-client-id")
            client_id_node_mapping[cid] = node
        
        return client_id_node_mapping

    @classmethod
    def mount_app_ssr(cls, ssr_root=None, replace=False):
        
        shadow_element_div = document.createElement("div")
        shadow = shadow_element_div.attachShadow({ 'mode': 'open' })

        mounted_app_component = cls.mount_app(shadow, replace)
        client_id_to_node_map = mounted_app_component._set_nodes_with_client_ids(element=mounted_app_component.__element__)
        
        #print("client_id_to_node_map", client_id_to_node_map)
        
        child_bindings_recursive = [cb for cb  in mounted_app_component.get_child_bindings(recursive=True)]
        child_component_instances = [cb.childinstance for cb  in child_bindings_recursive]

        root_plus_child_component_instances = [mounted_app_component, *child_component_instances]

        client_ids_dict = {}


        for child_instance in root_plus_child_component_instances:
            child_client_id = child_instance.__element__.getAttribute("data-client-id")
            client_ids_dict[child_client_id] = child_instance
            
        #print("client_ids_dict keys:", [k for k in client_ids_dict.keys()])

        if not ssr_root:
            ssr_root = document.body

        marked_for_hydration = ssr_root.querySelectorAll("[data-hydration-id]")
        marked_for_hydration_dict = {}
        for x in marked_for_hydration:
            hid = x.getAttribute("data-hydration-id")
            if hid:
                marked_for_hydration_dict[hid] = x
        
        marked_for_hydration_ids = [k for k in marked_for_hydration_dict.keys()]

        # ---- Diagnostics (Phase E) ----
        # The client cannot read the server env; detect the mode from the tree
        # (canonical pages carry data-basis-text, legacy pages do not).
        mode = "canonical" if ssr_root.querySelector("[data-basis-text]") else "legacy"
        report = HydrationReport(mode=mode)
        fallback_needed = False

        for child_instance in root_plus_child_component_instances:
            cid = child_instance.client_id
            if cid \
            and (cid in marked_for_hydration_dict):
                corresponding_ssr_root_node = marked_for_hydration_dict[cid]
                try:
                    child_instance.initialize_ssr(corresponding_ssr_root_node, report=report)
                except Exception as exc:
                    # One broken component must not abort the whole report.
                    report.add_unhydrated_component(
                        child_instance.__class__.__name__, client_id=cid,
                        reason=f"initialize_ssr raised: {exc}",
                    )
            else:
                # Component root not present in the SSR tree.  Normal when it is
                # hidden by an if-binding on the server (its shadow node is then
                # detached); otherwise it is a genuine mismatch.
                if cid is not None:
                    hidden = not _shadow_contains(shadow, child_instance.__element__)
                    report.add_unhydrated_component(
                        child_instance.__class__.__name__, client_id=cid,
                        reason="hidden by if-binding" if hidden
                        else "component not present in SSR tree",
                    )
                    if not hidden:
                        fallback_needed = True

        if fallback_needed and hydration_fallback_enabled():
            _fallback_rerender(ssr_root, shadow, report)

        _emit_hydration_report(report)
    
    @client
    def _find_elements_marked_for_hydration(self, element=None):

        if not element:
            element_to_walk = self.__template__
        else:
            element_to_walk = element

        walker = document.createTreeWalker(element_to_walk, window.NodeFilter.SHOW_ELEMENT)

        nodes = []
        current_node = walker.nextNode()
        while current_node:
            if current_node.hasAttribute("data-hydration-id"):
                nodes.append(current_node)

            current_node = walker.nextNode()

        return nodes

    
    @client
    def _get_nodes_with_client_ids(self, element=None):

        if not element:
            element_to_walk = self.__template__
        else:
            element_to_walk = element

        walker = document.createTreeWalker(element_to_walk, window.NodeFilter.SHOW_ELEMENT)

        nodes_dict = {}
        current_node = walker.nextNode()
        while current_node:
            if current_node.hasAttribute("data-client-id"):
                client_id = current_node.getAttribute("data-client-id")
                nodes_dict[client_id] = current_node

            current_node = walker.nextNode()

        return nodes_dict

    @client
    def _set_nodes_with_client_ids(self, element=None):
            
        if not element:
            element = self.__template__

        element_to_walk = element
        
        id_to_node_map = {}

        # Initial Root Setup
        root_id = "r:0"
        if hasattr(element_to_walk, "setAttribute"):
            element_to_walk.setAttribute("data-client-id", root_id)
        id_to_node_map[root_id] = element_to_walk

        walker = document.createTreeWalker(
            element_to_walk, 
            window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT
        )

        # Stack stores: [ [node, path_prefix, next_child_index] ]
        # We start with the root on the stack. 
        # Server root is r:0, so its children should be r:0:0, r:0:1 etc.
        stack = [[element_to_walk, root_id, 0]]

        current_node = walker.nextNode()
        while current_node:
            parent = current_node.parentNode

            # 1. Ascend: Pop until the top of the stack is the actual parent
            while stack and stack[-1][0] != parent:
                stack.pop()

            if not stack:
                # Fallback for unexpected tree breaks
                current_node = walker.nextNode()
                continue

            # 2. Skip nodes that the server-side tree builder ignores (whitespace-only text)
            # Server-side tree_builder.py handle_data calls data.strip() and ignores if empty.
            if current_node.nodeType == 3: # TEXT_NODE
                if not current_node.textContent.strip():
                    current_node = walker.nextNode()
                    continue
            
            # 3. Get info from the parent (top of stack)
            parent_info = stack[-1]
            parent_path = parent_info[1]
            current_index = parent_info[2]

            # 4. Create ID: prefix : index
            current_id = f"{parent_path}:{current_index}"
            
            # 5. Increment the index for the NEXT sibling
            parent_info[2] += 1

            # 6. Apply ID and map
            try:
                if hasattr(current_node, "setAttribute"):
                    current_node.setAttribute("data-client-id", current_id)
                id_to_node_map[current_id] = current_node
            except:
                pass

            # 7. Descend: If this node can have children, push it onto the stack
            # 1 is Node.ELEMENT_NODE. Text/Comments (3/8) can't have children.
            if current_node.nodeType == 1:
                stack.append([current_node, current_id, 0])

            current_node = walker.nextNode()

        return id_to_node_map