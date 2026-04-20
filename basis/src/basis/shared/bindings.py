import ast
from dataclasses import dataclass, field
import operator
from string import Formatter
from typing import Any


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
class SelfAttributeBinding(AttributeBinding):
    ...

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
    attr_bindings:list[AttributeBinding] = field(default_factory=list)

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

    for other_attr in attribute_names:
        if other_attr.startswith("{") and other_attr.endswith("}"):
            other_attr_no_braces = other_attr.strip("{}")
            other_attr_value = element.getAttribute(other_attr)
            other_attr_isboolean = True
            
            if other_attr_value == "":
                other_attr_value = other_attr
            
            element.removeAttribute(other_attr)

        else:
            other_attr_no_braces = other_attr
            other_attr_value = element.getAttribute(other_attr)
            other_attr_isboolean = False

        print(other_attr, other_attr_value)
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
            
            if other_attr_value == "":
                other_attr_value = other_attr
            
            #element.removeAttribute(other_attr)

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
        bindings.append(TextBinding(component_instance=component_instance, node=node, content=text_content, fields=fieldnames))
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
