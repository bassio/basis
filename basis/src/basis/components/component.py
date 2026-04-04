from string import Formatter
from dataclasses import dataclass
from functools import wraps, partial
import inspect
import json
from pathlib import Path
import ast
import operator

try:
    from pyscript import window, document, ffi, fetch

    PYSCRIPT = True
    
except ImportError:

    PYSCRIPT = False


from basis.shared.store import Store


ALLOWED_BUILTINS = {'False': False,
                    'True': True,
                    'None': None,
                    'divmod': divmod,
                    'enumerate': enumerate,
                    'filter': filter,
                    'float': float,
                    'format': format,
                    'hex': hex,
                    'int': int,
                    'iter': iter,
                    'len': len,
                    'list': list,
                    'map': map,
                    'max': max,
                    'min': min,
                    'oct': oct,
                    'ord': ord,
                    'pow': pow,
                    'range': range,
                    'repr': repr,
                    'reversed': reversed,
                    'round': round,
                    'set': set,
                    'slice': slice,
                    'sorted': sorted,
                    'str': str,
                    'sum': sum,
                    'tuple': tuple,
                    'zip': zip}


def safe_eval(expr_str, context, allowed_builtins):
    try:
        tree = ast.parse(expr_str, mode='eval')
    except Exception as e:
        print(f"Failed to parse {expr_str}: {e}")
        return f"{{Error: {expr_str}}}"
    
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)

        elif isinstance(node, ast.Name):
            if node.id in context:
                return context[node.id]
            elif node.id in allowed_builtins:
                return allowed_builtins[node.id]
            raise NameError(f"Name {node.id} is not defined")

        elif isinstance(node, ast.Attribute):
            val = _eval(node.value)
            return getattr(val, node.attr)

        elif isinstance(node, ast.Subscript):
            val = _eval(node.value)
            if hasattr(ast, 'Index') and isinstance(node.slice, ast.Index):
                key = _eval(node.slice.value)
            else:
                key = _eval(node.slice)
            return val[key]

        elif isinstance(node, ast.Call):
            func = _eval(node.func)
            args = [_eval(arg) for arg in node.args]
            kwargs = {kw.arg: _eval(kw.value) for kw in node.keywords}
            return func(*args, **kwargs)

        elif isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.Str):
            return node.s

        elif isinstance(node, ast.Num):
            return node.n

        elif isinstance(node, ast.NameConstant):
            return node.value

        elif isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op_type = type(node.op)
            ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
                ast.Mod: operator.mod,
                ast.Pow: operator.pow,
                ast.FloorDiv: operator.floordiv,
            }
            if op_type in ops:
                return ops[op_type](left, right)
            raise ValueError(f"Unsupported binop {op_type}")

        elif isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                op_type = type(op)
                ops = {
                    ast.Eq: operator.eq,
                    ast.NotEq: operator.ne,
                    ast.Lt: operator.lt,
                    ast.LtE: operator.le,
                    ast.Gt: operator.gt,
                    ast.GtE: operator.ge,
                    ast.Is: operator.is_,
                    ast.IsNot: operator.is_not,
                    ast.In: operator.contains,
                }
                if op_type == ast.NotIn:
                    res = not operator.contains(right, left)
                elif op_type in ops:
                    if op_type == ast.In:
                        res = ops[op_type](right, left)
                    else:
                        res = ops[op_type](left, right)
                else:
                    raise ValueError(f"Unsupported cmp {op_type}")
                if not res: return False
                left = right
            return True

        elif isinstance(node, ast.UnaryOp):
            operand = _eval(node.operand)
            if isinstance(node.op, ast.Not): return not operand
            elif isinstance(node.op, ast.USub): return -operand
            elif isinstance(node.op, ast.UAdd): return +operand
            raise ValueError(f"Unsupported unary {type(node.op)}")

        elif isinstance(node, ast.BoolOp):
            if isinstance(node.op, ast.And):
                for val in node.values:
                    if not _eval(val): return False
                return True
            elif isinstance(node.op, ast.Or):
                for val in node.values:
                    if _eval(val): return True
                return False

        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")
            
    try:
        return _eval(tree.body)
    except Exception as e:
        print(f"Error evaluating '{expr_str}': {e}")
        return f"{{Error: {expr_str}}}"

