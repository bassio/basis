import inspect
from pathlib import Path
from basis.shared.bindings import SelfBinding, SlotBinding, Refrain
from basis.shared.store import Store

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
    
    def _get_nodes(self, element=None):
        return NotImplementedError
    
    def __init_selfbinding__(self):
        raise NotImplementedError()
    
    @classmethod
    def initialize(cls, container, **kwargs):
        new_instance = cls()

        if len(kwargs):
            new_instance.__dict__.update(**kwargs)
        
        new_instance.__init_bindings__()

        new_instance.fill_slots_aware(container)

        new_instance.__init_fields__()

        with new_instance.refrain() as refrained:
            for k, v in kwargs.items():
                setattr(refrained, k, v)

        return new_instance
    
    def bind_nodes(self, nodes):
        for node in nodes:
            self._bind_node(node)

    def __init_bindings__(self):
        nodes = self._get_nodes()

        self.bind_nodes(nodes)
        
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
        
        fields_on_class = [attr for attr in self.__fields__ \
                                if (not attr in self.__dict__) and \
                                (attr in cls.__dict__) \
                                and (not inspect.isfunction(getattr(cls, attr)))]
        
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
                            #print(f"{component_name} found in _pending_subscriptions")
                            self.__class__._pending_subscriptions[component_name].append((self, attr_name))
                        else:
                            #print(f"{component_name} NOT FOUND in _pending_subscriptions")
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

    def react(self, names):
        pass
    
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
