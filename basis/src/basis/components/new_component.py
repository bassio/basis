from string import Formatter
from dataclasses import dataclass
from functools import wraps, partial
import inspect
import json
from pathlib import Path

try:
    from pyscript import window, document, ffi, fetch

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False

from basis.shared.bindings import Binding, SelfBinding, TextBinding, \
    AttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding, \
    safe_eval, safe_format, safe_format_with_stores, \
    extract_dependencies, ALLOWED_BUILTINS, Refrain

from basis.shared.store import Store
from basis.shared.base_component import BaseComponent


def client(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if PYSCRIPT:
            return func(*args, **kwargs)

    return wrapper


class Refrain:
    def __init__(self, component):
        self.__dict__['inner_dict'] = {}
        self.__dict__['component'] = component

    def __enter__(self):
        return self
    
    def __setattr__(self, name, value):
        self.inner_dict[name] = value

    def __exit__(self, exc_type, exc_val, exc_tb):

        inner_dict = self.inner_dict

        for k, v in inner_dict.items():
            self.component.__dict__[k] = v
        
        #print(f"inner_dict in Refrain of {self.component}: ", inner_dict)

        if len(inner_dict) > 0:
            self.component.react([k for k in inner_dict.keys()])


class Component(BaseComponent):

    # _registry = {} defined on BaseComponent
    _instance_registry = {}
    _pending_subscriptions = {}

    S = Store._registry
    C = _instance_registry

    @classmethod
    def _initialize_blueprint(cls):
        ###Client
        init_template = document.createElement('template')
        init_template.innerHTML = cls.__templatestr__
        setattr(cls, "__blueprint__", init_template)
    
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

    def __init__(self):
        super().__init__()

    @client
    def _get_nodes(self, element=None):

        if not element:
            element_to_walk = self.__template__
        else:
            element_to_walk = element

        walker = document.createTreeWalker(element_to_walk, window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT)

        nodes = []
        current_node = walker.nextNode()
        while current_node:
            nodes.append(current_node)
            current_node = walker.nextNode()

        return nodes

    @client
    def __init_selfbinding__(self):
        self_element = self.__template__.firstElementChild
        self.__dict__['__bindings__'].append(SelfBinding(component_instance=self, node=self_element))
        
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
                    child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)
                    node.__basis_mounted__ = True
                    node.appendChild(child_instance.__template__)
                
            if str.lower(element.tagName) == 'slot':
                slot_name = element.getAttribute('name')
                if not slot_name:
                    slot_is_default = True
                    slot_name = None
                else:
                    slot_is_default = False
                bindings.append(SlotBinding(component_instance=self, node=element, name=slot_name, is_default=slot_is_default))

            element_attrs = [a for a in element.getAttributeNames()]
            event_attrs = [a for a in element_attrs if a.startswith("on")]
            other_attrs = [a for a in element_attrs if not a.startswith("on")]
            
            for event_attr in event_attrs:
                event_attr_value = element.getAttribute(event_attr)
                if event_attr_value.startswith("{") and event_attr_value.endswith("}"):
                    event_attr_value = event_attr_value.strip("{}")
                    bindings.append(EventBinding(component_instance=self, node=element, event=event_attr, target_fn=event_attr_value))
                    fields.append(event_attr_value)

            for other_attr in other_attrs:
                
                #'if' attr
                if other_attr == 'if':
                    if_expr = element.getAttribute('if')
                    if_expr_clean = if_expr.removeprefix("{").removesuffix("}")
                    fieldnames = extract_dependencies(if_expr, ALLOWED_BUILTINS) 
                    anchor = document.createComment(f"if: {if_expr_clean}")
                    element.parentNode.insertBefore(anchor, element)
                    bindings.append(IfBinding(
                        component_instance=self, node=element, expr=if_expr_clean, anchor=anchor, is_visible=True, fields=fieldnames
                    ))
                    fields += fieldnames

                #'bind' attr
                elif other_attr == 'bind':
                    bind_attr_value = element.getAttribute('bind')
                    fieldnames = extract_dependencies(bind_attr_value, ALLOWED_BUILTINS)
                    if len(fieldnames) == 1:
                        field = fieldnames[0]
                        bindings.append(ModelBinding(component_instance=self, node=element, field=field))
                        fields.append(field)
                        tag_name = str.lower(element.tagName)
                        def create_update_handler(f, input_type):
                            def update_state(event):
                                if input_type == 'checkbox':
                                    setattr(self, f, event.target.checked)
                                else:
                                    setattr(self, f, event.target.value)
                            return ffi.create_proxy(update_state)
                        input_type = element.getAttribute('type') if element.hasAttribute('type') else 'text'
                        handler = create_update_handler(field, input_type)
                        if tag_name == 'input' and input_type in ['checkbox', 'radio']:
                            bound_event = 'change'
                        elif tag_name == 'select':
                            bound_event = 'change'
                        else:
                            bound_event = 'input'
                        element.addEventListener(bound_event, handler)
                        bindings.append(EventBinding(component_instance=self, node=element, event=f"{bound_event}", target_fn=handler))

                elif other_attr.startswith("{") and other_attr.endswith("}"):
                    other_attr_value = element.getAttribute(other_attr)
                    other_attr_no_braces = other_attr.strip("{}")
                    if other_attr_value == "":
                        other_attr_value = other_attr
                    other_attr_isboolean = True
                    element.removeAttribute(other_attr)
                    
                    fnames = [fname for _, fname, _, _ in formatter.parse(other_attr_value) if fname is not None]
                    has_expr = any(fnames)
                    if has_expr:
                        fieldnames = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
                        bindings.append(AttributeBinding(component_instance=self, node=element, attr=other_attr_no_braces, content=other_attr_value, fields=fieldnames, is_boolean=other_attr_isboolean))
                        fields += fieldnames

                else:
                    other_attr_value = element.getAttribute(other_attr)
                    other_attr_no_braces = other_attr
                    other_attr_isboolean = False
                
                    fnames = [fname for _, fname, _, _ in formatter.parse(other_attr_value) if fname is not None]
                    has_expr = any(fnames)
                    if has_expr:
                        fieldnames = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
                        bindings.append(AttributeBinding(component_instance=self, node=element, attr=other_attr_no_braces, content=other_attr_value, fields=fieldnames, is_boolean=other_attr_isboolean))
                        fields += fieldnames

            if 'for' in other_attrs:
                inlist_attr_value = element.getAttribute('in').strip("{}")
                for_attr_value = element.getAttribute('for')
                element_clone = element.cloneNode(True)
                if element.hasAttribute('key'):
                    bindings.append(KeyedLoopBinding(component_instance=self, node=element, clone=element_clone, parent=element.parentElement, collection=inlist_attr_value, item=for_attr_value, key=element.getAttribute('key')))
                else:
                    bindings.append(LoopBinding(component_instance=self, node=element, clone=element_clone, parent=element.parentElement, collection=inlist_attr_value, item=for_attr_value))

        elif node.nodeName == '#text':
            if node.parentElement and str.lower(node.parentElement.tagName) == 'style':
                return
            text_content = node.textContent
            fnames = [fname for _, fname, _, _ in formatter.parse(text_content) if fname is not None]
            has_expr = any(fnames)
            if has_expr:
                fieldnames = extract_dependencies(text_content, ALLOWED_BUILTINS)
                bindings.append(TextBinding(component_instance=self, node=node, content=text_content, fields=fieldnames))
                fields += fieldnames

        elif node.nodeName == '#comment':
            pass

        self.__bindings__.extend(bindings)

        for f in fields:
            if f not in self.__fields__:
                self.__fields__.append(f)


    @classmethod
    def mount_app(cls, container, replace=False):
        
        new_instance = cls.mount(container, replace)

        #fix styles
        styles = set()

        #client
        style_elem = document.createElement("style")

        for c in cls._registry.values():
            if hasattr(c, 'style'):
                if isinstance(c.style, str):
                    styles.add(c.style)
                elif inspect.isfunction(c.style):
                    if c.style.__doc__ is not None:
                        styles.add(c.style.__doc__)
                else:
                    raise
        
        #client
        style_elem.textContent = "\n".join(styles)
        #client
        container.prepend(style_elem)


        return new_instance
    
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
                for tag, component_cls in cls._registry.items():
                    if component_cls.__name__ == py_class_name:
                        print(f"Hydrating {py_class_name} via basis:hydrate event")
                        component_cls.hydrate(element)
                        return
                print(f"Warning: No Component found for '{py_class_name}' during hydration")

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
        super(Component, new_instance).__init__()
        new_instance.__dict__['_subscriptions'] = []

        if attributes:
            new_instance.__dict__.update(attributes)

        # Point _template at the existing live DOM root (firstElementChild of
        # the custom-element host, which is the server-rendered component root).
        live_root = container.firstElementChild or container
        new_instance.__dict__['_template'] = document.createElement('template')
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
        
    @classmethod
    def mount(cls, container, replace=False, **attributes):
        
        print(f"mount: starting mounting {cls}, with attributes: {attributes}")

        #If you need a reference to the individual nodes after they have been appended to the live DOM, you must get a copy or reference to them before you call appendChild() on the main parent.
        new_instance = cls.initialize(container, **attributes)
        new_template = new_instance.__template__
        self_element = new_instance.__element__
        
        #child_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, ChildBinding)]
        
        if replace:
            container.replaceWith(new_template)
            for k, v in attributes.items():
                self_element.setAttribute(k, v)

        else:
            container.appendChild(new_template)


        # connectedCallback fires here for every custom element now in the live DOM.
        # Any JS-injected template content lands in nodes whose authored children
        # we already moved to the fragments above - it is safely discarded by
        # Python's mount(replace=True) call below.

        event_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, EventBinding)]

        for binding in event_bindings:
            if isinstance(binding.target_fn, str):
                self_event_method = getattr(new_instance, binding.target_fn)
                binding.node.removeAttribute(binding.event)
                #client
                setattr(binding.element, binding.event, ffi.create_proxy(self_event_method))
            else:
                if binding.target_fn.__class__.__name__ == "JsProxy":
                    self_event_method = binding.target_fn
                    binding.node.removeAttribute(binding.event)
                    setattr(binding.element, binding.event, self_event_method)
                else:
                    raise Exception("C target_fn error:", binding)

        
        '''
        for binding in child_bindings: #custom elements
            #obtain attributes set on the <custom-element> tag from the JS component side (after mounting parent of course!)
            updated_child_node_attrs = {c.name: c.value for c in binding.node.attributes}

            custom_child_instance = binding.childclass.mount(binding.node, replace=True, **updated_child_node_attrs)
            binding.childinstance = custom_child_instance
            
        '''

        for nested_child in cls.get_nested_children():
            nested_child.mount(self_element, replace=False) #appendChild

        print(f"mount: finished mounting {cls}")

        return new_instance
    
    def fill_slots_aware(self, container):
        
        #default_slot_elements = self.__template__.querySelectorAll("slot:not([name])")
        #named_slot_elements = self.__template__.querySelectorAll("slot[name]")

        if not self.has_slots():
            pass
            return

        slot_bindings:list[SlotBinding] = [b for b in self.__bindings__ if isinstance(b, SlotBinding)]
        named_slot_bindings = [nb for nb in slot_bindings if not nb.is_default]
        default_slot_bindings = [db for db in slot_bindings if db.is_default]
        
        # Snapshot childNodes now (live NodeList changes as we move nodes)
        
        #client
        light_children = list(container.childNodes)

        # Partition by slot attribute value
        named_children: dict = {}
        default_children: list = []

        for child in light_children:
            slot_attr = None
            try:
                slot_attr = child.getAttribute('slot')
            except Exception:
                pass  # Text nodes don't have getAttribute

            if slot_attr:
                if slot_attr not in named_children:
                    named_children[slot_attr] = []
                named_children[slot_attr].append(child)
            else:
                default_children.append(child)
        
        print("Filling slots: default_children", default_children)
        print("Filling slots: named_children", named_children)

        for sb in named_slot_bindings:
            slot_node = sb.node
            slot_name = sb.name

            children_to_insert = named_children.get(slot_name, [])

            slot_node.replaceWith(*children_to_insert)

        # Fill each <slot> in order
        for sb in default_slot_bindings:
            slot_node = sb.node

            children_to_insert = default_children
            
            slot_node.replaceWith(*children_to_insert)

        all_slotted_nodes = [*named_children.values(), *default_children]

        nodes_to_bind = []
        for child in all_slotted_nodes:
            if hasattr(child, 'getAttributeNames'):
                nodes_to_bind.append(child)
                #client
                walker = document.createTreeWalker(child, window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT)
                n = walker.nextNode()
                while n:
                    nodes_to_bind.append(n)
                    n = walker.nextNode()
            elif hasattr(child, 'wholeText'):
                nodes_to_bind.append(child)

        if nodes_to_bind:
            self.bind_nodes(nodes_to_bind)

        return self.__element__


    @staticmethod
    def fill_slots(template, light_dom_source):

        default_slot_elements = template.querySelectorAll("slot:not([name])")
        named_slot_elements = template.querySelectorAll("slot[name]")
        
        if len(default_slot_elements) + len(named_slot_elements) == 0:
            return

        # Snapshot childNodes now (live NodeList changes as we move nodes)
        light_children = list(light_dom_source.childNodes)

        # Partition by slot attribute value
        named_children: dict = {}
        default_children: list = []

        for child in light_children:
            slot_attr = None
            try:
                slot_attr = child.getAttribute('slot')
            except Exception:
                pass  # Text nodes don't have getAttribute

            if slot_attr:
                if slot_attr not in named_children:
                    named_children[slot_attr] = []
                named_children[slot_attr].append(child)
            else:
                default_children.append(child)
        
        print(f"default_children", default_children)
        print("named_children", named_children)
        
        for slot_node in named_slot_elements:
            parent = slot_node.parentNode
            if parent is None:
                continue

            slot_name = slot_node.getAttribute('name')
            children_to_insert = named_children.get(slot_name, [])

            # Move each child before the <slot> placeholder
            for child in children_to_insert:
                parent.insertBefore(child, slot_node)

            # Remove the <slot> placeholder regardless of whether it was filled
            slot_node.remove()

        # Fill each <slot> in order
        for slot_node in default_slot_elements:
            parent = slot_node.parentNode
            if parent is None:
                continue

            children_to_insert = default_children
            
            # Move each child before the <slot> placeholder
            for child in children_to_insert:
                parent.insertBefore(child, slot_node)

            # Remove the <slot> placeholder regardless of whether it was filled
            slot_node.remove()

        return template
    
    def react(self, names):

        print(f"In react({names}) of {self}")
        
        text_bindings:list[TextBinding] = [tb for tb in self.__bindings__ if isinstance(tb, TextBinding)]
        attr_bindings:list[AttributeBinding] = [ab for ab in self.__bindings__ if isinstance(ab, AttributeBinding)]
        model_bindings:list[ModelBinding] = [mb for mb in self.__bindings__ if isinstance(mb, ModelBinding)]
        if_bindings:list[IfBinding] = [ib for ib in self.__bindings__ if isinstance(ib, IfBinding)]
        loop_bindings:list[LoopBinding] = [lb for lb in self.__bindings__ if isinstance(lb, LoopBinding)]
        keyed_loop_bindings:list[KeyedLoopBinding] = [lb for lb in self.__bindings__ if isinstance(lb, KeyedLoopBinding)]
        child_bindings:list[ChildBinding] = [cb for cb in self.__bindings__ if isinstance(cb, ChildBinding)]

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
                fragment = document.createDocumentFragment()
                
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
                            for c in lb.clone.attributes:
                                if c.name not in updated_child_node_attrs:
                                    
                                    has_expr = any(fname is not None for _, fname, _, _ in formatter.parse(c.value))
                                    if has_expr:
                                        val = safe_format(c.value, updated_child_node_attrs, ALLOWED_BUILTINS)
                                        updated_child_node_attrs[c.name] = val
                                    else:
                                        updated_child_node_attrs[c.name] = c.value
                            
                        # Update props and component reacts
                        for k, v in updated_child_node_attrs.items():
                            setattr(child_instance, k, v)
                            
                        fragment.appendChild(child_instance.__element__)
                        new_instances[k_val] = child_instance
                    else:
                        # New creation
                        try:
                            #client
                            cloned_element = document.importNode(lb.node, True)
                            cloned_element.removeAttribute('for')
                            cloned_element.removeAttribute('in')
                            cloned_element.removeAttribute('key')
                        except:
                            #client
                            cloned_element = document.importNode(lb.clone, True)
                            cloned_element.removeAttribute('for')
                            cloned_element.removeAttribute('in')
                            cloned_element.removeAttribute('key')
                            
                        updated_child_node_attrs = {lb.item: i}
                        rest_of_fields = [f for f in self.__fields__ if (f != lb.item) and (not inspect.isfunction(getattr(self, f)))]
                        for field in rest_of_fields:
                            updated_child_node_attrs[field] = getattr(self, field)
                        
                        if '-' in (tag:=str.lower(lb.clone.tagName)):
                            childcomponent_py = self.__class__._registry[tag]
                            for c in cloned_element.attributes:
                                if c.name not in updated_child_node_attrs:
                                    
                                    has_expr = any(fname is not None for _, fname, _, _ in formatter.parse(c.value))
                                    if has_expr:
                                        val = safe_format(c.value, updated_child_node_attrs, ALLOWED_BUILTINS)
                                        updated_child_node_attrs[c.name] = val
                                    else:
                                        updated_child_node_attrs[c.name] = c.value
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
                fragment = document.createDocumentFragment();

                for i in collection_value: #iterate through the collection
                    try:
                        #client
                        cloned_element = document.importNode(lb.node, True)
                        cloned_element.removeAttribute('for')
                        cloned_element.removeAttribute('in')
                    except:
                        #client
                        cloned_element = document.importNode(lb.clone, True)
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
                        updated_child_node_attrs = {c.name: c.value for c in new_cb.node.attributes}
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
            #print("attr_bindings_to_update", attr_bindings_to_update)
            if ab.node not in looped_nodes:                    
                if ab.attr not in ["in"]:
                    final_val = safe_format_with_stores(ab.content, self.__dict__, ALLOWED_BUILTINS, Store._registry, self.__class__._instance_registry)
                    #print("final_val", final_val)
                    if ab.is_boolean:
                        ab.node.toggleAttribute(ab.attr, bool(final_val))
                    else:
                        ab.node.setAttribute(ab.attr, final_val)

                else:
                    _, fname, _, _ = next(iter(formatter.parse(ab.content)))
                    evaluated_val = safe_eval(fname, self.__dict__, ALLOWED_BUILTINS)
                    final_val = json.dumps(evaluated_val)
                    ab.node.setAttribute(ab.attr, final_val)
                    
        for ib in if_bindings_to_update:
            expr_eval = bool(safe_eval(ib.expr, self.__dict__, ALLOWED_BUILTINS))
            #print("Expr_eval for IfBinding:", ib.expr, expr_eval, )
            if expr_eval == False:
                #print("REMOVING node from DOM based on IfBinding")
                ib.node.remove() #client
            else:
                #print("INSERTING node into DOM based on IfBinding")
                ib.anchor.after(ib.node) #client
            
            ib.is_visible = expr_eval
            