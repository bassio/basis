from string import Formatter
from dataclasses import dataclass
import inspect

from basis.shared.bindings import *
from basis.server.components.element import Element, ElementString, html_to_element_tree
from basis.components.component import safe_eval, safe_format, extract_dependencies, ALLOWED_BUILTINS


class ServerComponent(object):
    _registry = {}
    tag:str

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        if hasattr(cls, 'template'):
            templatestr = cls.template.__doc__
        elif cls.__doc__:
            templatestr = cls.__doc__
        else:
            return
        
        setattr(cls, "__templatestr__", templatestr)

        setattr(cls, "__blueprint__", html_to_element_tree(templatestr))
        
        if hasattr(cls, 'tag') \
        and  "-" in cls.tag:
            tag = cls.tag
        else:
            tag = cls.__name__ # ? .lower()

        ServerComponent._registry[tag] = cls

    def __init__(self):
        super().__init__()
        self.__init_bindings__()
        self.__init_fields__()


    def __init_bindings__(self):

        nodes = []
                
        bindings = []
        fields = []


        element_tree_root = self.__template__
        top_elem = element_tree_root['component']

        for d in top_elem.descendants:
            nodes.append(d)

        bindings.append(SelfBinding(component_instance=self, node=top_elem))

        for i, node in enumerate(nodes):
            if isinstance(node, Element): #confirm it is an ELEMENT not a TEXT node
                element = node
                if '-' in node.tag:
                    tag = str.lower(element.tag)
                    childcomponent_py = ServerComponent._registry[tag] # = element
                    bindings.append(ChildBinding(component_instance=self, node=element, childclass=childcomponent_py))

                element_attrs = [a for a in element.attrs]
                event_attrs = [a for a in element_attrs if a.startswith("on")]
                other_attrs = [a for a in element_attrs if not a.startswith("on")]
                
                for event_attr in event_attrs:
                    event_attr_value = node.attrs[event_attr]
                    if event_attr_value.startswith("{") and event_attr_value.endswith("}"):
                        event_attr_value = event_attr_value.strip("{}")
                        bindings.append(EventBinding(component_instance=self, node=element, event=event_attr, target_fn=event_attr_value))
                        fields.append(event_attr_value)

                if 'bind' in other_attrs:
                    bind_attr_value = element.attrs['bind']
                    from string import Formatter
                    fieldnames = [fname for _, fname, _, _ in Formatter().parse(bind_attr_value) if fname is not None]
                    if len(fieldnames) == 1:
                        field = fieldnames[0]
                        bindings.append(ModelBinding(component_instance=self, node=element, field=field))
                        fields.append(field)

                if 'for' in other_attrs:
                    for_attr_value = element.attrs['for']
                    from string import Formatter
                    has_expr = any(fname is not None for _, fname, _, _ in Formatter().parse(for_attr_value))
                    
                    if has_expr:
                        fieldnames = extract_dependencies(for_attr_value, ALLOWED_BUILTINS)
                        bindings.append(LoopBinding(component_instance=self, node=element, content=for_attr_value, fields=fieldnames))
                        fields += fieldnames

                for other_attr in other_attrs:
                    other_attr_value = element.attrs[other_attr]
                    from string import Formatter
                    has_expr = any(fname is not None for _, fname, _, _ in Formatter().parse(other_attr_value))
                    
                    if has_expr:
                        fieldnames = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
                        bindings.append(AttributeBinding(component_instance=self, node=element, attr=other_attr, content=other_attr_value, fields=fieldnames))
                        fields += fieldnames

            elif isinstance(node, ElementString):

                #skip "textnodes" inside <style> elements
                if (node.parent) \
                and str.lower(node.parent.tag) == 'style':
                    continue

                text = node
                text_content = str(text) #!js text.textContent
                from string import Formatter
                has_expr = any(fname is not None for _, fname, _, _ in Formatter().parse(text_content))
                                
                if has_expr:
                    fieldnames = extract_dependencies(text_content, ALLOWED_BUILTINS)
                    bindings.append(TextBinding(component_instance=self, node=node, content=text_content, fields=fieldnames))
                    fields += fieldnames
                
        #print(f"Bindings of {self.__class__.__name__}", bindings, fields)
        self.__dict__['__bindings__'] = bindings
        self.__dict__['__fields__'] = fields

    def __init_fields__(self):
        cls = self.__class__
        
        fields_on_class = [attr for attr in self.__fields__ \
                                if not attr in self.__dict__ and \
                                attr in cls.__dict__ \
                                and not inspect.isfunction(getattr(cls, attr))]
        
        for field in fields_on_class:
            print(f"setting attr from class on the instance: {field}")
            self.__dict__[field] = cls.__dict__[field]

        if len(fields_on_class) > 0:
            print(f"Reacting from __init_fields__ of {cls}. Fields on class: {fields_on_class}")
            self.react(fields_on_class)

    @classmethod
    def mount(cls, container, replace=False, **attributes):
        new_instance = cls()
        
        # set attributes from kwargs
        if len(attributes):
            for k, v in attributes.items():
                setattr(new_instance, k, v)

        #If you need a reference to the individual nodes after they have been appended to the live DOM, you must get a copy or reference to them before you call appendChild() on the main parent.
        
        new_template = new_instance.__template__

        self_element = new_instance.__template__['component'] # js: new_template.firstElementChild

        if replace:
            container.replace_with(self_element) #js: container.replaceWith(new_template)
        else:
            container.children.append(self_element) #js: container.appendChild(new_template)
            
        event_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, EventBinding)]

        for binding in event_bindings:
            self_event_method = getattr(new_instance, binding.target_fn)
            #js: binding.node.removeAttribute(binding.event)
            #js: setattr(binding.element, binding.event, ffi.create_proxy(self_event_method))
            setattr(binding.element, binding.event, self_event_method)

        child_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, ChildBinding)]

        for binding in child_bindings: #custom elements
            #obtain attributes set on the <custom-element> tag from the JS component side (after mounting parent of course!)
            #updated_child_node_attrs = {c.name: c.value for c in binding.node.attributes}
            updated_child_node_attrs = {k: v for k, v in binding.node.attrs.items()}
            custom_child = binding.childclass.mount(binding.node, replace=True, **updated_child_node_attrs)
        
        for nested_child in cls.get_nested_children():
            nested_child.mount(self_element, replace=False) #appendChild

        #print(f"finished mounting {cls}")

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
                                and issubclass(v, ServerComponent)
                                ]
            
            sorted_members = []

            for sc_name, sc in cls.__dict__.items():
                if (sc_name, sc) in subclass_members:
                    sorted_members.append(sc)

            return sorted_members
                   
        else:
            return []
        
    def __getattribute__(self, name):
        return super().__getattribute__(name)

    def __setattr__(self, name, value):
        try:
            old_value = self.__dict__[name]
        except KeyError: #setting a new attribute
            old_value = None

        super().__setattr__(name, value)

        #check for change
        if value != old_value:
            if name in self.__fields__:
                print(f"__setattr__ called for {name}, old value {old_value}, new value {value}")

                print("reacting")
                self.react([name])


    def react(self, names):
        
        text_bindings = [tb for tb in self.__bindings__ if isinstance(tb, TextBinding)]
        attr_bindings = [ab for ab in self.__bindings__ if isinstance(ab, AttributeBinding)]
        model_bindings = [mb for mb in self.__bindings__ if isinstance(mb, ModelBinding)]

        for name in names:
            for mb in model_bindings:
                if mb.field == name:
                    val = safe_eval(name, self.__dict__, ALLOWED_BUILTINS)
                    input_type = mb.node.attrs.get('type', 'text')
                    if input_type == 'checkbox':
                        if val:
                            mb.node.attrs['checked'] = 'checked'
                        elif 'checked' in mb.node.attrs:
                            del mb.node.attrs['checked']
                    else:
                        mb.node.attrs['value'] = str(val) if val is not None else ""

            for tb in text_bindings:
                if name in tb.fields:
                    tb.node.value = safe_format(tb.content, self.__dict__, ALLOWED_BUILTINS)

            for ab in attr_bindings:
                if name in ab.fields:
                    final_val = safe_format(ab.content, self.__dict__, ALLOWED_BUILTINS)
                    ab.node.attrs[ab.attr] = final_val
    

    @classmethod
    def clone_blueprint(cls):
        return cls.__blueprint__

    @property
    def __template__(self):
        if hasattr(self, "_template"):
            return self._template
        else:
            cloned = self.__class__.clone_blueprint()
            self.__dict__['_template'] = cloned
            return cloned

