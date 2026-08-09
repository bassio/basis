import inspect
from pathlib import Path
import weakref

from basis.shared.bindings import BindingBlueprint, Binding, SelfBinding, TextBinding, \
    AttributeBinding, SelfAttributeBinding, TextContentAttributeBinding, ModelBinding, EventBinding, IfBinding, \
    ChildBinding, LoopBinding, SlotBinding, ComponentSubscription, \
    FormModelBinding, desugar_expression, safe_eval, safe_format, safe_format_with_stores, \
    ALLOWED_BUILTINS, Refrain, \
    _process_self_attr_bindings
from basis.shared.bindings import extract_dependencies
from basis.shared.store import Store
from basis.shared.dag import DependencyGraph, StateNode, ComputedNode, EffectNode, computed
from basis.shared.context import ContextVarProxyDict


def include_store(name: str, url: str = None, target: str = None):

    """
    Decorator to include a reactive store in a Page or Component.
    """
    def decorator(cls):
        if not hasattr(cls, '__basis_stores__'):
            cls.__basis_stores__ = []
        if not any(s['name'] == name for s in cls.__basis_stores__):
            cls.__basis_stores__.append({
                'name': name,
                'url': url,
                'target': target
            })
        return cls
    return decorator


def include_model(model: type, name: str, one: bool = False, target: str = "items", **kwargs):
    """
    Decorator to include a model-backed store in a Page or Component.
    """
    def decorator(cls):
        if not hasattr(cls, '__basis_models__'):
            cls.__basis_models__ = []
        if not any(s['name'] == name for s in cls.__basis_models__):
            cls.__basis_models__.append({
                'model': model,
                'name': name,
                'one': one,
                'target': target,
                'kwargs': kwargs
            })
        return cls
    return decorator


