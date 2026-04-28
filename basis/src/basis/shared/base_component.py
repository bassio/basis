import inspect
from pathlib import Path
from pathlib import Path
from string import Formatter

from basis.shared.bindings import Binding, SelfBinding, TextBinding, \
    AttributeBinding, SelfAttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding, ComponentSubscription, \
    safe_eval, safe_format, safe_format_with_stores, \
    extract_dependencies, ALLOWED_BUILTINS, Refrain, \
    _process_event_attr_bindings, _process_standard_attr_bindings, \
    _process_text_bindings, _process_self_attr_bindings

from basis.shared.store import Store


class BaseComponent(object):

    _registry = {}
    _instance_registry = {}
    _pending_subscriptions = {}

    S = Store._registry
    C = _instance_registry

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
        self.__dict__['_deps'] = {}
        self.__dict__['__fields__'] = []
        self.__dict__['_subscriptions'] = []
        
    def add_binding(self, binding):

        self.__dict__['__bindings__'].append(binding)

        if hasattr(binding, 'fields'):
            for field in binding.fields:
                if field not in self._deps:
                    self._deps[field] = []
                if binding not in self._deps[field]:
                    self._deps[field].append(binding)

        if hasattr(binding, 'attr_bindings'):
            for cab in binding.attr_bindings:
                if hasattr(cab, 'fields'):
                    for field in cab.fields:
                        if field not in self._deps:
                            self._deps[field] = []
                        if cab not in self._deps[field]:
                            self._deps[field].append(cab)

    def remove_binding(self, binding):
        try:
            self.__dict__['__bindings__'].remove(binding)
        except ValueError:
            pass
        if hasattr(binding, 'fields'):
            for field in binding.fields:
                if field in self._deps and binding in self._deps[field]:
                    self._deps[field].remove(binding)
        if hasattr(binding, 'attr_bindings'):
            for cab in binding.attr_bindings:
                if hasattr(cab, 'fields'):
                    for field in cab.fields:
                        if field in self._deps and cab in self._deps[field]:
                            self._deps[field].remove(cab)
    
    def __init_selfbinding__(self):
        #template is ServerFragment on server and DocumentFragment on client
        template = self.__template__
        self_element = template.firstElementChild
        self.add_binding(SelfBinding(component_instance=self, node=self_element))
        
    def __init_selfbinding__(self):
        #template is ServerFragment on server and DocumentFragment on client
        template = self.__template__
        self_element = template.firstElementChild
        self.add_binding(SelfBinding(component_instance=self, node=self_element))
    
    def set_selfbinding(self, node):
        #template is ServerFragment on server and DocumentFragment on client
        sb = None

        for b in self.__bindings__:
            if isinstance(b, SelfBinding):
                sb = b
                break

        if sb:
            sb.node = node
        else:
            self.__bindings__.append(SelfBinding(component_instance=self, node=node))

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

        for b in bindings:
            self.add_binding(b)
    
    #
    def __init_self_attr_bindings__(self, **attrs_dict):
        for k, v in attrs_dict.items():
            self.__dict__[k] = v
            #self.__element__.setAttribute(k, v)

        attr_names = [k for k in attrs_dict.keys()]

        #print("attrs_dict", attrs_dict, self.__class__)

        attr_bindings, fields = _process_self_attr_bindings(self, attrs_dict)
        
        #print("self attr bindings:", attr_bindings)

        for b in attr_bindings:
            self.add_binding(b)
        self.__fields__.extend(fields)

    @classmethod
    def initialize(cls, container, **kwargs):
        new_instance = cls()

        new_instance.__init_selfbinding__()

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

    def _bind_node(self, node):

        formatter = Formatter()
        bindings=[]
        fields=[]

        if hasattr(node, 'getAttributeNames'): #confirm it is an ELEMENT not a TEXT node
            element = node

            element_attrs = [a for a in element.getAttributeNames()]
            event_attrs = [a for a in element_attrs if a.startswith("on")]
            other_attrs = [a for a in element_attrs if not a.startswith("on")]

            special_attrs = ["if", "for", "in", "key", "bind"]

            non_standard_attrs = [a for a in other_attrs if not a.startswith("on") and a in special_attrs]
            standard_attrs = [a for a in other_attrs if a not in non_standard_attrs]

            is_loop_template = 'for' in non_standard_attrs

            if '-' in element.tagName and not is_loop_template:
                tag = str.lower(element.tagName)
                childcomponent_py = self.__class__._registry[tag]
                dom_child_node_attrs = {a: element.getAttribute(a) for a in element.getAttributeNames()}

                if not getattr(node, '__basis_mounted__', False):
                    print("appending child.. with dom attrs:", dom_child_node_attrs)
                    child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)
                    node.__basis_mounted__ = True
                    node.appendChild(child_instance.__template__)
                
                    child_attr_bindings = [sab for sab in child_instance.__bindings__ \
                                        if isinstance(sab, SelfAttributeBinding)]
                    bindings.append(ChildBinding(component_instance=self, node=element, childclass=childcomponent_py, childinstance=child_instance, attr_bindings=child_attr_bindings))

            if str.lower(element.tagName) == 'slot':
                return

            if not is_loop_template:    
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
                fieldnames = extract_dependencies(if_expr, ALLOWED_BUILTINS) 
                
                #anchor = self._create_element(f"if: {if_expr_clean}")
                anchor = self._create_element(f"div")
                anchor.setAttribute("style", "display: contents;")
                anchor.setAttribute("data-if-expression", "{" + if_expr_clean + "}")
                
                #client
                element.parentNode.insertBefore(anchor, element)
                bindings.append(IfBinding(
                    component_instance=self, node=element, expr=if_expr_clean, anchor=anchor, is_visible=True, fields=fieldnames
                ))
                fields += fieldnames

            #'bind' attr
            if 'bind' in non_standard_attrs and not is_loop_template:
                bind_attr_value = element.getAttribute('bind')
                fieldnames = extract_dependencies(bind_attr_value, ALLOWED_BUILTINS)
                if len(fieldnames) == 1:
                    field = fieldnames[0]
                    bindings.append(ModelBinding(component_instance=self, node=element, field=field))
                    fields.append(field)
                    tag_name = str.lower(element.tagName)
                    input_type = element.getAttribute('type') if element.hasAttribute('type') else 'text'

                    handler = self._create_update_handler(field, input_type)
                    self.__dict__['bind_handler'] = handler

                    if tag_name == 'input' and input_type in ['checkbox', 'radio']:
                        bound_event = 'change'
                    elif tag_name == 'select':
                        bound_event = 'change'
                    else:
                        bound_event = 'input'
                    
                    #client
                    element.addEventListener(bound_event, handler)
                    bindings.append(EventBinding(component_instance=self, node=element, event=f"on{bound_event}", target_fn='bind_handler'))

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

        for b in bindings:
            self.add_binding(b)

        for f in fields:
            if f not in self.__fields__:
                self.__fields__.append(f)

    def bind_nodes(self, nodes):
        for node in nodes:
            self._bind_node(node)

    def __init_bindings__(self, root_element=None):

        print(f"__init_bindings__ of {self.__class__}")

        nodes = self._get_nodes(element=root_element)

        self.bind_nodes(nodes)

        print(f"Bindings of {self.__class__}:", self.__bindings__)
        
        # add to component instance registry if it is has an id
        self_element = self.__element__
        if self_element.hasAttribute('id'):
            component_id = self_element.getAttribute('id')
            self.__class__._instance_registry[component_id] = self
            
            if component_id in self.__class__._pending_subscriptions:
                for subscribing_component_instance, attr_name in self.__class__._pending_subscriptions.pop(component_id):
                    self.add_subscription(subscribing_component_instance, attr_name)
                    subscribed_field = f"#{component_id}.{attr_name}"
                    with subscribing_component_instance.refrain() as refrained:
                        #setattr(refrained, subscribed_field, self)
                        setattr(refrained, subscribed_field, getattr(self, attr_name))


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
                    
                    store_instance.add_subscription(self, attr_name)
                
                elif field.startswith("#"):
                    component_name, attr_name = field.strip("#").split(".")
                    
                    if component_name in self.__class__._instance_registry:
                        component_instance = self.__class__._instance_registry[component_name]

                        setattr(refrained, field, component_instance)
                        
                        component_instance.add_subscription(self, attr_name)

                    else:
                        
                        new_subscription = ComponentSubscription(self, attr_name)

                        print("New ComponentSubscription:", new_subscription)

                        if component_name in self.__class__._pending_subscriptions:
                            self.__class__._pending_subscriptions[component_name].append(new_subscription)
                        else:
                            self.__class__._pending_subscriptions[component_name] = [new_subscription]
                else:
                    self.react([field])

    @property
    def __element__(self):
        for binding in self.__bindings__:
            if isinstance(binding, SelfBinding):
                return binding.node
        return None

    def fill_slots(self, container):
        
        slot_bindings:list[SlotBinding] = [b for b in self.__bindings__ if isinstance(b, SlotBinding)]

        if not len(slot_bindings):
            return

        named_slot_bindings = [nb for nb in slot_bindings if not nb.is_default]
        default_slot_bindings = [db for db in slot_bindings if db.is_default]
        
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
        
        #print("Filling slots: default_children", default_children)
        #print("Filling slots: named_children", named_children)

        for sb in named_slot_bindings:
            slot_node = sb.node
            slot_name = sb.name

            named_children_to_insert = named_children.get(slot_name, [])

            slot_node.replaceWith(*named_children_to_insert)
            
        # Fill each <slot> in order
        for sb in default_slot_bindings:
            slot_node = sb.node

            default_children_to_insert = default_children
            
            slot_node.replaceWith(*default_children_to_insert)


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
                print("and now reacting ..")
                self.react([name])

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        
        print(f"mount: starting mounting {cls}, with attributes: {attributes}")

        container = container

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
                

        #print("nested:", cls.get_nested_children())
        for nested_child in cls.get_nested_children():
            child_instance = nested_child.mount(self_element, replace=False) #appendChild
            #child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)
            #node.__basis_mounted__ = True
            #node.appendChild(child_instance.__template__)

            #child_attr_bindings = [sab for sab in child_instance.__bindings__ \
            #                    if isinstance(sab, SelfAttributeBinding)]
            child_attr_bindings = []

            new_instance.__bindings__.append(ChildBinding(component_instance=new_instance,
                                                          node=self_element,
                                                          childclass=nested_child,
                                                          childinstance=child_instance,
                                                          attr_bindings=child_attr_bindings))

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
            #print("members :::", members)

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

    def get_child_bindings(self, recursive=False):

        first_level_bindings = [c for c in self.__bindings__ if isinstance(c, ChildBinding)]

        for cb in first_level_bindings:
            yield cb
            if recursive:
                yield from cb.childinstance.get_child_bindings(recursive=True)

    def get_bindings(self, recursive=False):
        
        first_level_bindings = [c for c in self.__bindings__]
        first_level_child_bindings = [c for c in first_level_bindings if isinstance(c, ChildBinding)]

        for b in first_level_bindings:
            yield b
        
        if recursive:
            for cb in first_level_child_bindings:
                yield from cb.childinstance.get_bindings(recursive=True)

    def refrain(self):
        ref_context = Refrain(self)
        return ref_context

    def add_subscription(self, component_instance, attr_name:str):
        if (component_instance, attr_name) not in self._subscriptions:
            new_subscription = ComponentSubscription(component_instance, attr_name)

            self.__dict__['_subscriptions'].append(new_subscription)

            if attr_name not in self._deps:
                self._deps[attr_name] = []

            if new_subscription not in self._deps[attr_name]:
                self._deps[attr_name].append(new_subscription)

        print(f"_subscriptions of {self.__class__}: ", self.__dict__['_subscriptions'])

    def remove_subscription(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]

    def react(self, names:list[str]):

        if isinstance(names, str):
            raise Exception("Please pass only a list of strings to react().")

        print(f"In react({names}) of {self.__class__}")
        bindings_to_update = []
        subscriptions_to_update = []

        dependencies = set(names).intersection(set(self._deps.keys()))
        
        for name in dependencies:
            print("_deps:", self._deps[name])
            for binding in self._deps[name]:
                if binding not in bindings_to_update:
                    bindings_to_update.append(binding)

        for name in dependencies:
            for sub in self.__dict__['_subscriptions']:
                subscribing_component_instance, sub_attr_name = sub #deconstruct the ComponentSubscription
                if name == sub_attr_name:
                    subscriptions_to_update.append(sub)
                
        print("bindings_to_update: ", bindings_to_update)
        print("all _deps: ", self._deps)
        
        for binding in bindings_to_update:
            if hasattr(binding, 'update'):
                binding.update()
            elif isinstance(binding, ComponentSubscription):
                sub = binding
                self_component_id = self.__element__.getAttribute("id")
                sub.component_instance.react([f"#{self_component_id}.{sub.attr}"])
