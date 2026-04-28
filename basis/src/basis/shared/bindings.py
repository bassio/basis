import ast
from dataclasses import dataclass, field
import inspect
import json
import operator
from string import Formatter
from typing import Any


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


@dataclass
class Binding(object):
    component_instance:"Component"

    @property
    def component_class(self):
        return self.component_instance.__class__

@dataclass
class ComponentSubscription(Binding):
    attr:str

    @property
    def subscribing_component(self):
        return self.component_instance

    def __eq__(self, value):
        if isinstance(value, ComponentSubscription):
            return (value.attr == self.attr) and (value.component_instance is self.component_instance) 
        elif isinstance(value, tuple) and len(value) == 2:
            return (value[1] == self.attr) and (value[0] is self.component_instance) 
        else:
            return super().__eq__(value)
    
    def __iter__(self):
        # Allows: x, y = obj destructuring
        return iter([self.component_instance, self.attr])

@dataclass
class NodeBinding(Binding):
    node:object

    def marked_for_hydration(self):
        return [self.node]

            
@dataclass
class SelfBinding(NodeBinding):
    ...

@dataclass
class TextBinding(NodeBinding):
    content:str
    fields:list[str]
    parent:object

    def update(self):

        context = self.component_instance.__dict__
        store_registry = self.component_instance.__class__.S

        self.node.textContent = safe_format_with_stores(
            self.content, 
            context, 
            ALLOWED_BUILTINS, 
            store_registry=store_registry, 
            component_instance_registry=self.component_instance.__class__._instance_registry
        )

    def marked_for_hydration(self):
        return [self.parent]
    
@dataclass
class AttributeBinding(NodeBinding):
    attr:str
    content:str
    fields:list[str]
    is_boolean:bool = False
    
    def update(self):
        context = self.component_instance.__dict__
        store_registry = self.component_instance.__class__.S
        if self.attr not in ["in"]:
            final_val = safe_format_with_stores(self.content, self.component_instance.__dict__, ALLOWED_BUILTINS, store_registry, self.component_instance.__class__._instance_registry)
            if self.is_boolean:
                bool_val = str(final_val).lower() == 'true'
                self.node.toggleAttribute(self.attr, bool_val)
            else:
                self.node.setAttribute(self.attr, final_val)
        else:
            formatter = Formatter()
            _, fname, _, _ = next(iter(formatter.parse(self.content)))
            evaluated_val = safe_eval(fname, self.component_instance.__dict__, ALLOWED_BUILTINS)
            final_val = json.dumps(evaluated_val)
            self.node.setAttribute(self.attr, final_val)
    
@dataclass
class SelfAttributeBinding(AttributeBinding):
    def update(self):
        context = self.component_instance.__dict__
        store_registry = self.component_instance.__class__.S

        if self.attr not in ["in"]:
            final_val = safe_format_with_stores(self.content, context, ALLOWED_BUILTINS, store_registry, self.component_instance.__class__._instance_registry)
            if self.is_boolean:
                bool_val = str(final_val).lower() == 'true'
                setattr(self.component_instance, self.attr, bool_val)
            else:
                setattr(self.component_instance, self.attr, final_val)
        else:
            formatter = Formatter()
            _, fname, _, _ = next(iter(formatter.parse(self.content)))
            evaluated_val = safe_eval(fname, context, ALLOWED_BUILTINS)
            final_val = json.dumps(evaluated_val)
            setattr(self.component_instance, self.attr, final_val)

@dataclass
class ModelBinding(NodeBinding):
    field: str

    @property
    def fields(self):
        return [self.field]

    def update(self):
        val = getattr(self.component_instance, self.field)
        input_type = self.node.getAttribute('type') if hasattr(self.node, 'hasAttribute') and self.node.hasAttribute('type') else 'text'
        if input_type == 'checkbox':
            self.node.checked = bool(val)
        else:
            self.node.value = str(val) if val is not None else ""

@dataclass
class EventBinding(NodeBinding):
    event:str
    target_fn:str

    @property
    def element(self):
        return self.node

    @property
    def fields(self):
        return [self.target_fn]
    

@dataclass
class IfBinding(NodeBinding):
    expr: str
    anchor: object
    is_visible: bool
    fields: list

    def update(self):
        expr_eval = bool(safe_eval(self.expr, self.component_instance.__dict__, ALLOWED_BUILTINS))
        if expr_eval == self.is_visible:
            return  # visibility unchanged — skip DOM mutation
        if expr_eval == False:
            self.node.remove()
        else:
            self.anchor.after(self.node)
        self.is_visible = expr_eval

    def marked_for_hydration(self):
        return [self.node, self.anchor]


