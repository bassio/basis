from dataclasses import dataclass
from functools import wraps

try:
    from pyscript import window, document, ffi, fetch

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False

from basis.shared.bindings import SelfBinding, ChildBinding, EventBinding, IfBinding, TextBinding, KeyedLoopBinding

from basis.shared.base_component import BaseComponent
from basis.shared.hmr import start_hmr

def client(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if PYSCRIPT:
            return func(*args, **kwargs)

    return wrapper


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
        print("_register_custom_element", cls.__tag__)
        if "-" in cls.__tag__ \
        and cls.__tag__ not in cls._registry:
            templatestr = cls.__templatestr__
            custom_element = window.CustomElementFactory(ffi.to_js({'__templatestr__': templatestr, 'pyClassName': cls.__name__, '__shadow__': getattr(cls, '__shadow__', False)}))
            window.customElements.define(cls.__tag__, custom_element)
            setattr(cls, 'custom_element', custom_element)
    
    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        
        #client
        cls._register_custom_element()
        
        # Start HMR if on client
        #if PYSCRIPT:
        #    start_hmr()

    def __init__(self):
        super().__init__()


    @classmethod
    def _get_nodes(cls, element):

        walker = document.createTreeWalker(element, window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT | window.NodeFilter.SHOW_COMMENT)

        nodes = []
        current_node = walker.nextNode()
        while current_node:
            nodes.append(current_node)
            current_node = walker.nextNode()

        return nodes

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
        return ffi.create_proxy(f)

    @client   
    def _create_update_handler(self, f, input_type):
        handler = super()._create_update_handler(f, input_type)
        return self._create_function_proxy(handler)

    def initialize_ssr(self, ssr_root, **kwargs):
        
        self.set_selfbinding(ssr_root)

        all_bindings = [b for b in self.__bindings__]
        event_bindings = [eb for eb in all_bindings if isinstance(eb, EventBinding)]
        if_bindings = [ib for ib in all_bindings if isinstance(ib, IfBinding)]
        text_bindings = [tb for tb in all_bindings if isinstance(tb, TextBinding)]
        keyed_loop_bindings = [klb for klb in all_bindings if isinstance(klb, KeyedLoopBinding)]
        child_bindings = [eb for eb in all_bindings if isinstance(eb, ChildBinding)]
        other_bindings = [ob for ob in all_bindings if ob not in event_bindings + if_bindings + text_bindings + keyed_loop_bindings + child_bindings]


        for eb in event_bindings:
            
            eb_node_cid = eb.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{eb_node_cid}']")
            if matched_ssr_node:
                eb_node_new = matched_ssr_node
                print(f"MATCHED event binding's {eb.event} node: {eb_node_new.outerHTML}")
            elif ssr_root.getAttribute("data-hydration-id") == eb_node_cid:
                eb_node_new = ssr_root
                print(f"MATCHED event binding's {eb.event} node: {eb_node_new.outerHTML}")
            else:
                eb_node_new = eb.node #just keep the old node then !
                # this addresses an error that elements hidden because of an IfBinding will not be assigned a client id
                # because they are not in the shadow dom tree in the first place !!
                print(f"DID NOT MATCH event binding's {eb.event} node with client_id {eb_node_cid}: {eb_node_new.outerHTML}")

            eb.node = eb_node_new

            if isinstance(eb.target_fn, str):
                event_method = getattr(self, eb.target_fn)
                event_method_final = self._create_function_proxy(event_method)
                eb.node.removeAttribute(eb.event)
                setattr(eb.node, eb.event, event_method_final)
            else:
                self_event_method = eb.target_fn
                eb.node.removeAttribute(eb.event)
                setattr(eb.node, eb.event, self_event_method)

        for ib in if_bindings:
            ib_node_cid = ib.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{ib_node_cid}']")
            if matched_ssr_node:
                ib.node = matched_ssr_node
                ib.is_visible = True
            elif ib_node_cid and ssr_root.getAttribute("data-hydration-id") == ib_node_cid:
                ib.node = ssr_root
                ib.is_visible = True
            else:
                ib.is_visible = False
                #no-op : leave the node the one still in the shadow dom

            anchor_cid = ib.anchor.getAttribute("data-client-id")
            matched_ssr_anchor = ssr_root.querySelector(f"[data-hydration-id='{anchor_cid}']")
            if matched_ssr_anchor:
                ib.anchor = matched_ssr_anchor
            elif anchor_cid and ssr_root.getAttribute("data-hydration-id") == anchor_cid:
                ib.anchor = ssr_root
            

        for tb in text_bindings:
            tb_node_parent_cid = tb.node.parentNode.getAttribute("data-client-id")
            matched_ssr_node_parent = ssr_root.querySelector(f"[data-hydration-id='{tb_node_parent_cid}']")
            if not matched_ssr_node_parent \
            and tb_node_parent_cid and ssr_root.getAttribute("data-hydration-id") == tb_node_parent_cid:
                matched_ssr_node_parent = ssr_root

            if matched_ssr_node_parent:
                for childNode in matched_ssr_node_parent.childNodes:
                    if childNode.nodeType == 3:
                        if childNode.textContent == tb.node.textContent:
                            #print("YES!!!!!!!!!!!!!!!!!!", tb.node.textContent)
                            tb.node = childNode
                        else:
                            #print("No!!!!!!!!!!!!!!!!!!!", childNode.textContent)
                            pass

        for klb in keyed_loop_bindings:
            klb.parent
            klb_child_bindings = [cb for cb in child_bindings if cb.loop_binding is klb]
            for cb in klb_child_bindings:
                klb_child_node_cid = cb.node.getAttribute("data-client-id")
                matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{klb_child_node_cid}']")
                if matched_ssr_node:
                    cb.node = matched_ssr_node
                    klb.parent = matched_ssr_node.parentNode

        for cb in child_bindings:
            if cb.loop_binding:
                continue

            cb_node_cid = cb.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{cb_node_cid}']")
            if matched_ssr_node:
                cb.node = matched_ssr_node
            elif cb_node_cid and ssr_root.getAttribute("data-hydration-id") == cb_node_cid:
                cb.node = ssr_root

        for ob in other_bindings:
            ob_node_cid = ob.node.getAttribute("data-client-id")
            matched_ssr_node = ssr_root.querySelector(f"[data-hydration-id='{ob_node_cid}']")
            if matched_ssr_node:
                ob.node = matched_ssr_node
            elif ob_node_cid and ssr_root.getAttribute("data-hydration-id") == ob_node_cid:
                ob.node = ssr_root

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
        shadow = shadow_element_div

        mounted_app_component = cls.mount_app(shadow, replace)
        client_id_to_node_map = mounted_app_component._set_nodes_with_client_ids(element=mounted_app_component.__element__)
        
        print("client_id_to_node_map", client_id_to_node_map)
        
        child_bindings_recursive = [cb for cb  in mounted_app_component.get_child_bindings(recursive=True)]
        child_component_instances = [cb.childinstance for cb  in child_bindings_recursive]

        root_plus_child_component_instances = [mounted_app_component, *child_component_instances]

        client_ids_dict = {}

        print("$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$$")

        for child_instance in root_plus_child_component_instances:
            child_client_id = child_instance.__element__.getAttribute("data-client-id")
            client_ids_dict[child_client_id] = child_instance
            
        print("client_ids_dict keys:", [k for k in client_ids_dict.keys()])

        if not ssr_root:
            ssr_root = document.body

        marked_for_hydration = ssr_root.querySelectorAll("[data-hydration-id]")
        marked_for_hydration_dict = {x.getAttribute("data-hydration-id"):x for x in marked_for_hydration}
        
        marked_for_hydration_ids = [k for k in marked_for_hydration_dict.keys()]
        #print("marked_for_hydration", marked_for_hydration_ids)
        print("marked_for_hydration_dict", marked_for_hydration_dict)
        print("mismatch", [x for x in marked_for_hydration_ids if x not in [k for k in client_ids_dict.keys()]])
        
        for child_instance in root_plus_child_component_instances:
            cid = child_instance.client_id
            if cid \
            and (cid in marked_for_hydration_dict):
                corresponding_ssr_root_node = marked_for_hydration_dict[cid]
                child_instance.initialize_ssr(corresponding_ssr_root_node)
            else:
                # Component is not in the SSR tree (e.g. hidden by IfBinding)
                print(f"Skipping hydration for hidden component: {child_instance} (id: {cid})")
    
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