def safe_format(template_str, context, allowed_builtins):
    
    result = ""
    formatter = Formatter()
    for literal_text, fname, format_spec, conversion in formatter.parse(template_str):
        result += literal_text
        if fname is not None:
            val = safe_eval(fname, context, allowed_builtins)
            if format_spec:
                result += format(val, format_spec)
            else:
                result += str(val)
    return result

def safe_format_with_stores(template_str, context, allowed_builtins, store_registry, component_instance_registry):
    
    result = ""
    formatter = Formatter()
    for literal_text, fname, format_spec, conversion in formatter.parse(template_str):
        result += literal_text
        if fname is not None:
            if fname.startswith("$"):
                store_name, attr_name = fname.strip("$").split(".")
                val = getattr(store_registry[store_name], attr_name)
            elif fname.startswith("#"):
                component_name, attr_name = fname.strip("#").split(".")
                if component_name in component_instance_registry:
                    print("FOUND COMPONENT INSTANCE IN REGISTRY: ")
                    val = getattr(component_instance_registry[component_name], attr_name)
                else:
                    print("COULD NOT FIND COMPONENT INSTANCE IN THE REGISTRY: ", component_name)
                    val = ""
            else:
                val = safe_eval(fname, context, allowed_builtins)
            
            if format_spec:
                result += format(val, format_spec)
            else:
                result += str(val)
    
    return result

def extract_dependencies(template_str, allowed_builtins):
    
    formatter = Formatter()
    deps = set()
    for _, fname, _, _ in formatter.parse(template_str):
        if fname is not None:
            if (dollar_or_hash_sign:=fname[0]) in ['$', '#']:
                fname_no_sign = fname.strip("$#")
                try:
                    tree = ast.parse(fname_no_sign, mode='eval')

                    store_name = None
                    attr_name = None

                    for node in ast.walk(tree):
                        if isinstance(node, ast.Name): # extract store_name
                            if node.id not in allowed_builtins and isinstance(getattr(node, 'ctx', None), ast.Load):
                                store_name = node.id
                        if isinstance(node, ast.Attribute): # extract the attr in the Store
                            attr_name = node.attr
                            
                    if store_name and attr_name:
                        deps.add(f"{dollar_or_hash_sign}{store_name}.{attr_name}")
                        
                except SyntaxError:
                    pass
            else:
                try:
                    tree = ast.parse(fname, mode='eval')
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Name):
                            if node.id not in allowed_builtins and isinstance(getattr(node, 'ctx', None), ast.Load):
                                deps.add(node.id)
                except SyntaxError:
                    pass
        
    return list(deps)