@dataclass
class ChildBinding(NodeBinding):
    childclass:str
    childinstance:object=None
    attr_bindings:list[SelfAttributeBinding] = field(default_factory=list)
    loop_binding:"LoopBinding|KeyedLoopBinding|None"=None

@dataclass
class LoopBinding(NodeBinding):
    item:str
    collection:str
    clone:object
    parent:object

    @property
    def fields(self):
        return [self.collection]
    
    def _new_clone(self):
        # New creation
        cloned_element = self.clone.cloneNode(True)
        cloned_element.removeAttribute('for')
        cloned_element.removeAttribute('in')

        return cloned_element
    
    def _child_node_attrs_dict(self, item):
        
        item_attr_name = self.item # the "for={single_item}"
        
        updated_child_node_attrs = {item_attr_name: item}
                

        if '-' in (tag:=str.lower(self.clone.tagName)):
            updated_child_node_attrs = {c: self.clone.getAttribute(c) for c in self.clone.getAttributeNames()}

        else:
            rest_of_fields = [f for f in self.component_instance.__fields__ \
                              if (f != item_attr_name) \
                                and (not inspect.isfunction(getattr(self.component_instance, f))) \
                                and (not f in ["for", "in", "key"])]
            
            for field in rest_of_fields:
                updated_child_node_attrs[field] = getattr(self.component_instance, field)

        updated_child_node_attrs.pop('for', None)
        updated_child_node_attrs.pop('in', None)
        updated_child_node_attrs.pop('key', None)

        return updated_child_node_attrs

    def update(self):

        # keep a reference to child bindings for this loop binding
        bindings_to_delete = [cb for cb in self.component_instance.__bindings__ \
                              if isinstance(cb, ChildBinding) \
                                and cb.loop_binding == self]

        collection_value = getattr(self.component_instance, self.collection, [])
        fragment = self.component_instance._create_document_fragment()

        for i in collection_value:
            cloned_element = self._new_clone()
            
            updated_child_node_attrs = self._child_node_attrs_dict()
            
            if '-' in (tag:=str.lower(self.clone.tagName)):
                childcomponent_py = self.component_instance.__class__._registry[tag]
            else:
                quick_component = self.component_instance.__class__.from_template(cloned_element.outerHTML)
                childcomponent_py = quick_component
                    
            new_cb = ChildBinding(component_instance=self.component_instance,
                                  node=cloned_element,
                                  childclass=childcomponent_py,
                                  loop_binding=self)
            self.component_instance.add_binding(new_cb)

            custom_child_instance = childcomponent_py.mount(fragment, replace=False, **updated_child_node_attrs)
            new_cb.childinstance = custom_child_instance
        

        # delete old child bindings for this loop
        # we essentially delete all the bindings non-selectively as we have rebuilt new ones
        for rem in bindings_to_delete:
            self.component_instance.remove_binding(rem)
        
        #do the replace
        self.parent.replaceChildren(fragment)

    def marked_for_hydration(self):
        return [self.node, self.parent]


