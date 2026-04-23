import inspect
import json
from pathlib import Path
from pathlib import Path
from string import Formatter

from basis.shared.bindings import Binding, SelfBinding, TextBinding, \
    AttributeBinding, SelfAttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding, \
    safe_eval, safe_format, safe_format_with_stores, \
    extract_dependencies, ALLOWED_BUILTINS, Refrain, \
    _process_event_attr_bindings, _process_standard_attr_bindings, \
    _process_text_bindings, _process_self_attr_bindings

from basis.shared.store import Store

try:
    from basis.server.components.element import Element as _ServerElement

    PYSCRIPT = False
    
except ImportError:

    PYSCRIPT = True

class BaseComponent(object):
    _registry = {}

    @classmethod
    def from_template(cls, templatestr, **kwargs):
        return type(
            f"{cls.__name__}Subclass",
            (cls,), 
            {"template": templatestr,
             **kwargs
            }
        )

    @classmethod
    def __file__(cls):
        try:
            return Path(inspect.getfile(cls))
        except OSError:
            return Path.cwd()

    @classmethod
    def _get_template_string(cls) -> str:
        if hasattr(cls, 'template'):
            if inspect.isfunction(cls.template):
                templatestr = cls.template.__doc__
            elif isinstance(cls.template, str):
                templatestr = cls.template
        elif cls.__doc__:
            templatestr = cls.__doc__
        elif (html_file:=cls.__file__().with_suffix(".html").with_stem(cls.__file__().parent.name)).exists():
            with open(html_file, "r") as htm:
                templatestr = htm.read()
        else:
            return ""
        
        return templatestr
    
    @classmethod
    def _set_style_string(cls):
        css_file = cls.__file__().with_suffix(".css").with_stem(cls.__file__().parent.name)
        if css_file.exists():
            with open(css_file, "r") as css:
                setattr(cls, "style", css.read())

    @classmethod
    def _initialize_blueprint(cls):
        raise NotImplementedError()
    
    @classmethod
    def _register_component_subclass(cls):
        if hasattr(cls, '__tag__') and "-" in cls.__tag__:
            tag = cls.__tag__
        else:
            tag = cls.__name__
            cls.__tag__ = tag

        cls._registry[tag] = cls

    @classmethod
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        
        templatestr = cls._get_template_string()
        
        if not templatestr:
            return
        
        setattr(cls, "__templatestr__", templatestr)

        cls._set_style_string()
        
        ###Client
        cls._initialize_blueprint()
        
        cls._register_component_subclass()


    def __init__(self):
        super().__init__()
        self.__dict__['__bindings__'] = []
        self.__dict__['__fields__'] = []
        self.__dict__['_subscriptions'] = []
        self.__init_selfbinding__()
    
    def __init_selfbinding__(self):
        #template is ServerFragment on server and DocumentFragment on client
        template = self.__template__
        self_element = template.firstElementChild
        self.__dict__['__bindings__'].append(SelfBinding(component_instance=self, node=self_element))
    
    def _get_nodes(self, element=None):
        return NotImplementedError

    #
    def __init_slot_bindings__(self):
        nodes = self._get_nodes()

        bindings = []

        for node in nodes:
            if hasattr(node, 'getAttributeNames') \
            and str.lower(node.tagName) == 'slot':
                slot_name = node.getAttribute('name')

                if not slot_name:
                    slot_is_default = True
                    slot_name = None
                else:
                    slot_is_default = False

                bindings.append(SlotBinding(component_instance=self, node=node, name=slot_name, is_default=slot_is_default))

        self.__bindings__.extend(bindings)
    
    #
    def __init_self_attr_bindings__(self, **attrs_dict):
        for k, v in attrs_dict.items():
            self.__dict__[k] = v
            #self.__element__.setAttribute(k, v)

        attr_names = [k for k in attrs_dict.keys()]

        print("attrs_dict", attrs_dict, self.__class__)

        attr_bindings, fields = _process_self_attr_bindings(self, attrs_dict)
        
        print("self attr bindings:", attr_bindings)

        self.__bindings__.extend(attr_bindings)
        self.__fields__.extend(fields)

    @classmethod
    def initialize(cls, container, **kwargs):
        new_instance = cls()

        #if len(kwargs):
        #    new_instance.__dict__.update(**kwargs)

        new_instance.__init_self_attr_bindings__(**kwargs)
        
        new_instance.__init_slot_bindings__()

        new_instance.fill_slots(container)

        new_instance.__init_bindings__()

        new_instance.__init_fields__()

        with new_instance.refrain() as refrained:
            for k, v in kwargs.items():
                setattr(refrained, k, v)

        return new_instance

    def _create_function_proxy(self, f):
        return f

    #@server
    def _create_update_handler(self, f, input_type):

        def update_state(event):
            if input_type == 'checkbox':
                setattr(self, f, event.target.checked)
            else:
                setattr(self, f, event.target.value)

        return update_state

    def bind_nodes(self, nodes):
        for node in nodes:
            self._bind_node(node)

    def __init_bindings__(self):

        print(f"__init_bindings__ of {self.__class__}")

        nodes = self._get_nodes()

        self.bind_nodes(nodes)

        print(f"Bindings of {self.__class__}:", self.__bindings__)
        
        # add to component instance registry if it is has an id
        self_element = self.__element__
        if self_element.hasAttribute('id'):
            component_id = self_element.getAttribute('id')
            self.__class__._instance_registry[component_id] = self
            
            if component_id in self.__class__._pending_subscriptions:
                for subscribing_component_instance, attr_name in self.__class__._pending_subscriptions.pop(component_id):
                    self.subscribe(subscribing_component_instance, attr_name)
                    subscribed_field = f"#{component_id}.{attr_name}"
                    with subscribing_component_instance.refrain() as refrained:
                        setattr(refrained, subscribed_field, self)


    def __init_fields__(self):
        cls = self.__class__
        
        print(f"__init_fields__ : {cls} fields: ", self.__fields__)

        fields_on_class = [attr for attr in self.__fields__ \
                                if (attr not in self.__dict__) and \
                                (attr in cls.__dict__) \
                                and (not inspect.isfunction(getattr(cls, attr)))]
        
        print(f"fields_on_class of {cls} : ", fields_on_class)

        if fields_on_class:
            with self.refrain() as refrained:
                for field in fields_on_class:
                    print(f"setting attr from class {self.__class__.__name__} on the instance: {field}, with value {cls.__dict__[field]}")
                    setattr(refrained, field, cls.__dict__[field])
                    self.__fields__.append(field)
        
        with self.refrain() as refrained:

            for field in self.__fields__:
                if field.startswith("$"):
                    
                    store_name, attr_name = field.strip("$").split(".")
                    store_instance = Store._registry[store_name]
                    
                    setattr(refrained, field, store_instance)
                    
                    store_instance.subscribe(self, attr_name)
                
                elif field.startswith("#"):
                    component_name, attr_name = field.strip("#").split(".")
                    
                    if component_name in self.__class__._instance_registry:
                        component_instance = self.__class__._instance_registry[component_name]

                        setattr(refrained, field, component_instance)
                        
                        component_instance.subscribe(self, attr_name)

                    else:

                        if component_name in self.__class__._pending_subscriptions:
                            self.__class__._pending_subscriptions[component_name].append((self, attr_name))
                        else:
                            self.__class__._pending_subscriptions[component_name] = [(self, attr_name)]
                else:
                    self.react([field])

    @property
    def __element__(self):
        for binding in self.__bindings__:
            match binding:
                case SelfBinding:
                    return binding.node
        return None

    def fill_slots(self, container):
        
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

        # Server-side only: after all children have been moved into their
        # slot positions inside the component's own template, clear the
        # container's children list so they are not rendered a second time
        # as direct children of the host element (e.g. <sign-component>).
        # On the client, the browser DOM does this automatically when nodes
        # are moved via replaceWith / insertBefore.
        try:
            if not PYSCRIPT:
                from basis.server.components.element import Element as _ServerElement
                if isinstance(container, _ServerElement):
                    container.children = []
        except ImportError:
            pass

        return self.__element__
    
    def __getattribute__(self, name):
        try:
            if name.startswith("$"):
                store_name, attr_name = name.strip("$").split(".")
                val = getattr(self.__class__.S[store_name], attr_name)
                return val
            elif name.startswith("#"):
                component_name, attr_name = name.strip("#").split(".")
                val = getattr(self.__class__._instance_registry[component_name], attr_name)
                return val
            else:
                return super().__getattribute__(name)

        except:
                return super().__getattribute__(name)

    def __setattr__(self, name, value):
        try:
            old_value = self.__dict__[name]
        except KeyError: #setting a new attribute
            old_value = None

        super().__setattr__(name, value)

        if not name.startswith("$") or name.startswith("#"):
            super().__setattr__(name, value)

        #check for change
        if value != old_value:
            if name in self.__fields__:
                print(f"__setattr__ on {self.__class__} called for {name}, old value {old_value}, new value {value}")
                #print("reacting")
                self.react([name])

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        
        print(f"mount: starting mounting {cls}, with attributes: {attributes}")

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


        event_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, EventBinding)]

        for binding in event_bindings:
            if isinstance(binding.target_fn, str):
                event_method = getattr(new_instance, binding.target_fn)
                binding.node.removeAttribute(binding.event)
                event_method_final = new_instance._create_function_proxy(event_method)
                setattr(binding.element, binding.event, event_method_final)
                
            else:
                self_event_method = binding.target_fn
                binding.node.removeAttribute(binding.event)
                setattr(binding.element, binding.event, self_event_method)
                

        for nested_child in cls.get_nested_children():
            nested_child.mount(self_element, replace=False) #appendChild

 
        print(f"mount: finished mounting {cls}")

        return new_instance


    @classmethod
    def mount_app(cls, container, replace=False):
        
        new_instance = cls.mount(container, replace)

        #fix styles
        styles = set()

        #client
        style_elem = cls._create_element("style")

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
    def get_nested_children(cls):
        nested = []

        cls_attrs_order = {key: i for i, key in enumerate(cls.__dict__.keys())}

        if len(cls_attrs_order) > 0:

            members = inspect.getmembers_static(cls)

            subclass_members = [(k, v) for k, v in members
                                if inspect.isclass(v) \
                                and v.__module__ == cls.__module__ \
                                and v.__qualname__.startswith(cls.__qualname__ + '.') \
                                and issubclass(v, BaseComponent)
                                ]
            
            sorted_members = []

            for sc_name, sc in cls.__dict__.items():
                if (sc_name, sc) in subclass_members:
                    sorted_members.append(sc)

            return sorted_members
                   
        else:
            return []

    def has_slots(self):
        for binding in self.__bindings__:
            if isinstance(binding, SlotBinding):
                return True
        return False
    
    def refrain(self):
        ref_context = Refrain(self)
        return ref_context

    def subscribe(self, component_instance, attr_name:str):
        if (component_instance, attr_name) not in self._subscriptions:
            self.__dict__['_subscriptions'].append((component_instance, attr_name))

        print(f"_subscriptions of {self.__class__}: ", self.__dict__['_subscriptions'])

    def unsubscribe(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]

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
                lb.parent.replaceChildren(fragment)
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
            lb.parent.replaceChildren(fragment)

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

