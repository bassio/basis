from string import Formatter
from dataclasses import dataclass
from functools import wraps, partial
import inspect
import json
import copy

try:
    import pyscript

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False

from basis.shared.bindings import Binding, SelfBinding, TextBinding, \
    AttributeBinding, SelfAttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding, \
    safe_eval, safe_format, safe_format_with_stores, \
    extract_dependencies, ALLOWED_BUILTINS, Refrain, \
    _process_event_attr_bindings, _process_standard_attr_bindings, \
    _process_text_bindings
    

from basis.shared.store import Store
from basis.shared.base_component import BaseComponent

from basis.server.components.element import Element, ElementString, Comment, html_to_element_tree, ServerFragment



class ServerComponent(BaseComponent):

    # _registry = {} defined on BaseComponent
    _instance_registry = {}
    _pending_subscriptions = {}

    S = Store._registry
    C = _instance_registry

    #@server
    @classmethod
    def _initialize_blueprint(cls):
        ###Server
        blueprint_tree = html_to_element_tree(cls.__templatestr__)
        setattr(cls, "__blueprint__", blueprint_tree)
    
    #@server
    @classmethod
    def clone_blueprint(cls):
        raw = cls.__blueprint__
        # blueprint is the builder dict; 'component' key holds the root Element
        root_element = raw['component']
        return copy.deepcopy(root_element)

    #@server
    @property
    def __template__(self) -> ServerFragment:
        """Return a ServerFragment wrapping the root Element.

        Mirrors the client where __template__ is the DocumentFragment (.content)
        of the cloned <template> element.  The fragment is consumed (emptied) by
        the first Element.appendChild() call in mount(), so any later call (e.g.
        from _bind_node) is a silent no-op — identical to client behaviour.
        """
        if '_template' not in self.__dict__:
            root = self.__class__.clone_blueprint()
            self.__dict__['_template'] = ServerFragment(root)
        return self.__dict__['_template']
    
    def __init__(self):
        super().__init__()

    #@server
    def _get_nodes(self, element=None):
        
        nodes = []
        
        if element:
            for d in element.descendants:
                nodes.append(d)

            return nodes

        else:
            if hasattr(self, "_nodes"):
                return self._nodes
            else:
                # Unwrap ServerFragment → root Element for traversal
                template = self.__template__
                top_elem = template.root if isinstance(template, ServerFragment) else template
                for d in top_elem.descendants:
                    nodes.append(d)
        
                self.__dict__['_nodes'] = nodes

                return nodes
    
    #@server
    def _create_comment(self, comment_text, parent=None):
        return Comment(data=comment_text, parent=parent)
    
    #@server
    def _create_document_fragment(self):
        return ServerFragment(root=None)

    #@server
    @classmethod
    def _create_element(cls, tag):
        element = Element(tag, attrs={}, children=[])
        return element

    def _bind_node(self, node):

        formatter = Formatter()
        bindings=[]
        fields=[]

        if hasattr(node, 'getAttributeNames'): #confirm it is an ELEMENT not a TEXT node
            element = node
            if '-' in element.tagName:
                tag = str.lower(element.tagName)
                childcomponent_py = self.__class__._registry[tag]
                dom_child_node_attrs = {a: element.getAttribute(a) for a in element.getAttributeNames()}

                if not getattr(node, '__basis_mounted__', False):
                    print("appending child..")
                    child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)
                    node.__basis_mounted__ = True
                    node.appendChild(child_instance.__template__)  # no-op: fragment already consumed by mount()

                    child_attr_bindings = [sab for sab in child_instance.__bindings__ \
                                        if isinstance(sab, SelfAttributeBinding)]
                    bindings.append(ChildBinding(component_instance=self, node=element, childclass=childcomponent_py, childinstance=child_instance, attr_bindings=child_attr_bindings))
                else:
                    raise Exception("excepted here __basis_mounted__")
                
            if str.lower(element.tagName) == 'slot':
                return

                
            element_attrs = [a for a in element.getAttributeNames()]
            event_attrs = [a for a in element_attrs if a.startswith("on")]
            other_attrs = [a for a in element_attrs if not a.startswith("on")]

            special_attrs = ["if", "for", "in", "key", "bind"]

            non_standard_attrs = [a for a in other_attrs if not a.startswith("on") and a in special_attrs]
            standard_attrs = [a for a in other_attrs if a not in non_standard_attrs]
                        
            #event
            event_bindings, event_fields = _process_event_attr_bindings(self, element, event_attrs)
            bindings += event_bindings
            fields += event_fields
            
            #standard
            std_bindings, std_fields = _process_standard_attr_bindings(self, element, standard_attrs)
            bindings += std_bindings
            fields += std_fields


            #'if' attr
            if 'if' in non_standard_attrs:
                if_expr = element.getAttribute('if')
                if_expr_clean = if_expr.removeprefix("{").removesuffix("}")
                print("if_expr",element.parentNode)
                fieldnames = extract_dependencies(if_expr, ALLOWED_BUILTINS) 
                anchor = self._create_comment(f"if: {if_expr_clean}", parent=element.parentNode)
                
                #client
                element.parentNode.insertBefore(anchor, element)
                bindings.append(IfBinding(
                    component_instance=self, node=element, expr=if_expr_clean, anchor=anchor, is_visible=True, fields=fieldnames
                ))
                fields += fieldnames

            #'bind' attr
            if 'bind' in non_standard_attrs:
                bind_attr_value = element.getAttribute('bind')
                fieldnames = extract_dependencies(bind_attr_value, ALLOWED_BUILTINS)
                if len(fieldnames) == 1:
                    field = fieldnames[0]
                    bindings.append(ModelBinding(component_instance=self, node=element, field=field))
                    fields.append(field)
                    tag_name = str.lower(element.tagName)
                    input_type = element.getAttribute('type') if element.hasAttribute('type') else 'text'


                    handler = self._create_update_handler(field, input_type)

                    if tag_name == 'input' and input_type in ['checkbox', 'radio']:
                        bound_event = 'change'
                    elif tag_name == 'select':
                        bound_event = 'change'
                    else:
                        bound_event = 'input'
                    
                    #client
                    element.addEventListener(bound_event, handler)
                    bindings.append(EventBinding(component_instance=self, node=element, event=f"{bound_event}", target_fn=handler))

            if 'for' in non_standard_attrs:
                inlist_attr_value = element.getAttribute('in').strip("{}")
                for_attr_value = element.getAttribute('for')

                #client
                element_clone = element.cloneNode(True)
                if element.hasAttribute('key'):
                    bindings.append(KeyedLoopBinding(component_instance=self, node=element, clone=element_clone, parent=element.parentElement, collection=inlist_attr_value, item=for_attr_value, key=element.getAttribute('key')))
                else:
                    bindings.append(LoopBinding(component_instance=self, node=element, clone=element_clone, parent=element.parentElement, collection=inlist_attr_value, item=for_attr_value))

        elif node.nodeName == '#text':
            text_bindings, text_fields = _process_text_bindings(self, node)
            bindings += text_bindings
            fields += text_fields

        elif node.nodeName == '#comment':
            pass

        self.__bindings__.extend(bindings)

        for f in fields:
            if f not in self.__fields__:
                self.__fields__.append(f)

    
    @classmethod
    def mount_app_ssr(cls, container, replace=False):
        """
        Entry point for SSR pages.

        Checks whether the container already holds server-rendered content
        (identified by data-basis-component markers). If so, calls .hydrate()
        on the matching Component subclass; otherwise falls back to .mount_app().

        Also registers a document-level listener for 'basis:hydrate' events
        fired by CustomElementFactory when custom elements with SSR content
        are upgraded by the browser.
        """
        # Register the global SSR hydration event listener so that nested
        # custom elements deferred by the browser emit their hydrate events
        # and get picked up here.
        @client
        def _register_hydration_listener():
            def _on_hydrate(event):
                py_class_name = event.detail.pyClassName
                element = event.detail.element
                for tag, component_cls in self.__class__._registry.items():
                    if component_cls.__name__ == py_class_name:
                        print(f"Hydrating {py_class_name} via basis:hydrate event")
                        component_cls.hydrate(element)
                        return
                print(f"Warning: No Component found for '{py_class_name}' during hydration")
            
            #client
            document.addEventListener('basis:hydrate', ffi.create_proxy(_on_hydrate))

        _register_hydration_listener()

        # Check if the container's first data-basis-component element matches cls
        ssr_root = None
        try:
            ssr_root = container.querySelector('[data-basis-component]')
        except Exception:
            pass

        if ssr_root is not None:
            py_class_name = ssr_root.getAttribute('data-basis-component')
            if py_class_name == cls.__name__:
                new_instance = cls.hydrate(ssr_root.parentElement or ssr_root)
                return new_instance

        # Fallback: regular SPA mount
        return cls.mount_app(container, replace)

    @classmethod
    def hydrate(cls, container, **attributes):

        """
        Attach Basis reactivity to an existing server-rendered DOM node.

        Unlike mount(), this method does NOT insert any new nodes — it binds
        against what is already in the live DOM (placed there by SSR).

        Parameters
        ----------
        container:
            The custom-element host node (e.g. <my-sidebar>) whose
            firstElementChild is the pre-rendered component root.
        attributes:
            Initial attribute values to set before building bindings.
        """
        print(f"hydrate: starting hydration of {cls} against existing DOM")
        new_instance = cls.__new__(cls)
        # Manually call super() __init__ to set up __bindings__ / __fields__
        super(cls, new_instance).__init__()
        new_instance.__dict__['_subscriptions'] = []

        if attributes:
            new_instance.__dict__.update(attributes)

        # Point _template at the existing live DOM root (firstElementChild of
        # the custom-element host, which is the server-rendered component root).
        live_root = container.firstElementChild or container
        new_instance.__dict__['_template'] = cls._create_element('template')
        new_instance.__dict__['_template'].content.appendChild(live_root)

        # Bootstrap SelfBinding from the live root
        new_instance.__dict__['__bindings__'].append(
            SelfBinding(component_instance=new_instance, node=live_root)
        )

        @client
        def _finish_hydration(inst):
            inst.__init_bindings__()
            inst.__init_fields__()
            with inst.refrain() as refrained:
                for k, v in attributes.items():
                    setattr(refrained, k, v)

        _finish_hydration(new_instance)

        print(f"hydrate: finished hydration of {cls}")
        return new_instance
        

    def react(self, names):

        print(f"In react({names}) of {self.__class__}")
        
        text_bindings:list[TextBinding] = [tb for tb in self.__bindings__ if isinstance(tb, TextBinding)]
        attr_bindings:list[AttributeBinding] = [ab for ab in self.__bindings__ if isinstance(ab, AttributeBinding)]
        model_bindings:list[ModelBinding] = [mb for mb in self.__bindings__ if isinstance(mb, ModelBinding)]
        if_bindings:list[IfBinding] = [ib for ib in self.__bindings__ if isinstance(ib, IfBinding)]
        loop_bindings:list[LoopBinding] = [lb for lb in self.__bindings__ if isinstance(lb, LoopBinding)]
        keyed_loop_bindings:list[KeyedLoopBinding] = [lb for lb in self.__bindings__ if isinstance(lb, KeyedLoopBinding)]
        child_bindings:list[ChildBinding] = [cb for cb in self.__bindings__ if isinstance(cb, ChildBinding)]

        child_attr_bindings:list[SelfAttributeBinding] = []
        for cb in child_bindings:
            child_attr_bindings.extend(cb.attr_bindings)

        looped_nodes = [lb.node for lb in loop_bindings] + [lb.node for lb in keyed_loop_bindings]
        

        text_bindings_to_update = []
        attr_bindings_to_update = []
        model_bindings_to_update = []
        if_bindings_to_update = []

        for tb in text_bindings:
            if len(set(tb.fields).intersection(names)):
                if tb not in text_bindings_to_update:
                    text_bindings_to_update.append(tb)

        for ab in attr_bindings:
            if len(set(ab.fields).intersection(names)):
                if ab not in attr_bindings_to_update:
                    attr_bindings_to_update.append(ab)
       ###
        for cab in child_attr_bindings:
            if len(set(cab.fields).intersection(names)):
                if cab not in attr_bindings_to_update:
                    attr_bindings_to_update.append(cab)

        for mb in model_bindings:
            if len(set(mb.fields).intersection(names)):
                if mb not in model_bindings_to_update:
                    model_bindings_to_update.append(mb)

        #print("in react", "if bindings:", if_bindings)
        for ib in if_bindings:
            print("ib fields:", ib.fields)
            if len(set(ib.fields).intersection(names)):
                if ib not in if_bindings_to_update:
                    if_bindings_to_update.append(ib)

        attr_bindings_to_pop = []
        text_bindings_to_pop = []
        new_child_bindings = []

        formatter = Formatter()

        ### antigravity generated

        for lb in keyed_loop_bindings:

            if lb.collection in names:
                collection_value = getattr(self, lb.collection, [])
                
                if not hasattr(lb, 'instances'):
                    lb.instances = {}

                new_instances = {}

                #client
                fragment = self._create_document_fragment()
                
                # Pop parent components initial bindings on this loop placeholder
                for tb in text_bindings:
                    #client: contains
                    if lb.node.contains(tb.node) and lb.item in tb.fields:
                        text_bindings_to_pop.append(tb)
                for ab in attr_bindings:
                    if ab.node == lb.node and lb.item in ab.fields:
                        attr_bindings_to_pop.append(ab)

                for i in collection_value:
                    if isinstance(i, dict):
                        k_val = i.get(lb.key)
                    else:
                        try:
                            k_val = getattr(i, lb.key)
                        except AttributeError:
                            k_val = getattr(i, 'get', lambda k: None)(lb.key)
                    
                    if k_val in lb.instances:
                        # Reuse
                        child_instance = lb.instances[k_val]
                        
                        updated_child_node_attrs = {lb.item: i}
                        rest_of_fields = [f for f in self.__fields__ if (f != lb.item) and (not inspect.isfunction(getattr(self, f)))]
                        for field in rest_of_fields:
                            updated_child_node_attrs[field] = getattr(self, field)
                            
                        if '-' in (tag:=str.lower(lb.clone.tagName)):
                            for c_attr in lb.clone.getAttributeNames():
                                c_attr_value = lb.clone.getAttribute(c_attr)
                                if c_attr not in updated_child_node_attrs:
                                    
                                    has_expr = any(fname is not None for _, fname, _, _ in formatter.parse(c_attr_value))
                                    if has_expr:
                                        val = safe_format(c_attr_value, updated_child_node_attrs, ALLOWED_BUILTINS)
                                        updated_child_node_attrs[c_attr] = val
                                    else:
                                        updated_child_node_attrs[c_attr] = c_attr_value
                            
                        # Update props and component reacts
                        for k, v in updated_child_node_attrs.items():
                            setattr(child_instance, k, v)
                            
                        fragment.appendChild(child_instance.__element__)
                        new_instances[k_val] = child_instance
                    else:
                        # New creation
                        cloned_element = lb.node.cloneNode(True)
                        cloned_element.removeAttribute('for')
                        cloned_element.removeAttribute('in')
                        cloned_element.removeAttribute('key')


                        updated_child_node_attrs = {lb.item: i}
                        rest_of_fields = [f for f in self.__fields__ if (f != lb.item) and (not inspect.isfunction(getattr(self, f)))]
                        for field in rest_of_fields:
                            updated_child_node_attrs[field] = getattr(self, field)
                        
                        if '-' in (tag:=str.lower(lb.clone.tagName)):
                            childcomponent_py = self.__class__._registry[tag]
                            for c_attr in cloned_element.getAttributeNames():
                                if c_attr not in updated_child_node_attrs:
                                    c_attr_value = cloned_element.getAttribute(c_attr)
                                    has_expr = any(fname is not None for _, fname, _, _ in formatter.parse(c_attr_value))
                                    if has_expr:
                                        val = safe_format(c_attr_value, updated_child_node_attrs, ALLOWED_BUILTINS)
                                        updated_child_node_attrs[c_attr] = val
                                    else:
                                        updated_child_node_attrs[c_attr] = c_attr_value
                        else:
                            quick_component = self.__class__.from_template(cloned_element.outerHTML)
                            childcomponent_py = quick_component
                                
                        new_cb = ChildBinding(component_instance=self, node=cloned_element, childclass=childcomponent_py)
                        self.__bindings__.append(new_cb)
                        
                        custom_child_instance = new_cb.childclass.mount(fragment, replace=False, **updated_child_node_attrs)
                        new_cb.childinstance = custom_child_instance
                        new_instances[k_val] = custom_child_instance

                # Cleanup old child bindings that are removed
                for k_val, old_instance in lb.instances.items():
                    if k_val not in new_instances:
                        bindings_to_rem = [cb for cb in self.__bindings__ if isinstance(cb, ChildBinding) and getattr(cb, 'childinstance', None) == old_instance]
                        for rem in bindings_to_rem:
                            self.__bindings__.remove(rem)

                #client
                lb.parent.replaceChildren(*fragment.children)
                lb.instances = new_instances


        ### end antigravity

        for lb in loop_bindings:

            if lb.collection in names:
                collection_value = self.__dict__[lb.collection]

                cloned_elements = []

                #client
                fragment = self._create_document_fragment()

                for i in collection_value: #iterate through the collection

                    cloned_element = lb.node.cloneNode(True)
                    cloned_element.removeAttribute('for')
                    cloned_element.removeAttribute('in')

                    
                    if '-' in (tag:=str.lower(lb.clone.tagName)):
                        childcomponent_py = self.__class__._registry[tag]
                    else:
                        quick_component = self.__class__.from_template(cloned_element.outerHTML)
                        childcomponent_py = quick_component

                    new_cb = ChildBinding(component_instance=self, node=cloned_element, childclass=childcomponent_py)
                    new_child_bindings.append(new_cb)
                    self.__bindings__.append(new_cb)
                    
                    new_cb = ChildBinding(component_instance=self, node=cloned_element, childclass=childcomponent_py)
                    new_child_bindings.append(new_cb)
                    self.__bindings__.append(new_cb)
                    

                    for tb in text_bindings:
                        #client
                        if lb.node.contains(tb.node) \
                        and lb.item in tb.fields:
                            new_text_binding = TextBinding(self, node=cloned_element, content=tb.content, fields=tb.fields)
                            self.__bindings__.append(new_text_binding)
                            text_bindings_to_pop.append(tb)

                    for ab in attr_bindings:
                        if ab.node == lb.node \
                        and lb.item in ab.fields:
                            new_attr_binding = AttributeBinding(self, node=cloned_element, attr=ab.attr, content=ab.content, fields=ab.fields)
                            self.__bindings__.append(new_attr_binding)
                            attr_bindings_to_pop.append(ab)

                    
                    if '-' in (tag:=str.lower(lb.clone.tagName)):
                        updated_child_node_attrs = {c: new_cb.node.getAttribute(c) for c in new_cb.node.getAttributeNames()}
                        custom_child_instance = new_cb.childclass.mount(fragment, replace=False, **updated_child_node_attrs)
                        new_cb.childinstance = custom_child_instance

                    else:
                        updated_child_node_attrs = {}
                        updated_child_node_attrs[lb.item] = i

                        rest_of_fields = [f for f in self.__fields__ if (f != lb.item) and (not inspect.isfunction(getattr(self, f)))]

                        for field in rest_of_fields:
                            updated_child_node_attrs[field] = getattr(self,field)

                        custom_child_instance = new_cb.childclass.mount(fragment, replace=False, **updated_child_node_attrs)

                        new_cb.childinstance = custom_child_instance
            
            #client
            lb.parent.replaceChildren(*fragment.children)

            #delete old child bindings
            for cb in child_bindings:
                if cb.node == lb.node:
                    self.__bindings__.remove(cb)
                elif '-' in (tag:=str.lower(lb.clone.tagName)):
                    childcomponent_py = self.__class__._registry[tag]
                    if cb.childclass == childcomponent_py:
                        self.__bindings__.remove(cb)
                
        #print("text_bindings_to_update before popping", text_bindings_to_update)
        for tb in text_bindings_to_pop:
            try:
                text_bindings_to_update.remove(tb) #pop
            except ValueError:
                pass

        for ab in attr_bindings_to_pop:
            try:
                attr_bindings_to_update.remove(ab) #pop
            except ValueError:
                pass

        for tb in text_bindings_to_update:
            #print("text_bindings_to_update", text_bindings_to_update)
            tb.node.textContent = safe_format_with_stores(tb.content, tb.component_instance.__dict__, ALLOWED_BUILTINS, Store._registry, self.__class__._instance_registry)

        for mb in model_bindings_to_update:
            #print("model_bindings_to_update (in {self.__class__}):", model_bindings_to_update)
            if mb.node not in looped_nodes:
                val = getattr(self, mb.field)
                input_type = mb.node.getAttribute('type') if mb.node.hasAttribute('type') else 'text'
                #print(f"model final_val (in {self.__class__}):", val, "input_type", )
                if input_type == 'checkbox':
                    mb.node.checked = bool(val)
                else:
                    mb.node.value = str(val) if val is not None else ""

        for ab in attr_bindings_to_update:
            print("attr_bindings_to_update", attr_bindings_to_update)
            if ab.node not in looped_nodes:                    
                if ab.attr not in ["in"]:
                    final_val = safe_format_with_stores(ab.content, self.__dict__, ALLOWED_BUILTINS, Store._registry, self.__class__._instance_registry)
                    print("final_val", final_val)
                    if ab.is_boolean:
                        bool_val = str(final_val).lower() == 'true'
                        if isinstance(ab, SelfAttributeBinding):
                            setattr(ab.component_instance, ab.attr, bool_val)
                        else: #just an AttributeBinding
                            ab.node.toggleAttribute(ab.attr, bool_val)
                    else:
                        if isinstance(ab, SelfAttributeBinding):
                            setattr(ab.component_instance, ab.attr, final_val)
                        else: #just an AttributeBinding
                            ab.node.setAttribute(ab.attr, final_val)

                else:
                    _, fname, _, _ = next(iter(formatter.parse(ab.content)))
                    evaluated_val = safe_eval(fname, self.__dict__, ALLOWED_BUILTINS)
                    final_val = json.dumps(evaluated_val)
                    ab.node.setAttribute(ab.attr, final_val)
                    
        for ib in if_bindings_to_update:
            expr_eval = bool(safe_eval(ib.expr, self.__dict__, ALLOWED_BUILTINS))
            if expr_eval == ib.is_visible:
                continue  # visibility unchanged — skip DOM mutation
            if expr_eval == False:
                #print("REMOVING node from DOM based on IfBinding")
                ib.node.remove() #client
            else:
                #print("INSERTING node into DOM based on IfBinding")
                ib.anchor.after(ib.node) #client
            ib.is_visible = expr_eval