@dataclass
class KeyedLoopBinding(NodeBinding):
    item:str
    collection:str
    clone:object
    parent:object
    key:str
    instances:dict = field(default_factory=dict)

    @property
    def fields(self):
        return [self.collection]

    def _new_clone(self):
        # New creation
        cloned_element = self.clone.cloneNode(True)
        cloned_element.removeAttribute('for')
        cloned_element.removeAttribute('in')
        cloned_element.removeAttribute('key')

        return cloned_element

    def _child_node_attrs_dict(self, item):
        
        item_attr_name = self.item # the "for={single_item}"
        
        updated_child_node_attrs = {item_attr_name: item}
        
        rest_of_fields = [f for f in self.component_instance.__fields__ \
                          if (f != item_attr_name) \
                            and (not inspect.isfunction(getattr(self.component_instance, f))) \
                            and (not f in ["for", "in", "key"])]
        
        for field in rest_of_fields:
            updated_child_node_attrs[field] = getattr(self.component_instance, field)


        if '-' in (tag:=str.lower(self.clone.tagName)):

            formatter = Formatter()

            for c_attr in self.clone.getAttributeNames():
                if c_attr not in updated_child_node_attrs:
                    c_attr_value = self.clone.getAttribute(c_attr)
                    has_expr = any(fname is not None for _, fname, _, _ in formatter.parse(c_attr_value))
                    if has_expr:
                        val = safe_format(c_attr_value, updated_child_node_attrs, ALLOWED_BUILTINS)
                        updated_child_node_attrs[c_attr] = val
                    else:
                        updated_child_node_attrs[c_attr] = c_attr_value

            updated_child_node_attrs.pop('for', None)
            updated_child_node_attrs.pop('in', None)
            updated_child_node_attrs.pop('key', None)

        return updated_child_node_attrs

    def _child_component_class(self):
        cloned_element = self._new_clone()
        if '-' in (tag:=str.lower(cloned_element.tagName)):
            childcomponent_py = self.component_instance.__class__._registry[tag]
        else:
            quick_component = self.component_instance.__class__.from_template(cloned_element.outerHTML)
            childcomponent_py = quick_component

        return childcomponent_py

    def get_collection_keys(self):
        collection_value = getattr(self.component_instance, self.collection, [])

        keys = []

        for i in collection_value:
            if isinstance(i, dict): #i.e. list of dicts
                k_val = i.get(self.key)
            else:
                try:
                    k_val = getattr(i, self.key) #i.e. list of objects that has "key" as attribute
                except AttributeError:
                    k_val = getattr(i, 'get', lambda k: None)(self.key)
            

            keys.append(k_val)

        return keys
    
    def get_collection_items(self):
        collection_value = getattr(self.component_instance, self.collection, [])

        return [i for i in collection_value]
    

    def update(self):

        # keep a reference to child bindings for this loop binding
        related_child_bindings = [cb for cb in self.component_instance.__bindings__ \
                                if isinstance(cb, ChildBinding) \
                                and cb.loop_binding == self]

        
        new_instances = {}
        fragment = self.component_instance._create_document_fragment()
        
        keys = self.get_collection_keys()
        items = self.get_collection_items()

        existing_instances_keys = [ik for ik in self.instances.keys()]
        
        for k_val, i in zip(keys, items):            
            if k_val in existing_instances_keys:
                # Reuse
                child_instance = self.instances[k_val]
                
                updated_child_node_attrs = self._child_node_attrs_dict(i)
                
                # Update props and component reacts
                for k, v in updated_child_node_attrs.items():
                    with child_instance.refrain() as refrained:
                        setattr(refrained, k, v)

                child_instance.__element__.setAttribute('data-item-key', k_val)
                new_instances[k_val] = child_instance

                fragment.appendChild(child_instance.__element__)

            else:
                # New creation
                cloned_element = self._new_clone()
                updated_child_node_attrs = self._child_node_attrs_dict(i)
                

                childcomponent_py = self._child_component_class()
                
                child_instance = childcomponent_py.mount(fragment, replace=False, **updated_child_node_attrs)
                child_instance.__element__.setAttribute('data-item-key', k_val)
                new_instances[k_val] = child_instance


                new_cb = ChildBinding(component_instance=self.component_instance,
                        node=child_instance.__element__,
                        childclass=childcomponent_py,
                        childinstance=child_instance,
                        loop_binding=self)
                self.component_instance.add_binding(new_cb)
                

        # Cleanup old child bindings that are removed
        for k_val, old_instance in self.instances.items():
            if k_val not in new_instances:
                bindings_to_rem = [cb for cb in self.component_instance.__bindings__ if isinstance(cb, ChildBinding) and cb.childinstance == old_instance]
                for rem in bindings_to_rem:
                    self.component_instance.remove_binding(rem)

        self.parent.replaceChildren(fragment)
        self.instances = new_instances

    def marked_for_hydration(self):
        return [self.node, self.parent]

@dataclass
class SlotBinding(NodeBinding):
    name: str | None = None
    is_default: bool = True
    
    @property
    def fields(self):
        return []



def safe_eval(expr_str, context, allowed_builtins):
    try:
        tree = ast.parse(expr_str, mode='eval')
    except Exception as e:
        print(f"Failed to parse {expr_str}: {e}")
        return f"[Error: {expr_str}]"
    
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

        #elif isinstance(node, ast.Str):
        #    return node.s

        #elif isinstance(node, ast.Num):
        #    return node.n

        #elif isinstance(node, ast.NameConstant):
        #    return node.value

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
        print(f"Error evaluating '{expr_str}': {e}", context)
        return f"[Error: {expr_str}]"

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
                    #print("FOUND COMPONENT INSTANCE IN REGISTRY: ")
                    val = getattr(component_instance_registry[component_name], attr_name)
                else:
                    #print("COULD NOT FIND COMPONENT INSTANCE IN THE REGISTRY: ", component_name)
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