def client(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if PYSCRIPT:
            return func(*args, **kwargs)

    return wrapper

@dataclass
class Field(object):
    name:str

class StoreField(object):
    name:str
    store:str

@dataclass
class Binding(object):
    component_instance:"Component"
    node:object

    @property
    def component_class(self):
        return self.component_instance.__class__

@dataclass
class SelfBinding(Binding):
    ...

@dataclass
class TextBinding(Binding):
    content:str
    fields:list[str]


@dataclass
class AttributeBinding(Binding):
    attr:str
    content:str
    fields:list[str]
    is_boolean:bool = False
    
@dataclass
class ModelBinding(Binding):
    field: str

    @property
    def fields(self):
        return [self.field]

@dataclass
class EventBinding(Binding):
    event:str
    target_fn:str

    @property
    def element(self):
        return self.node

    @property
    def fields(self):
        return [self.target_fn]
    

@dataclass
class IfBinding(Binding):
    expr: str
    anchor: object
    is_visible: bool
    fields: list

@dataclass
class ChildBinding(Binding):
    childclass:str
    childinstance:object=None

@dataclass
class LoopBinding(Binding):
    item:str
    collection:str
    clone:object
    parent:object

@dataclass
class KeyedLoopBinding(Binding):
    item:str
    collection:str
    clone:object
    parent:object
    key:str

@dataclass
class SlotBinding(Binding):
    name: str | None = None
    is_default: bool = True
    
    @property
    def fields(self):
        return []

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


class Component(object):
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
        return Path(inspect.getfile(cls))
    
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)

        pth_cls = cls.__file__()
                
        if hasattr(cls, 'template'):
            if inspect.isfunction(cls.template):
                templatestr = cls.template.__doc__
            elif isinstance(cls.template, str):
                templatestr = cls.template
        elif cls.__doc__:
            templatestr = cls.__doc__
        elif (html_file:=pth_cls.with_suffix(".html").with_stem(pth_cls.parent.name)).exists():
            with open(html_file, "r") as htm:
                templatestr = htm.read()
            
            css_file = pth_cls.with_suffix(".css").with_stem(pth_cls.parent.name)

            if css_file.exists():
                with open(css_file, "r") as css:
                    setattr(cls, "style", css.read())

        else:
            return

        setattr(cls, "__templatestr__", templatestr)

        init_template = document.createElement('template')
        init_template.innerHTML = cls.__templatestr__

        setattr(cls, "__blueprint__", init_template)
        
        if hasattr(cls, '__tag__') \
        and  "-" in cls.__tag__:
            tag = cls.__tag__
        else:
            tag = cls.__name__ # ? .lower()

        if not tag in Component._registry.keys(): 
            Component._registry[tag] = cls

            if "-" in tag:
                if PYSCRIPT:
                    custom_element = window.CustomElementFactory(ffi.to_js({'__templatestr__': templatestr, 'pyClassName': cls.__name__, '__shadow__': getattr(cls, '__shadow__', False)}))
                    window.customElements.define(cls.__tag__, custom_element)
                    setattr(cls, 'custom_element', custom_element)        

    def __init__(self):
        super().__init__()
        self.__dict__['_subscriptions'] = []
        self.__init_bindings__()
        self.__init_fields__()

    @client
    def __init_bindings__(self):
        walker = document.createTreeWalker(self.__template__,
        window.NodeFilter.SHOW_ELEMENT | window.NodeFilter.SHOW_TEXT);

        nodes = []

        current_node = walker.nextNode()

        while current_node:
            # Do something with the node
            nodes.append(current_node)
            current_node = walker.nextNode()

        bindings: list[Binding] = []
        fields: list[str] = []
        first_level_custom_element_children = []
        formatter = Formatter()

        def get_ancestor_tags(el):
            ancestors = []
            element = el
            while (element):
                try:
                    element = element.parentNode
                    ancestors.append(element.tagName)
                except:
                    break

            return ancestors

        self_element = self.__template__.firstElementChild
        bindings.append(SelfBinding(component_instance=self, node=self_element))


        for i, node in enumerate(nodes):
            if hasattr(node, 'getAttributeNames'): #confirm it is an ELEMENT not a TEXT node
                element = node
                if '-' in element.tagName:

                    tag = str.lower(element.tagName)

                    #custom_element_ancestors = [a for a in get_ancestor_tags(element) if '-' in a]

                    childcomponent_py = Component._registry[tag]
                    dom_child_node_attrs = {c.name: c.value for c in node.attributes}

                    #child_instance = childcomponent_py()

                    child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)

                    print(f"Child ATTRS in __init_bindings__ of {self.__class__} from dom of child component {childcomponent_py}", dom_child_node_attrs)

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

                    other_attr_value = element.getAttribute(other_attr)

                    if other_attr.startswith("{") and other_attr.endswith("}"):
                        other_attr_no_braces = other_attr.strip("{}")

                        if other_attr_value == "": # i.e. empty value for example <input checked />
                            other_attr_value == other_attr #i.e. the name with the braces so that we could Formatter().parse it e.g. <input {checked} >
                        
                        other_attr_isboolean = True

                        element.removeAttribute(other_attr) #remove the e.g. {checked} attribute from the dom

                    else:
                        other_attr_no_braces = other_attr
                        other_attr_isboolean = False
                    
                    fnames = [fname for _, fname, _, _ in formatter.parse(other_attr_value) if fname is not None]
                    has_expr = any(fnames)

                    if has_expr:
                        fieldnames = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)

                        print("fieldnames", fieldnames)

                        bindings.append(AttributeBinding(component_instance=self, node=element, attr=other_attr_no_braces, content=other_attr_value, fields=fieldnames, is_boolean=other_attr_isboolean))
                        fields += fieldnames

                if 'if' in other_attrs:
                    if_expr = element.getAttribute('if')
                    if_expr_clean = if_expr.removeprefix("{").removesuffix("}")

                    # interestingly here the extract_dependencies requires the braces around the 
                    # expression because it depends on the Formatter().parse() functionality
                    # hence if_expr rather than if_expr_clean
                    fieldnames = extract_dependencies(if_expr, ALLOWED_BUILTINS) 

                    print("if dependencies:", fieldnames)
                    
                    anchor = document.createComment(f"if: {if_expr_clean}")
                    print(f"inserting {element.tagName} element prior to anchor")
                    element.parentNode.insertBefore(anchor, element)
                    
                    bindings.append(IfBinding(
                        component_instance=self,
                        node=element,
                        expr=if_expr_clean,
                        anchor=anchor,
                        is_visible=True,
                        fields=fieldnames
                    ))
                    fields += fieldnames

                if 'bind' in other_attrs:
                    bind_attr_value = element.getAttribute('bind')
                    fieldnames = [fname for _, fname, _, _ in formatter.parse(bind_attr_value) if fname is not None]
                    if len(fieldnames) == 1:
                        field = fieldnames[0]
                        bindings.append(ModelBinding(component_instance=self, node=element, field=field))
                        fields.append(field)
                        
                        tag_name = str.lower(element.tagName)
                        input_type = element.getAttribute('type') if element.hasAttribute('type') else 'text'
                        
                        def create_update_handler(f):
                            def update_state(event):
                                if input_type == 'checkbox':
                                    setattr(self, f, event.target.checked)
                                else:
                                    setattr(self, f, event.target.value)
                            return ffi.create_proxy(update_state)
                            
                        handler = create_update_handler(field)
                        if tag_name == 'input' and input_type in ['checkbox', 'radio']:
                            element.addEventListener('change', handler)
                        elif tag_name == 'select':
                            element.addEventListener('change', handler)
                        else:
                            element.addEventListener('input', handler)

                if 'for' in other_attrs:
                    inlist_attr_value = element.getAttribute('in').strip("{}")
                    for_attr_value = element.getAttribute('for')
                    element_clone = element.cloneNode(True)
                    if element.hasAttribute('key'):
                        bindings.append(KeyedLoopBinding(component_instance=self, node=element, clone=element_clone, parent=element.parentElement, collection=inlist_attr_value, item=for_attr_value, key=element.getAttribute('key')))
                    else:
                        bindings.append(LoopBinding(component_instance=self, node=element, clone=element_clone, parent=element.parentElement, collection=inlist_attr_value, item=for_attr_value))

            elif hasattr(node, 'wholeText'):

                #skip "textnodes" inside <style> elements
                if (node.parentElement) \
                and str.lower(node.parentElement.tagName) == 'style':
                    continue

                text_content = node.textContent
                
                fnames = [fname for _, fname, _, _ in formatter.parse(text_content) if fname is not None]
                has_expr = any(fnames)

                if has_expr:
                    fieldnames = extract_dependencies(text_content, ALLOWED_BUILTINS)
                    print("text field names", fieldnames)
                    bindings.append(TextBinding(component_instance=self, node=node, content=text_content, fields=fieldnames))
                    fields += fieldnames
        
        # add to component instance registry if it is has an id
        if component_id:=self_element.getAttribute('id'):
            Component._instance_registry[component_id] = self
            
            if component_id in Component._pending_subscriptions:
                
                for subscribing_component_instance, attr_name in Component._pending_subscriptions.pop(component_id):
                    self.subscribe(subscribing_component_instance, attr_name)
                    
                    subscribed_field = f"#{component_id}.{attr_name}"
                    with subscribing_component_instance.refrain() as refrained:
                        setattr(refrained, subscribed_field, self)

        self.__dict__['__bindings__'] = bindings
        self.__dict__['__fields__'] = list(set(fields))
    

    def __init_fields__(self):
        cls = self.__class__

        print(f"__init_fields__ : {cls} fields:, ", self.__fields__)
        
        fields_on_class = [attr for attr in self.__fields__ \
                                if (not attr in self.__dict__) and \
                                (attr in cls.__dict__) \
                                and (not inspect.isfunction(getattr(cls, attr)))]
        
        if fields_on_class:
            with self.refrain() as refrained:
                for field in fields_on_class:
                    #print(f"setting attr from class {self.__class__.__name__} on the instance: {field}, with value {cls.__dict__[field]}")
                    setattr(refrained, field, cls.__dict__[field])
        
        for field in self.__fields__:
            if field.startswith("$"):
                
                store_name, attr_name = field.strip("$").split(".")
                store_instance = Store._registry[store_name]
                
                with self.refrain() as refrained:
                    setattr(refrained, field, store_instance)
                
                store_instance.subscribe(self, attr_name)
            
            elif field.startswith("#"):
                component_name, attr_name = field.strip("#").split(".")
                
                if component_name in Component._instance_registry:
                    component_instance = Component._instance_registry[component_name]

                    with self.refrain() as refrained:
                        setattr(refrained, field, component_instance)
                    
                    component_instance.subscribe(self, attr_name)

                else:

                    if component_name in Component._pending_subscriptions:
                        #print(f"{component_name} found in _pending_subscriptions")
                        Component._pending_subscriptions[component_name].append((self, attr_name))
                    else:
                        #print(f"{component_name} NOT FOUND in _pending_subscriptions")
                        Component._pending_subscriptions[component_name] = [(self, attr_name)]
                        
    @classmethod
    def mount_app(cls, container, replace=False):
        
        new_instance = cls.mount(container, replace)

        #fix styles
        styles = set()

        style_elem = document.createElement("style")

        #print(Component._registry)

        for c in Component._registry.values():
            if hasattr(c, 'style'):
                if isinstance(c.style, str):
                    styles.add(c.style)
                elif inspect.isfunction(c.style):
                    if c.style.__doc__ is not None:
                        styles.add(c.style.__doc__)
                else:
                    raise

        style_elem.textContent = "\n".join(styles)
        container.prepend(style_elem)


        return new_instance
    
    @classmethod
    def mount(cls, container, replace=False, **attributes):

        print(f"mount: starting mounting {cls}")

        new_instance = cls() # this naturally calls __init_bindings__ and __init_fields__

        # set attributes from kwargs
        if len(attributes):
            with new_instance.refrain() as refrained:
                for k, v in attributes.items():
                    setattr(refrained, k, v)

        #If you need a reference to the individual nodes after they have been appended to the live DOM, you must get a copy or reference to them before you call appendChild() on the main parent.
        
        new_template = new_instance.__template__

        # the LIMITATION for this is that components have to have a single element at their root.
        self_element = new_template.firstElementChild
        

        #child_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, ChildBinding)]


        # PRE-SNAPSHOT: capture each child binding's authored light-DOM content and
        # attributes BEFORE the template enters the live DOM i.e. before connectedCallback().

        # SLOTS ....
        # Distribute slotted content into the child's rendered template
        new_instance.fill_slots(new_instance.__element__, container)

        if replace:
            container.replaceWith(new_template)
            for k, v in attributes.items():
                self_element.setAttribute(k, v)

        else:
            container.appendChild(new_template)
            for k, v in attributes.items():
                self_element.setAttribute(k, v)


        # connectedCallback fires here for every custom element now in the live DOM.
        # Any JS-injected template content lands in nodes whose authored children
        # we already moved to the fragments above - it is safely discarded by
        # Python's mount(replace=True) call below.

        event_bindings = [eb for eb in new_instance.__bindings__ if isinstance(eb, EventBinding)]

        for binding in event_bindings:
            self_event_method = getattr(new_instance, binding.target_fn)
            binding.node.removeAttribute(binding.event)
            setattr(binding.element, binding.event, ffi.create_proxy(self_event_method))

        # SLOTS ....
        # Distribute slotted content into the child's rendered template
        # new_instance.fill_slots(container)
        
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
    
    @staticmethod
    def fill_slots(template, light_dom_source):

        default_slot_elements = template.querySelectorAll("slot:not([name])")
        named_slot_elements = template.querySelectorAll("slot[name]")
        
        #print("LEN SLOT BINDINGS:" , len(default_slot_elements) + len(named_slot_elements))

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
        
        #print("default_children", default_children)
        #print("named_children", named_children)
        
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
                #print(child.textContent)
                parent.insertBefore(child, slot_node)

            # Remove the <slot> placeholder regardless of whether it was filled
            slot_node.remove()

        return template
    

    def has_slots(self):
        for binding in self.__bindings__:
            if isinstance(binding, SlotBinding):
                return True
        return False
    

    @classmethod
    def is_static(cls):
        return (len(cls.__bindings__) == 0)

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
                                and issubclass(v, Component)
                                ]
            
            sorted_members = []

            for sc_name, sc in cls.__dict__.items():
                if (sc_name, sc) in subclass_members:
                    sorted_members.append(sc)

            return sorted_members
                   
        else:
            return []
        

    def subscribe(self, component_instance, attr_name:str):
        if (component_instance, attr_name) not in self._subscriptions:
            self.__dict__['_subscriptions'].append((component_instance, attr_name))

        print(f"_subscriptions of {self.__class__}: ", self.__dict__['_subscriptions'])

    def unsubscribe(self, component_instance, attr_name:str):
        self.__dict__['_subscriptions'] = [
            sub for sub in self._subscriptions if sub != (component_instance, attr_name)
        ]

    def __getattribute__(self, name):
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
                print(f"__setattr__ called for {name}, old value {old_value}, new value {value}")

                def microtask_callback(test):
                    #window.console.log(f"This message runs as a microtask with label {test}.")
                    pass

                # Call the JavaScript queueMicrotask function from Python
                window.queueMicrotask(ffi.create_proxy(partial(microtask_callback, value)))

                #print("reacting")
                self.react([name])


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
                fragment = document.createDocumentFragment()
                
                # Pop parent components initial bindings on this loop placeholder
                for tb in text_bindings:
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
                            cloned_element = document.importNode(lb.node, True)
                            cloned_element.removeAttribute('for')
                            cloned_element.removeAttribute('in')
                            cloned_element.removeAttribute('key')
                        except:
                            cloned_element = document.importNode(lb.clone, True)
                            cloned_element.removeAttribute('for')
                            cloned_element.removeAttribute('in')
                            cloned_element.removeAttribute('key')
                            
                        updated_child_node_attrs = {lb.item: i}
                        rest_of_fields = [f for f in self.__fields__ if (f != lb.item) and (not inspect.isfunction(getattr(self, f)))]
                        for field in rest_of_fields:
                            updated_child_node_attrs[field] = getattr(self, field)
                        
                        if '-' in (tag:=str.lower(lb.clone.tagName)):
                            childcomponent_py = Component._registry[tag]
                            for c in cloned_element.attributes:
                                if c.name not in updated_child_node_attrs:
                                    
                                    has_expr = any(fname is not None for _, fname, _, _ in formatter.parse(c.value))
                                    if has_expr:
                                        val = safe_format(c.value, updated_child_node_attrs, ALLOWED_BUILTINS)
                                        updated_child_node_attrs[c.name] = val
                                    else:
                                        updated_child_node_attrs[c.name] = c.value
                        else:
                            quick_component = Component.from_template(cloned_element.outerHTML)
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

                lb.parent.replaceChildren(*fragment.children)
                lb.instances = new_instances


        ### end antigravity

        for lb in loop_bindings:

            if lb.collection in names:
                collection_value = self.__dict__[lb.collection]

                cloned_elements = []
                fragment = document.createDocumentFragment();

                for i in collection_value: #iterate through the collection
                    try:
                        cloned_element = document.importNode(lb.node, True)
                        cloned_element.removeAttribute('for')
                        cloned_element.removeAttribute('in')
                    except:
                        cloned_element = document.importNode(lb.clone, True)
                        cloned_element.removeAttribute('for')
                        cloned_element.removeAttribute('in')
                    
                    if '-' in (tag:=str.lower(lb.clone.tagName)):
                        childcomponent_py = Component._registry[tag]
                    else:
                        quick_component = Component.from_template(cloned_element.outerHTML)
                        childcomponent_py = quick_component

                    new_cb = ChildBinding(component_instance=self, node=cloned_element, childclass=childcomponent_py)
                    new_child_bindings.append(new_cb)
                    self.__bindings__.append(new_cb)
                    
                    new_cb = ChildBinding(component_instance=self, node=cloned_element, childclass=childcomponent_py)
                    new_child_bindings.append(new_cb)
                    self.__bindings__.append(new_cb)
                    

                    for tb in text_bindings:
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

                    #cloned_elements.append(cloned_element)
                    
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

                        #print('rest_of_fields', rest_of_fields)

                        custom_child_instance = new_cb.childclass.mount(fragment, replace=False, **updated_child_node_attrs)

                        new_cb.childinstance = custom_child_instance
            

            lb.parent.replaceChildren(*fragment.children)

            #delete old child bindings
            for cb in child_bindings:
                if cb.node == lb.node:
                    self.__bindings__.remove(cb)
                elif '-' in (tag:=str.lower(lb.clone.tagName)):
                    childcomponent_py = Component._registry[tag]
                    if cb.childclass == childcomponent_py:
                        self.__bindings__.remove(cb)
                
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
            print("text_bindings_to_update", text_bindings_to_update)
            tb.node.textContent = safe_format_with_stores(tb.content, tb.component_instance.__dict__, ALLOWED_BUILTINS, Store._registry, Component._instance_registry)

        for mb in model_bindings_to_update:
            if mb.node not in looped_nodes:
                val = getattr(self, mb.field)
                input_type = mb.node.getAttribute('type') if mb.node.hasAttribute('type') else 'text'
                if input_type == 'checkbox':
                    mb.node.checked = bool(val)
                else:
                    mb.node.value = str(val) if val is not None else ""

        for ab in attr_bindings_to_update:
            print("attr_bindings_to_update", attr_bindings_to_update)
            if ab.node not in looped_nodes:                    
                if ab.attr not in ["in"]:
                    final_val = safe_format_with_stores(ab.content, self.__dict__, ALLOWED_BUILTINS, Store._registry, Component._instance_registry)
                    print("final_val", final_val)
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
                ib.node.remove()
            else:
                #print("INSERTING node into DOM based on IfBinding")
                ib.anchor.after(ib.node)
            
            ib.is_visible = expr_eval

            
    def refrain(self):
        ref_context = Refrain(self)
        return ref_context

    @classmethod
    def clone_blueprint(cls):
        cloned = document.importNode(cls.__blueprint__, True)
        return cloned

    @property
    def __template__(self):
        if hasattr(self, "_template"):
            return self._template
        else:
            cloned = self.__class__.clone_blueprint().content
            self.__dict__['_template'] = cloned
            return cloned
    
    @property
    def __element__(self):
        for binding in self.__bindings__:
            match binding:
                case SelfBinding:
                    return binding.node
        return None



from collections import UserList, OrderedDict

class ReactiveDict(OrderedDict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def __setitem__(self, key, value):
        super().__setitem__(key, value)

    def __delitem__(self, key):
        super().__delitem__(key)

    def append(self, item, key=None):
        if not key:
            key = len(self)
        
        self[key] = item