class BaseComponent(object):

    _registry = {}
    _instance_registry = ContextVarProxyDict("component_instance_registry")
    _live_instances = weakref.WeakSet()
    _pending_subscriptions = ContextVarProxyDict("component_pending_subscriptions")

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
        templatestr = ""
        if hasattr(cls, 'template'):
            val = getattr(cls, 'template')
            if isinstance(val, str):
                templatestr = val
            elif isinstance(inspect.getattr_static(cls, 'template', None), classmethod):
                if val.__doc__ is not None and val.__doc__.strip():
                    templatestr = val.__doc__
                else:
                    templatestr = val()
            elif inspect.isfunction(val):
                if val.__doc__ is not None:
                    templatestr = val.__doc__
        
        if not templatestr:
            if cls.__doc__:
                templatestr = cls.__doc__
            elif (html_file:=cls.__file__().with_suffix(".html").with_stem(cls.__file__().parent.name)).exists():
                with open(html_file, "r") as htm:
                    templatestr = htm.read()
            else:
                templatestr = ""
        
        return templatestr
    
    @classmethod
    def _get_style_string(cls):
        style_content = ""
        if hasattr(cls, 'style'):
            val = getattr(cls, 'style')
            if isinstance(val, str):
                style_content = val
            elif isinstance(inspect.getattr_static(cls, 'style', None), classmethod):
                if val.__doc__ is not None and val.__doc__.strip():
                    style_content = val.__doc__
                else:
                    style_content = val()
            elif inspect.isfunction(val):
                if val.__doc__ is not None:
                    style_content = val.__doc__
        
        # Check if the style needs to be scoped
        is_scoped = False
        try:
            desc = inspect.getattr_static(cls, 'style', None)
            if getattr(desc, '__scoped__', False):
                is_scoped = True
        except AttributeError:
            pass
            
        if not is_scoped:
            try:
                val = getattr(cls, 'style', None)
                if val is not None:
                    if inspect.ismethod(val):
                        val = val.__func__
                    if getattr(val, '__scoped__', False):
                        is_scoped = True
            except AttributeError:
                pass

        if is_scoped and style_content:
            tag = getattr(cls, '__tag__', cls.__name__)
            style_content = f"@scope ({tag}) {{\n{style_content}\n}}"
        
        return style_content


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
        if cls.__name__.endswith("Subclass"):
            return

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
        self.__dict__['_dag'] = DependencyGraph()
        self.__dict__['_dag_nodes'] = self._dag.nodes
        self.__class__._live_instances.add(self)
        
    def __init_selfbinding__(self):
        #template is ServerFragment on server and DocumentFragment on client
        template = self.__template__
        self_element = template.firstElementChild
        self.add_binding(SelfBinding(component_instance=self, node=self_element))
        setattr(self_element, '__basis_instance__', self)
        self.__dict__['_element'] = self_element
        
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

        for k, v in kwargs.items():
            new_instance.__dict__[k] = v

        new_instance.__init_selfbinding__()

        #new_instance.__init_self_attr_bindings__(**kwargs)
        
        new_instance.__init_slot_bindings__()

        new_instance.fill_slots(container)

        new_instance.__init_bindings__()

        new_instance.__init_fields__()

        #with new_instance.refrain() as refrained:
        #    for k, v in kwargs.items():
        #        setattr(refrained, k, v)

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
            self.add_binding(SelfBinding(component_instance=self, node=node))
        self.__dict__['_element'] = node

    def add_binding(self, binding):

        self.__dict__['__bindings__'].append(binding)
        if isinstance(binding, SelfBinding):
            self.__dict__['_element'] = binding.node

        if hasattr(binding, 'fields'):
            # Existing flat dependency tracking (keeping for compatibility for now, but will eventually remove)
            for field in binding.fields:
                if field not in self._deps:
                    self._deps[field] = []
                    if field not in self.__fields__:
                        self.__fields__.append(field)
                if binding not in self._deps[field]:
                    self._deps[field].append(binding)
            
            # DAG integration: Register as an EffectNode
            if hasattr(binding, 'update'):
                # Generate a unique name for the effect node
                effect_name = f"effect_{id(binding)}"
                self._dag.add_effect(effect_name, binding.update, binding.fields)

    def remove_binding(self, binding):
        try:
            self.__dict__['__bindings__'].remove(binding)
        except ValueError:
            pass
        if hasattr(binding, 'update'):
            effect_name = f"effect_{id(binding)}"
            self._dag.remove_effect(effect_name)
        if hasattr(binding, 'fields'):
            for field in binding.fields:
                if field in self._deps and binding in self._deps[field]:
                    self._deps[field].remove(binding)
    

    @classmethod
    def _get_nodes(cls, element, skip_loop_descendants=False):
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

                if ast_trees_dict:

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

        if hasattr(node, 'getAttributeNames'): # ELEMENT node
            element = node

            tag_name = element.tagName.lower()
            #if tag_name in ['style', 'script'] and not element.hasAttribute('text-content'):
            #    return []

            element_attrs = list(element.getAttributeNames())
            event_attrs = [a for a in element_attrs if a.startswith("on")]
            other_attrs = [a for a in element_attrs if not a.startswith("on")]

            special_attrs = ["if", "for", "in", "key", "bind", "text-content"]
            non_standard_attrs = [a for a in other_attrs if a in special_attrs]
            standard_attrs = [a for a in other_attrs if a not in non_standard_attrs]

            is_loop_template = 'for' in non_standard_attrs and 'in' in non_standard_attrs

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
            if is_loop_template:
                inlist_attr_value = element.getAttribute('in').strip("{}")
                for_attr_value = element.getAttribute('for')
                fieldnames, trees_dict = extract_dependencies(element.getAttribute('in'), ALLOWED_BUILTINS)
                
                binding_class = LoopBinding
                
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
                    tag_name = str.lower(element.tagName)
                    if tag_name == 'form':
                        blueprints.append(BindingBlueprint(
                            binding_class=FormModelBinding,
                            node_index=node_index,
                            kwargs={
                                'target_expression': fieldnames[0],
                                'validate_on': element.getAttribute('validate-on') or 'input'
                            },
                            ast_trees=trees_dict
                        ))
                    else:
                        field = fieldnames[0]
                        blueprints.append(BindingBlueprint(
                            binding_class=ModelBinding,
                            node_index=node_index,
                            kwargs={'field': field},
                            ast_trees=trees_dict
                        ))
                        # Also need the event binding for the input
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

            # Process text-content binding
            if 'text-content' in non_standard_attrs and not is_loop_template:
                text_content_attr_value = element.getAttribute('text-content')
                fieldnames, trees_dict = extract_dependencies(text_content_attr_value, ALLOWED_BUILTINS)
                if trees_dict:
                    blueprints.append(BindingBlueprint(
                        binding_class=TextContentAttributeBinding,
                        node_index=node_index,
                        kwargs={'attr': 'text-content', 'content': text_content_attr_value, 'fields': fieldnames},
                        ast_trees=trees_dict
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

                        # Guard: standalone/valueless attrs
                        # are returned as None by getAttribute. They have no reactive content.
                        if attr_value is None:
                            continue

                        fieldnames, trees_dict = extract_dependencies(attr_value, ALLOWED_BUILTINS)
                        
                        if trees_dict:
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
            if parent and hasattr(parent, 'tagName'):
                if parent.tagName.lower() == 'style':
                    return []
                elif parent.tagName.lower() == 'script' and parent.getAttribute('type') != "application/json":
                    return []
                
            text_content = node.textContent
            fieldnames, trees_dict = extract_dependencies(text_content, ALLOWED_BUILTINS)

            if trees_dict:
                blueprints.append(BindingBlueprint(
                    binding_class=TextBinding,
                    node_index=node_index,
                    kwargs={'content': text_content, 'fields': fieldnames},
                    ast_trees=trees_dict
                ))

        return blueprints

    def __init_bindings__(self):
        # print(f"__init_bindings__ of {self.__class__}")
        
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

        #print(f"Bindings of {self.__class__}:", self.__bindings__)
        
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
        
        # print(f"__init_fields__ : {cls} fields: ", self.__fields__)

        fields_on_class = [attr for attr in self.__fields__ \
                                if (attr not in self.__dict__) and \
                                (attr in cls.__dict__) \
                                and (not inspect.isfunction(getattr(cls, attr)))]
        
        # print(f"fields_on_class of {cls} : ", fields_on_class)

        # Collect dependencies from computed properties
        for name, member in inspect.getmembers(cls):
            member_func = getattr(member, 'fget', member)
            if hasattr(member_func, '_is_computed'):
                deps = getattr(member_func, '_dependencies', [])
                for d in deps:
                    if d not in self.__fields__:
                        self.__fields__.append(d)

        with self.refrain() as refrained:

            for field in fields_on_class:
                # print(f"setting attr from class {self.__class__.__name__} on the instance: {field}, with value {cls.__dict__[field]}")
                setattr(refrained, field, cls.__dict__[field])

            for field in self.__fields__:
                if field.startswith("$"):
                    
                    if "." in field:
                        store_name, attr_name = field.strip("$").split(".")
                    else:
                        store_name = field.strip("$")
                        attr_name = ""

                    if store_name in Store._registry:
                        store_instance = Store._registry[store_name]
                        setattr(refrained, field, store_instance)
                        store_instance.add_subscription(self, attr_name)
                    else:
                        # Register pending subscription
                        if store_name not in Store._pending_subscriptions:
                            Store._pending_subscriptions[store_name] = []
                        
                        Store._pending_subscriptions[store_name].append((self, attr_name))
                    
                    # Register in DAG (even if pending)
                    self._dag.get_or_create_state(field)
                
                elif field.startswith("#"):
                    if "." in field:
                        component_name, attr_name = field.strip("#").split(".")

                        if component_name in self.__class__._instance_registry:
                            component_instance = self.__class__._instance_registry[component_name]

                            setattr(refrained, field, component_instance)
                            
                            component_instance.add_subscription(self, attr_name)
                            # Register in DAG
                            self._dag.get_or_create_state(field)

                        else:
                            
                            new_subscription = ComponentSubscription(component_instance=self,
                                                                     attr=attr_name)

                            if component_name not in self.__class__._pending_subscriptions:
                                self.__class__._pending_subscriptions[component_name] = []
                            
                            self.__class__._pending_subscriptions[component_name].append(new_subscription)
                                
                            # Register in DAG (even if pending, we want the node)
                            self._dag.get_or_create_state(field)
                
                    else:
                        # no-op if only "#component_id" with no attribute specified
                        pass

                        
                else:
                    # Register standard fields as StateNodes in the DAG
                    self._dag.get_or_create_state(field)
                    refrained.force_react(field)

            # Register computed properties in the DAG
            for name, member in inspect.getmembers(self.__class__):
                # Check if it's a computed property (metadata is on fget if it's a property)
                member_func = getattr(member, 'fget', member)
                if hasattr(member_func, '_is_computed'):
                    # The 'computed' decorator stores dependencies in _dependencies
                    deps = getattr(member_func, '_dependencies', [])
                    # The original function is stored in _original_func
                    original_func = getattr(member_func, '_original_func', None)
                    if original_func:
                        node = self._dag.add_computed(name, original_func, self, deps)
                        # Force an initial calculation so we don't start with None
                        node.update()


    @property
    def __element__(self):
        if '_element' in self.__dict__:
            return self.__dict__['_element']
        for binding in self.__bindings__:
            if isinstance(binding, SelfBinding):
                self.__dict__['_element'] = binding.node
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

            if named_children_to_insert:
                slot_node.replaceWith(*named_children_to_insert)
            #else:
            #    # Fallback to slot's own child nodes
            #    slot_node.replaceWith(*slot_node.children)
            
        # Fill each <slot> in order
        for sb in default_slot_bindings:
            slot_node = sb.node

            default_children_to_insert = default_children
            
            if default_children_to_insert:
                slot_node.replaceWith(*default_children_to_insert)
            #else:
            #    # Fallback to slot's own child nodes
            #    slot_node.replaceWith(*slot_node.children)


    def __getattribute__(self, name):
        if name and len(name) > 1:
            first_char = name[0]
            if first_char == '$':
                try:
                    target = name[1:]
                    if "." in target:
                        store_name, attr_name = target.split(".", 1)
                        return getattr(self.__class__.S[store_name], attr_name, None)
                    else:
                        return self.__class__.S[target]
                except Exception:
                    pass
            elif first_char == '#':
                try:
                    target = name[1:]
                    if "." in target:
                        component_name, attr_name = target.split(".", 1)
                        return getattr(self.__class__._instance_registry[component_name], attr_name, None)
                    else:
                        return self.__class__._instance_registry[target]
                except Exception:
                    pass
        return super().__getattribute__(name)

    def __setattr__(self, name, value):

        # print(f"inside __setattr__ of {self} for the attr {name}")

        if name.startswith("$"):
            store_name, attr_name = name.strip("$").split(".")
            store_instance = self.__class__.S[store_name]
            
            try:
                old_value = store_instance.__dict__[attr_name]
            except KeyError:
                old_value = None
            
            # print(f"calling __setattr__ on {store_instance} called for {attr_name}, old value {old_value}, new value {value}")
            setattr(store_instance, attr_name, value)

        elif name.startswith("#"):
            component_name, attr_name = name.strip("#").split(".")
            component_instance = self.__class__.C[component_name]

            try:
                old_value = component_instance.__dict__[attr_name]
            except KeyError:
                old_value = None
            
            setattr(component_instance, attr_name, value)
            # print(f"calling __setattr__ on {component_instance} called for {attr_name}, old value {old_value}, new value {value}")
            #the component_instance should then react from its instance !

        else:
            if name not in self.__dict__:
                # Initial assignment of a new attribute -> always trigger DAG
                self.__dict__[name] = value
                self._dag.trigger(name)
            else:
                # Updating an existing attribute -> fast change detection
                old_value = self.__dict__[name]
                self.__dict__[name] = value
                
                if value is not old_value:
                    if isinstance(value, (list, dict, set, tuple)) \
                    or value != old_value:
                        self._dag.trigger(name)
    
    @classmethod
    def mount(cls, container, replace=False, **attributes):
        
        # print(f"mount: starting mounting {cls}, with attributes: {attributes}")

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

        for nested_child in cls.get_nested_children():
            child_instance = nested_child.mount(self_element, replace=False) #appendChild

            new_instance.add_binding(ChildBinding(component_instance=new_instance,
                                                          node=self_element,
                                                          childclass=nested_child,
                                                          childinstance=child_instance,
                                                          ))

        # print(f"mount: finished mounting {cls}")

        return new_instance


    @classmethod
    def mount_app(cls, container, replace=False):
        # 1. Collect all stores/models from all registered components
        mounted_stores = set()
        mounted_models = set()
        mounted_providers = []

        all_component_classes = [cls] + list(cls._registry.values())

        for comp_cls in all_component_classes:
            # Handle @include_store decorators
            if hasattr(comp_cls, '__basis_stores__'):
                try:
                    from basis.shared.store_provider import StoreProvider
                    for store_cfg in comp_cls.__basis_stores__:
                        name = store_cfg['name']
                        if name not in mounted_stores:
                            mounted_stores.add(name)
                            provider = StoreProvider.mount(container, 
                                              name=name, 
                                              url=store_cfg['url'],
                                              target=store_cfg.get('target'))
                            mounted_providers.append(provider)
                except ImportError:
                    pass
                    
            # Handle @include_model decorators
            if hasattr(comp_cls, '__basis_models__'):
                try:
                    from basis.shared.store_provider import ModelStoreProvider
                    for model_cfg in comp_cls.__basis_models__:
                        name = model_cfg['name']
                        if name not in mounted_models:
                            mounted_models.add(name)
                            provider = ModelStoreProvider.mount(container,
                                                   name=name,
                                                   model=model_cfg['model'],
                                                   one=model_cfg['one'],
                                                   target=model_cfg['target'],
                                                   **model_cfg['kwargs'])
                            mounted_providers.append(provider)
                except ImportError:
                    pass

        new_instance = cls.mount(container, replace)
        new_instance._mounted_providers = mounted_providers

        #client
        for c_tag, c in cls._registry.items():
            if hasattr(c, 'style'):
                style_content = c._get_style_string()
                
                if style_content:
                    style_elem = cls._create_element("style")
                    style_elem.setAttribute("data-component-class", c.__name__)
                    style_elem.textContent = style_content
                    container.prepend(style_elem)

        return new_instance

    def hot_swap(self, new_cls):
        """Hot-swap this instance with a new class definition."""
        print(f"HMR: Hot-swapping instance {self} to {new_cls}")
        
        # 1. Capture current state (standard fields)
        state = {}
        for field in self.__fields__:
            if not field.startswith(("$", "#")):
                try:
                    state[field] = getattr(self, field)
                except AttributeError:
                    pass

        # 2. Update class reference
        self.__class__ = new_cls
        
        # 3. Clean up old bindings and DAG
        for b in list(self.__bindings__):
            self.remove_binding(b)
        
        self.__dict__['__bindings__'] = []
        self.__dict__['_deps'] = {}
        self.__dict__['_dag'] = DependencyGraph()
        self.__dict__['_dag_nodes'] = self._dag.nodes
        
        # 4. Clear cached template/nodes to force reload from new class blueprint
        if '_template' in self.__dict__:
            del self.__dict__['_template']
        if '_nodes' in self.__dict__:
            del self.__dict__['_nodes']

        # 5. Handle DOM replacement
        old_element = self.__element__
        if old_element:
            # Create new template content from the new class
            new_fragment = self.__template__
            # Note: self.__template__ is a DocumentFragment/ServerFragment
            
            # Replace old root element with new one
            # We assume the first child of the fragment is the component root
            old_element.replaceWith(new_fragment)
            
            # Re-initialize everything
            self.__init_selfbinding__()
            self.__init_slot_bindings__()
            self.__init_bindings__()
            self.__init_fields__()
            
            # 6. Restore state and trigger updates
            with self.refrain() as refrained:
                for k, v in state.items():
                    setattr(refrained, k, v)
            
            # Trigger all bindings to reflect the restored state in the new DOM
            self._dag.trigger_batch(list(state.keys()))
            
        print(f"HMR: Hot-swap complete for {self}")
    
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
                                                     attr=attr_name,
                                                     target_instance=self)

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

        # print(f"In react({names}) of {self}")

        # Integration with DAG: trigger the graph
        self._dag.trigger_batch(names)
        
ALLOWED_BUILTINS['BaseComponent'] = BaseComponent