def _process_standard_attr_bindings(component_instance, element, attribute_names):

    formatter = Formatter()

    bindings = []
    fields = []
    #print("_process_standard_attr_bindings", component_instance, element, attribute_names)

    for other_attr in attribute_names:
        if other_attr.startswith("{") and other_attr.endswith("}"):
            other_attr_no_braces = other_attr.strip("{}")
            other_attr_value = element.getAttribute(other_attr)
            other_attr_isboolean = True
            
            if (other_attr_value == "") or (other_attr_value == None):
                other_attr_value = other_attr
            
            element.removeAttribute(other_attr)

        else:
            other_attr_no_braces = other_attr
            other_attr_value = element.getAttribute(other_attr)
            other_attr_isboolean = False

        fnames = [fname for _, fname, _, _ in formatter.parse(other_attr_value) if fname is not None]
        has_expr = any(fnames)
        if has_expr:
            fieldnames = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
            bindings.append(AttributeBinding(component_instance=component_instance, node=element, attr=other_attr_no_braces, content=other_attr_value, fields=fieldnames, is_boolean=other_attr_isboolean))
            fields += fieldnames
            
    return bindings, fields


def _process_self_attr_bindings(component_instance, attrs_dict:dict):

    formatter = Formatter()

    bindings = []
    fields = []

    for other_attr, other_attr_value in attrs_dict.items():
        if other_attr.startswith("{") and other_attr.endswith("}"):
            other_attr_no_braces = other_attr.strip("{}")
            other_attr_isboolean = True

            if (other_attr_value == "") or (other_attr_value == None):
                other_attr_value = other_attr
            
            component_instance.__element__.removeAttribute(other_attr)

        else:
            other_attr_no_braces = other_attr
            other_attr_isboolean = False

        try:
            fnames = [fname for _, fname, _, _ in formatter.parse(other_attr_value) if fname is not None]
            has_expr = any(fnames)
            if has_expr:
                fieldnames = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
                if len(fieldnames):
                    bindings.append(SelfAttributeBinding(component_instance=component_instance, node=component_instance.__element__, attr=other_attr_no_braces, content=other_attr_value, fields=fieldnames, is_boolean=other_attr_isboolean))
                    fields += fieldnames
        except:
            continue

    return bindings, fields


def _process_event_attr_bindings(component_instance, element, attribute_names):

    bindings = []
    fields = []

    for event_attr in attribute_names:
        event_attr_value = element.getAttribute(event_attr)
        if event_attr_value.startswith("{") and event_attr_value.endswith("}"):
            event_attr_value = event_attr_value.strip("{}")
            bindings.append(EventBinding(component_instance=component_instance, node=element, event=event_attr, target_fn=event_attr_value))
            fields.append(event_attr_value)
            
    return bindings, fields


def _process_text_bindings(component_instance, textnode):
    
    node = textnode

    formatter = Formatter()

    bindings = []
    fields = []

    if node.parentElement and str.lower(node.parentElement.tagName) == 'style':
        return [], []
    
    text_content = node.textContent
    fnames = [fname for _, fname, _, _ in formatter.parse(text_content) if fname is not None]
    has_expr = any(fnames)
    if has_expr:
        fieldnames = extract_dependencies(text_content, ALLOWED_BUILTINS)
        bindings.append(TextBinding(component_instance=component_instance, \
                                    node=node, \
                                    content=text_content, \
                                    fields=fieldnames, \
                                    parent=node.parentNode))
        fields += fieldnames

    return bindings, fields

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
        
        if len(inner_dict) > 0:
            self.component.react([k for k in inner_dict.keys()])


__all__ = ['Binding', 'SelfBinding', 'TextBinding', 'AttributeBinding', \
            'ModelBinding', 'EventBinding', 'IfBinding', 'ChildBinding', \
            'LoopBinding', 'KeyedLoopBinding', 'SlotBinding', \
            'safe_eval', 'safe_format', 'safe_format_with_stores', \
            'extract_dependencies', 'Refrain', \
            '_process_standard_attr_bindings', '_process_event_attr_bindings', \
            '_process_text_bindings']
