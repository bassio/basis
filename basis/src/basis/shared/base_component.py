import inspect
from pathlib import Path
from string import Formatter

from basis.shared.bindings import BindingBlueprint, Binding, SelfBinding, TextBinding, \
    AttributeBinding, SelfAttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, KeyedLoopBinding, SlotBinding, ComponentSubscription, \
    desugar_expression, safe_eval, safe_format, safe_format_with_stores, \
    ALLOWED_BUILTINS, Refrain, \
    _process_self_attr_bindings
from basis.shared.bindings import extract_dependencies
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
    def _analyze_template(cls):
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
        super().__init_subclass__()
        
        templatestr = cls._get_template_string()
        
        if not templatestr:
            return
        
        setattr(cls, "__templatestr__", templatestr)

        cls._set_style_string()

        setattr(cls, "__binding_blueprints__", [])

        #set kwargs
        setattr(cls, "_creation_kwargs", kwargs)

        ###Client
        cls._initialize_blueprint()

        cls._analyze_creation_args()

        cls._analyze_template()

        cls._register_component_subclass()


    def __init__(self):
        super().__init__()
        self.__dict__['__bindings__'] = []
        self.__dict__['_selfattr_bindings'] = {}
        self.__dict__['_deps'] = {}
        self.__dict__['__fields__'] = []
        self.__dict__['_subscriptions'] = []
        
    def __init_selfbinding__(self):
        #template is ServerFragment on server and DocumentFragment on client
        template = self.__template__
        self_element = template.firstElementChild
        self.add_binding(SelfBinding(component_instance=self, node=self_element))
        setattr(self_element, '__basis_instance__', self)
        
    #
    def _get_instance_nodes(self):
        """Walk the template once and cache the nodes for index-based lookup."""
        if '_nodes' not in self.__dict__:
            self.__dict__['_nodes'] = self.__class__._get_nodes(self.__template__)
        return self.__dict__['_nodes']

    def __init_slot_bindings__(self):
        nodes = self._get_instance_nodes()
        for blueprint in self.__class__.__binding_blueprints__:
            if blueprint.binding_class == SlotBinding:
                node = nodes[blueprint.node_index]
                binding = SlotBinding.from_blueprint(self, node, blueprint)
                if binding:
                    self.add_binding(binding)
    
    #
    def __init_self_attr_bindings__(self, **attrs_dict):
        for k, v in attrs_dict.items():
            self.__dict__[k] = v
            #self.__element__.setAttribute(k, v)

        attr_names = [k for k in attrs_dict.keys()]

        #print("attrs_dict", attrs_dict, self.__class__)

        #attr_bindings, fields = _process_self_attr_bindings(self, attrs_dict)
        
        self_attr_binding_blueprints = [bp for bp in self.__class__.__binding_blueprints__
                                        if bp.binding_class == SelfAttributeBinding]

        attr_bindings = []

        for bp in self_attr_binding_blueprints:
            attr_bindings.append(SelfAttributeBinding.from_blueprint(self, bp.node, bp))

        for b in attr_bindings:
            self.add_binding(b)
            self.__dict__['_selfattr_bindings'][b.attr] = b

    @classmethod
    def initialize(cls, container, **kwargs):

        cls_dict = dict(cls.__dict__)
        
        new_cls = type(cls.__name__, (cls,), cls_dict, **kwargs)

        new_instance = new_cls()

        new_instance.__init_selfbinding__()

        #new_instance.__init_self_attr_bindings__(**kwargs)
        
        new_instance.__init_slot_bindings__()

        new_instance.fill_slots(container)

        new_instance.__init_bindings__()

        new_instance.__init_fields__()

        with new_instance.refrain() as refrained:
            for k, v in kwargs.items():
                setattr(refrained, k, v)

        return new_instance

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

    def add_binding(self, binding):

        self.__dict__['__bindings__'].append(binding)

        if hasattr(binding, 'fields'):
            for field in binding.fields:
                if field not in self._deps:
                    self._deps[field] = []
                    if field not in self.__fields__:
                        self.__fields__.append(field)
                if binding not in self._deps[field]:
                    self._deps[field].append(binding)

    def remove_binding(self, binding):
        try:
            self.__dict__['__bindings__'].remove(binding)
        except ValueError:
            pass
        if hasattr(binding, 'fields'):
            for field in binding.fields:
                if field in self._deps and binding in self._deps[field]:
                    self._deps[field].remove(binding)
    

    @classmethod
    def _get_nodes(cls, element):
        raise NotImplementedError()

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
    
    @classmethod
    def _analyze_creation_args(cls):

        blueprints = []

        for k, v in cls._creation_kwargs.items():

            if k.startswith("{") and k.endswith("}"):
                attr_no_braces = k.strip("{}")
                attr_isboolean = True

                if (v == "") or (v == None):
                    attr_value = k
            
            else:
                attr_no_braces = k
                attr_isboolean = False
                attr_value = v

            try:
                fieldnames, ast_trees_dict = extract_dependencies(attr_value, ALLOWED_BUILTINS)

                if len(fieldnames):

                    kwargs = {}
                    kwargs['attr'] = attr_no_braces
                    kwargs['content'] = attr_value
                    kwargs['fields'] = fieldnames
                    kwargs['is_boolean'] = attr_isboolean

                    bp = BindingBlueprint(binding_class=SelfAttributeBinding,
                                        node_index = -1,
                                        kwargs = kwargs,
                                        ast_trees=ast_trees_dict)
                    blueprints.append(bp)

            except:
                continue
        
        #print("####### blueprints", cls._creation_kwargs)

        cls.__binding_blueprints__.extend(blueprints)

    @classmethod
    def _analyze_node(cls, node, node_index):

        blueprints = []
        formatter = Formatter()

        if hasattr(node, 'getAttributeNames'): # ELEMENT node
            element = node

            tag_name = element.tagName.lower()
            if tag_name in ['style', 'script']:
                return []

            element_attrs = list(element.getAttributeNames())
            event_attrs = [a for a in element_attrs if a.startswith("on")]
            other_attrs = [a for a in element_attrs if not a.startswith("on")]

            special_attrs = ["if", "for", "in", "key", "bind"]
            non_standard_attrs = [a for a in other_attrs if a in special_attrs]
            standard_attrs = [a for a in other_attrs if a not in non_standard_attrs]

            is_loop_template = 'for' in non_standard_attrs

            # Process 'if'
            if 'if' in non_standard_attrs:
                if_expr = element.getAttribute('if')
                if_expr_clean = if_expr.removeprefix("{").removesuffix("}")
                fieldnames, trees_dict = extract_dependencies(if_expr, ALLOWED_BUILTINS)
                
                blueprints.append(BindingBlueprint(
                    binding_class=IfBinding,
                    node_index=node_index,
                    kwargs={'expr': if_expr_clean, 'fields': fieldnames, 'is_visible': True},
                    ast_trees=trees_dict
                ))

            # Process 'for' (Loop)
            if 'for' in non_standard_attrs:
                inlist_attr_value = element.getAttribute('in').strip("{}")
                for_attr_value = element.getAttribute('for')
                fieldnames, trees_dict = extract_dependencies(element.getAttribute('in'), ALLOWED_BUILTINS)
                
                binding_class = KeyedLoopBinding if 'key' in non_standard_attrs else LoopBinding
                kwargs = {'item': for_attr_value, 'collection': inlist_attr_value}
                if 'key' in non_standard_attrs:
                    kwargs['key'] = element.getAttribute('key')
                
                blueprints.append(BindingBlueprint(
                    binding_class=binding_class,
                    node_index=node_index,
                    kwargs=kwargs,
                    ast_trees=trees_dict
                ))
            
            # Process 'bind'
            if 'bind' in non_standard_attrs and not is_loop_template:
                bind_attr_value = element.getAttribute('bind')
                fieldnames, trees_dict = extract_dependencies(bind_attr_value, ALLOWED_BUILTINS)
                if len(fieldnames) == 1:
                    field = fieldnames[0]
                    blueprints.append(BindingBlueprint(
                        binding_class=ModelBinding,
                        node_index=node_index,
                        kwargs={'field': field},
                        ast_trees=trees_dict
                    ))
                    # Also need the event binding for the input
                    tag_name = str.lower(element.tagName)
                    input_type = element.getAttribute('type') if element.hasAttribute('type') else 'text'
                    if tag_name == 'input' and input_type in ['checkbox', 'radio']:
                        bound_event = 'change'
                    elif tag_name == 'select':
                        bound_event = 'change'
                    else:
                        bound_event = 'input'
                    
                    blueprints.append(BindingBlueprint(
                        binding_class=EventBinding,
                        node_index=node_index,
                        kwargs={'event': f"on{bound_event}", 'target_fn': 'bind_handler'}
                    ))

            # Process Components (ChildBinding)
            if '-' in element.tagName and not is_loop_template:
                tag = str.lower(element.tagName)

                blueprints.append(BindingBlueprint(
                    binding_class=ChildBinding,
                    node_index=node_index,
                    kwargs={'tag': tag}
                ))

            # Process standard attributes and events (if not a loop template)
            if not is_loop_template:
                # Events
                for event_attr in event_attrs:
                    val = element.getAttribute(event_attr)
                    if val.startswith("{") and val.endswith("}"):
                        fieldnames, trees_dict = extract_dependencies(val, ALLOWED_BUILTINS)
                        
                        if len(fieldnames) == 1:
                            field = fieldnames[0]
                            
                            blueprints.append(BindingBlueprint(
                                binding_class=EventBinding,
                                node_index=node_index,
                                kwargs={'event': event_attr, 'target_fn': field},
                                ast_trees=trees_dict
                            ))
                
                # Standard attributes
                for attr in standard_attrs:
                    if attr.startswith("{") and attr.endswith("}"):
                        attr_no_braces = attr.strip("{}")
                        attr_value = element.getAttribute(attr)
                        attr_isboolean = True
            
                        if (attr_value == "") or (attr_value == None):
                            attr_value = attr

                    else:
                        attr_no_braces = attr
                        attr_value = element.getAttribute(attr)
                        attr_isboolean = False

                        fieldnames, trees_dict = extract_dependencies(attr_value, ALLOWED_BUILTINS)
                        
                        if len(fieldnames):
                            blueprints.append(BindingBlueprint(
                                binding_class=AttributeBinding,
                                node_index=node_index,
                                kwargs={'attr': attr_no_braces,
                                        'content': attr_value,
                                        'fields': fieldnames,
                                        'is_boolean': attr_isboolean},
                                ast_trees=trees_dict
                            ))

            # Special case for Slot
            if str.lower(element.tagName) == 'slot':
                slot_name = element.getAttribute('name')
                blueprints.append(BindingBlueprint(
                    binding_class=SlotBinding,
                    node_index=node_index,
                    kwargs={'name': slot_name, 'is_default': not bool(slot_name)}
                ))

        elif node.nodeName == '#text':
            parent = getattr(node, 'parentNode', None) or getattr(node, 'parentElement', None)
            if parent and hasattr(parent, 'tagName') and parent.tagName.lower() in ['style', 'script']:
                return []
                
            text_content = node.textContent
            fieldnames, trees_dict = extract_dependencies(text_content, ALLOWED_BUILTINS)

            if len(fieldnames):
                blueprints.append(BindingBlueprint(
                    binding_class=TextBinding,
                    node_index=node_index,
                    kwargs={'content': text_content, 'fields': fieldnames},
                    ast_trees=trees_dict
                ))

        return blueprints

    def __init_bindings__(self):
        print(f"__init_bindings__ of {self.__class__}")
        
        #print("__binding_blueprints__", self.__class__.__binding_blueprints__)
        
        nodes = self._get_instance_nodes()

        for blueprint in self.__class__.__binding_blueprints__:
            if blueprint.binding_class == SlotBinding:
                continue
            elif blueprint.binding_class == SelfAttributeBinding:
                binding = blueprint.binding_class.from_blueprint(self, self.__element__, blueprint)
                self.add_binding(binding)
            else:
                node = nodes[blueprint.node_index]
                binding = blueprint.binding_class.from_blueprint(self, node, blueprint)
                if binding:
                    self.add_binding(binding)

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


        with self.refrain() as refrained:

            for field in fields_on_class:
                print(f"setting attr from class {self.__class__.__name__} on the instance: {field}, with value {cls.__dict__[field]}")
                setattr(refrained, field, cls.__dict__[field])

            for field in self.__fields__:
                if field.startswith("$"):
                    
                    if "." in field:
                        store_name, attr_name = field.strip("$").split(".")
                        store_instance = Store._registry[store_name]
                    
                        setattr(refrained, field, store_instance)
                        store_instance.add_subscription(self, attr_name)

                    else:
                        store_name = field.strip("$")
                        attr_name = ""

                        store_instance = Store._registry[store_name]

                        setattr(refrained, field, store_instance)
                        #store_instance.add_subscription(self, attr_name) ?could we subscribe to "" attr (the whole store)
                
                elif field.startswith("#"):
                    if "." in field:
                        component_name, attr_name = field.strip("#").split(".")

                        if component_name in self.__class__._instance_registry:
                            component_instance = self.__class__._instance_registry[component_name]

                            setattr(refrained, field, component_instance)
                            
                            component_instance.add_subscription(self, attr_name)

                        else:
                            
                            new_subscription = ComponentSubscription(component_instance=self,
                                                                     attr=attr_name)

                            if component_name in self.__class__._pending_subscriptions:
                                self.__class__._pending_subscriptions[component_name].append(new_subscription)
                            else:
                                self.__class__._pending_subscriptions[component_name] = [new_subscription]
                
                    else:
                        # no-op if only "#component_id" with no attribute specified
                        pass

                        
                else:
                    refrained.force_react(field)


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

        print(f"inside __setattr__ of {self} for the attr {name}")

        if name.startswith("$"):
            store_name, attr_name = name.strip("$").split(".")
            store_instance = self.__class__.S[store_name]
            
            try:
                old_value = store_instance.__dict__[attr_name]
            except KeyError:
                old_value = None
            
            print(f"calling __setattr__ on {store_instance} called for {attr_name}, old value {old_value}, new value {value}")
            setattr(store_instance, attr_name, value)

        elif name.startswith("#"):
            component_name, attr_name = name.strip("#").split(".")
            component_instance = self.__class__.C[component_name]

            try:
                old_value = component_instance.__dict__[attr_name]
            except KeyError:
                old_value = None
            
            setattr(component_instance, attr_name, value)
            print(f"calling __setattr__ on {component_instance} called for {attr_name}, old value {old_value}, new value {value}")
            #the component_instance should then react from its instance !

        else:
            try:
                old_value = self.__dict__[name]
                print(f"old_value of {name}", old_value)
            except KeyError: #setting a new attribute
                old_value = None

            self.__dict__[name] = value

            #check for change
            if value != old_value:
                print(f"__setattr__ on {self} called for {name}, old value {old_value}, new value {value}")
                print("and now reacting ..")
                self.react([name])

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        
        print(f"mount: starting mounting {cls}, with attributes: {attributes}")

        container = container

        new_instance = cls.initialize(container, **attributes)
        new_template = new_instance.__template__
        self_element = new_instance.__element__
                
        if replace:
            container.replaceWith(new_template)
            for k, v in attributes.items():
                self_element.setAttribute(k, v)

        else:
            container.appendChild(new_template)


        #print("nested:", cls.get_nested_children())
        for nested_child in cls.get_nested_children():
            child_instance = nested_child.mount(self_element, replace=False) #appendChild

            new_instance.add_binding(ChildBinding(component_instance=new_instance,
                                                          node=self_element,
                                                          childclass=nested_child,
                                                          childinstance=child_instance,
                                                          ))

        '''
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
                
        '''

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
            new_subscription = ComponentSubscription(component_instance=component_instance,
                                                     attr=attr_name)

            self.__dict__['_subscriptions'].append(new_subscription)

            self.add_binding(new_subscription)

    def add_pending_subscription(self, target_id, attr_name):
        if target_id not in self.__class__._pending_subscriptions:
            self.__class__._pending_subscriptions[target_id] = []

        self.__class__._pending_subscriptions[target_id].append((self, attr_name))

    def remove_subscription(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]

    def react(self, names:list[str]):

        if isinstance(names, str):
            raise Exception("Please pass only a list of strings to react().")

        print(f"In react({names}) of {self}")

        bindings_to_update = []
        subscriptions_to_update = []

        dependencies = set(names).intersection(set(self._deps.keys()))
        
        for name in dependencies:
            
            for binding in self._deps[name]:
                if binding not in bindings_to_update:
                    bindings_to_update.append(binding)

        for name in dependencies:
            for sub in self.__dict__['_subscriptions']:
                subscribing_component_instance, sub_attr_name = sub #deconstruct the ComponentSubscription
                if name == sub_attr_name:
                    subscriptions_to_update.append(sub)
                
        print("bindings_to_update: ", bindings_to_update)
        print("__fields__: ", self.__fields__)
        #print("all _deps: ", self._deps)
        
        for binding in bindings_to_update:
            if hasattr(binding, 'update'): # or perhaps we could also use isinstance(binding, NodeBinding)
                binding.update()
            elif isinstance(binding, ComponentSubscription):
                sub = binding
                self_component_id = self.__element__.getAttribute("id")
                sub.component_instance.react([f"#{self_component_id}.{sub.attr}"])

ALLOWED_BUILTINS['BaseComponent'] = BaseComponent
