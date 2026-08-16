import ast
from dataclasses import dataclass, field
import inspect
import json
import operator
import re
from string import Formatter
import sys
import traceback
from typing import Any

# Refrain has moved to reactive.py — re-export for backward compatibility
from basis.shared.reactive import Refrain
from basis.shared.validation import validate_field, validate_model, ValidationError
# Phase 5 #4 — structured error capture (see module docstring in errors.py)
from basis.shared.errors import (
    ERROR_PREFIX,
    EVAL_ERROR,
    find_template_line,
    import_error_hint,
    is_error_string,
    record_error,
)


# Module-level singleton — Formatter is stateless, no need to re-instantiate
_FORMATTER = Formatter()

# Module-level operator lookup dicts for _eval_ast (avoid rebuilding per-expression)
_BINOP_MAP = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
    ast.FloorDiv: operator.floordiv,
}

_CMPOP_MAP = {
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


IS_CLIENT = "pyscript" in sys.modules

if IS_CLIENT:
    from pyscript import ffi, document, window
else:
    ffi = None
    document = None
    window = None

class MissingStore:
    def __getattr__(self, name):
        return None
    def __getitem__(self, key):
        return None
    def __bool__(self):
        return False
    def __str__(self):
        return ""
    def __repr__(self):
        return "MissingStore"


def desugar_expression(expr: str) -> str:
    """Transform Basis DSL ($store, #comp) into valid Python (BaseComponent.S['store'], BaseComponent.C['comp'])."""
    if not expr:
        return expr
    # Replace $name with BaseComponent.S['name']
    expr = re.sub(r'\$([a-zA-Z_][a-zA-Z0-9_]*)', r"BaseComponent.S['\1']", expr)
    # Replace #id with BaseComponent.C['id']
    expr = re.sub(r'#([a-zA-Z_][a-zA-Z0-9_]*)', r"BaseComponent.C['\1']", expr)
    return expr

@dataclass
class BindingBlueprint:
    binding_class: type
    node_index: int
    kwargs: dict = field(default_factory=dict)
    ast_trees: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class Binding(object):
    component_instance:"Component"

    @property
    def component_class(self):
        return self.component_instance.__class__

@dataclass(kw_only=True)
class ComponentSubscription(Binding):
    attr:str
    target_instance:Any = None # The component that owns the attribute being subscribed to

    @property
    def subscriber(self):
        return self.component_instance
    
    @property
    def subscribing_component(self):
        return self.component_instance
    
    @property
    def fields(self):
        return [self.attr]
    
    def marked_for_hydration(self):
        return [self.node]
    
    @property
    def node(self):
        return self.subscriber.__element__
    
    def __eq__(self, value):
        if isinstance(value, ComponentSubscription):
            return (value.attr == self.attr) and (value.subscriber is self.subscriber) 
        elif isinstance(value, tuple) and len(value) == 2:
            return (value[1] == self.attr) and (value[0] is self.subscriber) 
        else:
            return super().__eq__(value)
    
    def __iter__(self):
        # Allows: x, y = obj destructuring
        return iter([self.subscriber, self.attr])

    def update(self):
        """Propagate change to the subscribing component."""
        if self.target_instance:
            self_component_id = self.target_instance.__element__.getAttribute("id")
            if self_component_id:
                self.subscriber.react([f"#{self_component_id}.{self.attr}"])


@dataclass(kw_only=True)
class NodeBinding(Binding):
    node:object
    ast_trees: dict

    def marked_for_hydration(self):
        return [self.node]

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        instance = cls(
            component_instance=component_instance, 
            node=node, 
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs, 
        )
        
        # Cross-Boundary Reactive Link Logic
        # Scan fields for DSL prefixes ($ for Store, # for Component)
        if hasattr(blueprint, 'kwargs') and 'fields' in blueprint.kwargs:
            for field in blueprint.kwargs['fields']:
                if "." in field:
                    try:
                        if field.startswith("$"): # Store link
                            store_name, attr = field.strip("$").split(".")
                            registry = component_instance.__class__.S
                            if store_name in registry:
                                target_store = registry[store_name]
                                target_store.add_subscription(component_instance, attr)
                        
                        elif field.startswith("#"): # Component link
                            comp_id, attr = field.strip("#").split(".")
                            registry = component_instance.__class__.C
                            if comp_id in registry:
                                target_comp = registry[comp_id]
                                component_instance.add_subscription(target_comp, attr)
                            else:
                                # Target not found yet — register a pending subscription
                                component_instance.add_pending_subscription(comp_id, attr)
                    except ValueError:
                        pass # malformed dependency
        
        return instance
            
@dataclass(kw_only=True)
class SelfBinding(NodeBinding):
    ast_trees: dict = field(default_factory=dict, init=False, repr=False)
    ...

@dataclass(kw_only=True)
class TextBinding(NodeBinding):
    content:str
    fields:list[str]
    parent:object

    def update(self):

        context = self.component_instance
        store_registry = self.component_instance.__class__.S

        self.node.textContent = safe_format_with_stores(
            self.content, 
            context,
            ALLOWED_BUILTINS, 
            store_registry=store_registry, 
            component_instance_registry=self.component_instance.__class__._instance_registry,
            ast_trees=self.ast_trees,
            component=self.component_instance,
            binding_type="TextBinding",
            template=self.content,
        )

    def marked_for_hydration(self):
        return [self.parent]
    
    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        instance = cls(
            component_instance=component_instance, 
            node=node,
            parent=node.parentNode,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs, 
        )

        return instance
        
@dataclass(kw_only=True)
class AttributeBinding(NodeBinding):
    attr:str
    content:str
    fields:list[str]
    is_boolean:bool = False
    _is_single_expr:bool = field(default=False, init=False, repr=False)
    _single_fname:str = field(default=None, init=False, repr=False)

    def __post_init__(self):
        # Pre-compute whether this is a single expression like "{val}" vs interpolation "count: {val}"
        try:
            parsed = list(_FORMATTER.parse(self.content))
        except ValueError:
            parsed = []
        self._is_single_expr = len(parsed) == 1 and parsed[0][1] is not None and not parsed[0][0]
        if self._is_single_expr:
            self._single_fname = parsed[0][1]

    def update(self):
        # Always evaluate in the context of the component that owns the binding (the parent)
        context = self.component_instance
        store_registry = self.component_instance.__class__.S
        instance_registry = self.component_instance.__class__._instance_registry

        if self._is_single_expr:
            ast_tree = self.ast_trees.get(self._single_fname)
            evaluated_val = safe_eval(self._single_fname, context, ALLOWED_BUILTINS, tree=ast_tree,
                                      component=self.component_instance,
                                      binding_type="AttributeBinding",
                                      template=self.content)
            
            # For the DOM attribute, we convert to string/JSON
            if isinstance(evaluated_val, (list, dict)):
                final_dom_val = json.dumps(evaluated_val)
            else:
                final_dom_val = evaluated_val
        else:
            evaluated_val = safe_format_with_stores(
                self.content,
                context,
                ALLOWED_BUILTINS,
                store_registry=store_registry,
                component_instance_registry=instance_registry,
                ast_trees=self.ast_trees,
                component=self.component_instance,
                binding_type="AttributeBinding",
                template=self.content,
            )
            final_dom_val = evaluated_val

        # Update the DOM node
        if self.is_boolean:
            bool_val = bool(evaluated_val) if self._is_single_expr else str(final_dom_val).lower() == 'true'
            self.node.toggleAttribute(self.attr, bool_val)

            # special cases
            if self.attr == 'selected' \
            and str.lower(getattr(self.node, 'tagName', '')) == 'option':
                self.node.selected = bool_val
            elif self.attr == 'checked' \
            and str.lower(getattr(self.node, 'tagName', '')) == 'input':
                self.node.checked = bool_val
            elif self.attr == 'disabled' and hasattr(self.node, 'disabled'):
                self.node.disabled = bool_val
            elif self.attr == 'readonly' and hasattr(self.node, 'readOnly'):
                self.node.readOnly = bool_val
            elif self.attr == 'required' and hasattr(self.node, 'required'):
                self.node.required = bool_val
            elif self.attr == 'hidden' and hasattr(self.node, 'hidden'):
                self.node.hidden = bool_val

        else:
            self.node.setAttribute(self.attr, str(final_dom_val))

        # Prop Synchronization: If the node is a Basis component instance, update its Python property.
        if hasattr(self.node, '__basis_instance__') and evaluated_val is not EVAL_ERROR:
            child_instance = self.node.__basis_instance__
            # We use the raw evaluated value to maintain object references (lists/dicts)
            # Use setattr to trigger the child's reactivity
            setattr(child_instance, self.attr, evaluated_val)

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):

        attr = blueprint.kwargs["attr"]
        content = blueprint.kwargs["content"]
        fields = blueprint.kwargs["fields"]
        is_boolean = blueprint.kwargs["is_boolean"]

        if is_boolean:
            node.removeAttribute(attr)

        instance = cls(
            component_instance=component_instance,
            node=node,
            attr=attr,
            content=content,
            fields=fields,
            is_boolean=is_boolean,
            ast_trees=blueprint.ast_trees
        )

        return instance

@dataclass(kw_only=True)
class SelfAttributeBinding(AttributeBinding):
    def update(self):
        context = self.component_instance
        store_registry = self.component_instance.__class__.S


        if self.attr not in ["in"]:
            final_val = safe_format_with_stores(self.content,
                                                context,
                                                ALLOWED_BUILTINS,
                                                store_registry,
                                                self.component_instance.__class__._instance_registry,
                                                ast_trees=self.ast_trees,
                                                component=self.component_instance,
                                                binding_type="SelfAttributeBinding",
                                                template=self.content)

            if self.is_boolean:
                bool_val = str(final_val).lower() == 'true'
                # following line was causing circular updates in react()
                setattr(self.component_instance, self.attr, bool_val)
                # replaced with below
                #self.component_instance.__dict__[self.attr] = final_val
            else:
                # following line was causing circular updates in react()
                setattr(self.component_instance, self.attr, final_val)
                # replaced with below
                #self.component_instance.__dict__[self.attr] = final_val

        else:
            _, fname, _, _ = next(iter(_FORMATTER.parse(self.content)))
            evaluated_val = safe_eval(fname, context, ALLOWED_BUILTINS, tree=self.ast_trees.get(fname),
                                      component=self.component_instance,
                                      binding_type="SelfAttributeBinding",
                                      template=self.content)
            if evaluated_val is EVAL_ERROR:
                final_val = ""
            else:
                final_val = json.dumps(evaluated_val)
            #self.component_instance.__dict__[self.attr] = final_val
            setattr(self.component_instance, self.attr, final_val)

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        instance = cls(
            component_instance=component_instance,
            node=node,
            attr=blueprint.kwargs['attr'],
            content=blueprint.kwargs['content'],
            fields=blueprint.kwargs['fields'],
            is_boolean=blueprint.kwargs['is_boolean'],
            ast_trees=blueprint.ast_trees
        )

        if instance.is_boolean:
            node.removeAttribute(blueprint.attr)

        return instance

@dataclass(kw_only=True)
class TextContentAttributeBinding(AttributeBinding):
    is_boolean:bool = field(default=False, init=False, repr=False)

    def update(self):
        # We leverage the base evaluation logic but redirect the output to textContent
        context = self.component_instance
        store_registry = self.component_instance.__class__.S
        instance_registry = self.component_instance.__class__._instance_registry

        final_dom_val = safe_format_with_stores(
            self.content,
            context,
            ALLOWED_BUILTINS,
            store_registry=store_registry,
            component_instance_registry=instance_registry,
            ast_trees=self.ast_trees,
            component=self.component_instance,
            binding_type="TextContentAttributeBinding",
            template=self.content,
        )

        #print("IN TextContentAttributeBinding : final_dom_val", final_dom_val)

        self.node.textContent = str(final_dom_val)

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):

        attr = blueprint.kwargs["attr"]
        content = blueprint.kwargs["content"]
        fields = blueprint.kwargs["fields"]

        instance = cls(
            component_instance=component_instance,
            node=node,
            attr=attr,
            content=content,
            fields=fields,
            ast_trees=blueprint.ast_trees
        )

        return instance

@dataclass(kw_only=True)
class SetterBinding(NodeBinding):
    field: str
    ast_trees: dict = field(default_factory=dict, init=False, repr=False)

    @property
    def fields(self):
        return [self.field]

    def update(self):
        pass

@dataclass(kw_only=True)
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

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        
        bind_attr_value = blueprint.kwargs['field']
        target_fn = "bind_handler"

        input_type = node.getAttribute('type') if hasattr(node, 'hasAttribute') and node.hasAttribute('type') else 'text'

        handler = component_instance._create_update_handler(bind_attr_value, input_type)
        component_instance.__dict__[target_fn] = handler

        instance = cls(
            component_instance=component_instance,
            node=node,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs,
        )

        return instance


def get_input_value(node, name=None):
    tag_name = node.tagName.lower() if hasattr(node, "tagName") else ""
    if tag_name == "input":
        input_type = node.getAttribute("type") if node.hasAttribute("type") else "text"
        if input_type == "checkbox":
            return node.checked
        if input_type == "radio" and name:
            form = node.form or (node.closest("form") if hasattr(node, "closest") else None)
            if form:
                checked_radio = form.querySelector(f"input[type='radio'][name='{name}']:checked")
                return checked_radio.value if checked_radio else None
            return node.value if node.checked else None
        return node.value
    elif tag_name in ("select", "textarea"):
        return node.value
    else:
        inst = getattr(node, "__basis_instance__", None)
        if inst and hasattr(inst, "value"):
            return inst.value
        if hasattr(node, "value"):
            return node.value
        return node.getAttribute("value")

def set_input_value(node, val):
    tag_name = node.tagName.lower() if hasattr(node, "tagName") else ""
    if tag_name == "input":
        input_type = node.getAttribute("type") if node.hasAttribute("type") else "text"
        if input_type == "checkbox":
            node.checked = bool(val)
        elif input_type == "radio":
            node.checked = (str(node.value) == str(val))
        else:
            node.value = str(val) if val is not None else ""
    elif tag_name in ("select", "textarea"):
        node.value = str(val) if val is not None else ""
    else:
        inst = getattr(node, "__basis_instance__", None)
        if inst and hasattr(inst, "value"):
            inst.value = val
        elif hasattr(node, "value"):
            node.value = val
        else:
            node.setAttribute("value", str(val) if val is not None else "")


def instantiate_model(model_class: Any) -> Any:
    try:
        return model_class()
    except Exception:
        # Construct with type-based default arguments to bypass required field validation
        init_args = {}
        if hasattr(model_class, "model_fields"):
            for f_name, f_info in model_class.model_fields.items():
                annotation = f_info.annotation
                if annotation is str:
                    init_args[f_name] = ""
                elif annotation in (int, float):
                    init_args[f_name] = 0
                else:
                    init_args[f_name] = None
        elif dataclasses.is_dataclass(model_class):
            for f in dataclasses.fields(model_class):
                if f.type is str:
                    init_args[f.name] = ""
                elif f.type in (int, float):
                    init_args[f.name] = 0
                else:
                    init_args[f.name] = None
        try:
            return model_class(**init_args)
        except Exception:
            return None


@dataclass(kw_only=True)
class FormModelBinding(NodeBinding):
    target_expression: str
    validate_on: str = "input"

    def __post_init__(self):
        self._node = self.node
        self.errors_expression = ""
        if self.target_expression.startswith("$"):
            parts = self.target_expression.split(".")
            self.errors_expression = f"{parts[0]}.{parts[1]}_errors"
        else:
            self.errors_expression = f"{self.target_expression}_errors"
            
        self._add_listeners(self._node)

    @property
    def node(self):
        return self._node

    @node.setter
    def node(self, val):
        if hasattr(self, "_node") and self._node:
            self._remove_listeners(self._node)
        self._node = val
        if val:
            self._add_listeners(val)

    @property
    def fields(self):
        return [self.target_expression]

    def _add_listeners(self, node):
        if not node:
            return
        self._input_proxy = self.component_instance._create_function_proxy(self.handle_input)
        self._blur_proxy = self.component_instance._create_function_proxy(self.handle_blur)
        self._submit_proxy = self.component_instance._create_function_proxy(self.handle_submit)
        
        if hasattr(node, "addEventListener"):
            node.addEventListener("input", self._input_proxy)
            node.addEventListener("change", self._input_proxy)
            node.addEventListener("blur", self._blur_proxy)
            node.addEventListener("submit", self._submit_proxy)
        else:
            setattr(node, "oninput", self._input_proxy)
            setattr(node, "onchange", self._input_proxy)
            setattr(node, "onblur", self._blur_proxy)
            setattr(node, "onsubmit", self._submit_proxy)

    def _remove_listeners(self, node):
        if not node:
            return
        if hasattr(node, "removeEventListener"):
            if hasattr(self, "_input_proxy"):
                node.removeEventListener("input", self._input_proxy)
                node.removeEventListener("change", self._input_proxy)
            if hasattr(self, "_blur_proxy"):
                node.removeEventListener("blur", self._blur_proxy)
            if hasattr(self, "_submit_proxy"):
                node.removeEventListener("submit", self._submit_proxy)

    def get_target_model(self) -> Any:
        context = self.component_instance
        store_registry = self.component_instance.__class__.S
        instance_registry = self.component_instance.__class__._instance_registry
        
        try:
            ast_tree = self.ast_trees.get(self.target_expression)
            target_obj = safe_eval(
                self.target_expression,
                context,
                ALLOWED_BUILTINS,
                tree=ast_tree,
                component=self.component_instance,
                binding_type="FormModelBinding",
                template=self.target_expression,
            )
        except Exception:
            target_obj = None

        if target_obj is None:
            if self.target_expression.startswith("$"):
                store_name, attr_name = self.target_expression.strip("$").split(".")
                store_instance = store_registry[store_name]
                model_class = getattr(store_instance, "model", None)
                if model_class:
                    target_obj = instantiate_model(model_class)
                    if target_obj is not None:
                        setattr(store_instance, attr_name, target_obj)
            else:
                model_class = None
                cls = self.component_instance.__class__
                if hasattr(cls, "__annotations__") and self.target_expression in cls.__annotations__:
                    model_class = cls.__annotations__[self.target_expression]
                if model_class:
                    target_obj = instantiate_model(model_class)
                    if target_obj is not None:
                        setattr(self.component_instance, self.target_expression, target_obj)
        return target_obj

    def get_errors_dict(self) -> dict:
        if not self.target_expression.startswith("$"):
            if not hasattr(self.component_instance, self.errors_expression):
                setattr(self.component_instance, self.errors_expression, {})
            return getattr(self.component_instance, self.errors_expression)
        else:
            store_name, attr_name = self.target_expression.strip("$").split(".")
            store_instance = self.component_instance.__class__.S[store_name]
            errors_attr = f"{attr_name}_errors"
            if not hasattr(store_instance, errors_attr):
                setattr(store_instance, errors_attr, {})
            return getattr(store_instance, errors_attr)

    def set_errors_dict(self, errors: dict):
        if not self.target_expression.startswith("$"):
            setattr(self.component_instance, self.errors_expression, errors)
        else:
            store_name, attr_name = self.target_expression.strip("$").split(".")
            store_instance = self.component_instance.__class__.S[store_name]
            errors_attr = f"{attr_name}_errors"
            setattr(store_instance, errors_attr, errors)

    def _collect_inputs(self) -> list[tuple[str, Any]]:
        inputs = []
        form_node = self.node
        if not form_node:
            return inputs

        def walk(node):
            if node != form_node:
                tag_name = node.tagName.lower() if hasattr(node, "tagName") else ""
                is_custom = "-" in tag_name
                
                if is_custom:
                    if node.hasAttribute("name") and not node.hasAttribute("bind"):
                        inputs.append((node.getAttribute("name"), node))
                    return
                    
            if node != form_node and hasattr(node, "tagName"):
                tag_name = node.tagName.lower()
                if tag_name in ("input", "select", "textarea"):
                    if node.hasAttribute("name") and not node.hasAttribute("bind"):
                        inputs.append((node.getAttribute("name"), node))
                        
            if hasattr(node, "childNodes"):
                for child in node.childNodes:
                    is_element = (child.nodeType == 1) if hasattr(child, "nodeType") else hasattr(child, "tagName")
                    if is_element:
                        walk(child)

        walk(form_node)
        return inputs

    def handle_input_change(self, field_name: str, raw_value: Any, trigger_validation: bool):
        target_obj = self.get_target_model()
        if not target_obj:
            return

        coerced, err_msg = validate_field(target_obj.__class__, field_name, raw_value)
        errors = self.get_errors_dict()
        
        if trigger_validation:
            if err_msg:
                errors[field_name] = err_msg
            else:
                errors.pop(field_name, None)
        else:
            if not err_msg:
                errors.pop(field_name, None)

        if not err_msg:
            setattr(target_obj, field_name, coerced)

        self.set_errors_dict(errors)
        self.component_instance.react([self.target_expression, self.errors_expression])

    def handle_input(self, event):
        target = event.target
        name = target.getAttribute("name")
        if not name:
            return
        if target.hasAttribute("bind"):
            return

        val = get_input_value(target, name)
        input_type = target.getAttribute("type") if target.hasAttribute("type") else ""
        is_instant = input_type in ("checkbox", "radio") or target.tagName.lower() == "select"
        
        trigger_val = (self.validate_on == "input") or is_instant
        self.handle_input_change(name, val, trigger_validation=trigger_val)

    def handle_blur(self, event):
        target = event.target
        name = target.getAttribute("name")
        if not name:
            return
        if target.hasAttribute("bind"):
            return

        val = get_input_value(target, name)
        trigger_val = (self.validate_on == "blur")
        self.handle_input_change(name, val, trigger_validation=trigger_val)

    def handle_submit(self, event):
        target_obj = self.get_target_model()
        if not target_obj:
            return

        if self.node and self.node.hasAttribute("novalidate"):
            return

        errors = {}
        try:
            validate_model(target_obj)
        except ValidationError as e:
            errors = {err["loc"][0]: err["msg"] for err in e.errors()}

        self.set_errors_dict(errors)
        self.component_instance.react([self.target_expression, self.errors_expression])

        if errors:
            event.preventDefault()
            if IS_CLIENT and hasattr(self.node, "dispatchEvent"):
                detail = ffi.to_js({"errors": errors})
                event_options = {"detail": detail, "bubbles": True, "cancelable": True}
                custom_event = window.CustomEvent.new("invalid", ffi.to_js(event_options))
                self.node.dispatchEvent(custom_event)

    def update(self):
        target_obj = self.get_target_model()
        if not target_obj:
            return

        inputs = self._collect_inputs()
        for name, el in inputs:
            if hasattr(target_obj, name):
                val = getattr(target_obj, name)
                set_input_value(el, val)

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        instance = cls(
            component_instance=component_instance,
            node=node,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs
        )
        return instance


@dataclass(kw_only=True)
class EventBinding(NodeBinding):
    event:str
    target_fn:str

    @property
    def element(self):
        return self.node
    
    @property
    def fields(self):
        return [self.target_fn]
    
    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        
        event = blueprint.kwargs['event']
        target_fn = blueprint.kwargs['target_fn']

        func_obj = getattr(component_instance, target_fn)
        handler = component_instance._create_function_proxy(func_obj)

        if node.hasAttribute(event):
            node.removeAttribute(event)

        # print("######## SETTING EVENT BINDING:", target_fn, "on", component_instance.__class__)
        if hasattr(node, "addEventListener"):
            # on the client
            node.addEventListener(event.removeprefix("on"), handler)
        else:
            # on the server (no addEventListener on server Element instances)
            setattr(node, event, handler)
        
        instance = cls(
            component_instance=component_instance,
            node=node,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs,
        )

        return instance

@dataclass(kw_only=True)
class IfBinding(NodeBinding):
    expr: str
    anchor: object
    is_visible: bool
    fields: list

    def update(self):
        expr_eval = bool(safe_eval(self.expr, self.component_instance, ALLOWED_BUILTINS, tree=self.ast_trees.get(self.expr),
                                   component=self.component_instance,
                                   binding_type="IfBinding",
                                   template=self.expr))
        if expr_eval == self.is_visible:
            return  # visibility unchanged — skip DOM mutation
        if expr_eval == False:
            self.node.remove()
        else:
            self.anchor.after(self.node)
        self.is_visible = expr_eval

    def marked_for_hydration(self):
        return [self.node, self.anchor]

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        if_expr_clean = blueprint.kwargs['expr']
        anchor = component_instance._create_element(f"div")
        anchor.setAttribute("style", "display: contents;")
        anchor.setAttribute("data-if-expression", "{" + if_expr_clean + "}")
        
        node.parentNode.insertBefore(anchor, node)
        
        return cls(
            component_instance=component_instance, 
            node=node,
            anchor=anchor,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs
        )


@dataclass(kw_only=True)
class ChildBinding(NodeBinding):
    childclass:str
    childinstance:object=None
    attr_bindings:"list[SelfAttrBinding]"=field(default_factory=list)
    loop_binding:"LoopBinding|KeyedLoopBinding|None"=None
    ast_trees: dict = field(default_factory=dict, init=True, repr=False)

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        tag = blueprint.kwargs['tag']
        childcomponent_py = component_instance.__class__._registry[tag]

        # Only attributes with NO template expressions flow through to the
        # child's mount() as creation kwargs.  An attribute like
        # heading="{sign_heading}" is a PARENT-scope binding: the parent's
        # AttributeBinding (and EventBinding for on* attrs) owns the expression,
        # evaluates it in the parent's scope and syncs the rendered value onto
        # the child's prop.  Passing the raw "{...}" value as a creation kwarg
        # would make the CHILD synthesise a SelfAttributeBinding and evaluate
        # the parent's expression in the child's scope — NameError.  Static
        # attrs (label="...", variant="primary") still flow through as plain
        # instance attributes.
        dom_child_node_attrs = {}
        for a in node.getAttributeNames():
            value = node.getAttribute(a)
            fieldnames, _ = extract_dependencies(value or "", ALLOWED_BUILTINS)
            if fieldnames:
                continue
            dom_child_node_attrs[a] = value

        if not getattr(node, '__basis_mounted__', False):
            child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)
            node.__basis_mounted__ = True
            # CRITICAL: This links the DOM wrapper node to the Python component instance. 
            # It enables AttributeBinding.update() on the parent to correctly sync reactive 
            # property changes down to the child component instance.
            setattr(node, '__basis_instance__', child_instance)
            
            return cls(
                component_instance=component_instance, 
                node=node, 
                childclass=childcomponent_py, 
                childinstance=child_instance, 
                ast_trees=blueprint.ast_trees,
            )

        return None

@dataclass(kw_only=True)
class LoopBinding(NodeBinding):
    """
    High-performance loop reconciliation using the Longest Increasing Subsequence (LIS) algorithm.
    Supports explicit keyed reconciliation (key="id") and index-based fallback reconciliation (0, 1, 2...).
    """
    item: str
    collection: str
    clone: object
    parent: object
    key: str | None = None
    instances: dict = field(default_factory=dict)
    ast_trees: dict = field(default_factory=dict, repr=False)

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

    def _get_rest_of_fields(self):
        """Cache the list of passthrough fields — it doesn't change between update cycles."""
        if not hasattr(self, '_cached_rest_of_fields'):
            item_attr_name = self.item
            rest = []
            for f in self.component_instance.__fields__:
                try:
                    if f in ("for", "in", "key"):
                        continue
                    elif f == item_attr_name:
                        continue
                    elif f.startswith(("#", "$")):
                        continue
                    elif inspect.isfunction(getattr(self.component_instance, f)):
                        continue
                    else:
                        rest.append(f)
                except:
                    continue
            self._cached_rest_of_fields = rest
        return self._cached_rest_of_fields

    def _child_node_attrs_dict(self, item):
        item_attr_name = self.item # the "for={single_item}"
        updated_child_node_attrs = {item_attr_name: item}

        for field in self._get_rest_of_fields():
            updated_child_node_attrs[field] = getattr(self.component_instance, field)

        if '-' in (tag:=str.lower(self.clone.tagName)):
            c_attr_names = self.clone.getAttributeNames()
            for c_attr in c_attr_names:
                # Loop-control attributes (for/in/key) are not child props —
                # never format or pass them down.  In particular
                # in="{$store.items}" is a $-store expression that cannot be
                # resolved against the per-item attrs dict and would previously
                # raise "invalid syntax" on every loop update.
                if c_attr in ("for", "in", "key"):
                    continue
                if c_attr not in updated_child_node_attrs:
                    c_attr_value = self.clone.getAttribute(c_attr)
                    has_expr = any(fname is not None for _, fname, _, _ in _FORMATTER.parse(c_attr_value))
                    if has_expr:
                        val = safe_format(c_attr_value, updated_child_node_attrs, ALLOWED_BUILTINS,
                                          component=self.component_instance,
                                          binding_type="LoopBinding",
                                          template=c_attr_value)
                        updated_child_node_attrs[c_attr] = val
                    else:
                        updated_child_node_attrs[c_attr] = c_attr_value

            updated_child_node_attrs.pop('for', None)
            updated_child_node_attrs.pop('in', None)
            updated_child_node_attrs.pop('key', None)

        return updated_child_node_attrs

    def _child_component_class(self, **kwargs):
        cloned_element = self._new_clone()
        if '-' in (tag:=str.lower(cloned_element.tagName)):
            childcomponent_py = self.component_instance.__class__._registry[tag]
        else:
            quick_component = self.component_instance.__class__.from_template(cloned_element.outerHTML, **kwargs)
            childcomponent_py = quick_component

        return childcomponent_py

    def get_collection_keys(self):
        collection_value = getattr(self.component_instance, self.collection, [])
        if collection_value is None:
            collection_value = []

        keys = []
        if self.key is not None:
            for i in collection_value:
                if isinstance(i, dict):
                    k_val = i.get(self.key)
                else:
                    try:
                        k_val = getattr(i, self.key)
                    except AttributeError:
                        k_val = getattr(i, 'get', lambda k: None)(self.key)
                keys.append(k_val)
        else:
            keys = list(range(len(collection_value)))

        return keys

    def get_collection_items(self):
        collection_value = getattr(self.component_instance, self.collection, [])
        if collection_value is None:
            collection_value = []

        return collection_value

    def update(self):
        # Build ChildBinding lookup map for O(1) lookups
        _cb_by_instance = {id(cb.childinstance): cb for cb in self.component_instance.__bindings__ if isinstance(cb, ChildBinding) and cb.loop_binding is self}

        # 1. Prepare data
        new_keys = self.get_collection_keys()
        new_items = self.get_collection_items()
        # 2. Removal Phase
        # Find instances that are no longer in the new keys
        new_keys_set = set(new_keys)
        removed_keys = [k for k in self.instances.keys() if k not in new_keys_set]

        for r_key in removed_keys:
            old_instance = self.instances[r_key]
            # Remove from DOM (handling custom elements by removing the wrapper node)
            cb = _cb_by_instance.get(id(old_instance))
            if cb:
                node_to_remove = cb.node
                if node_to_remove and node_to_remove.parentNode:
                    node_to_remove.remove()
            else:
                if old_instance.__element__ and old_instance.__element__.parentNode:
                    old_instance.__element__.remove()
            
            # Remove associated bindings from the parent component
            if cb:
                self.component_instance.remove_binding(cb)
            
            # Remove from our instance map
            del self.instances[r_key]
        
        # 3. Creation & Update Phase
        new_instances_list = []
        sources = [-1] * len(new_keys)
        
        # Mapping old_key -> stable index for LIS
        # We use the order keys were in before the update
        old_keys_list = list(self.instances.keys())
        old_key_to_idx = {k: i for i, k in enumerate(old_keys_list)}

        new_instances_map = {}

        for i, (k_val, item) in enumerate(zip(new_keys, new_items)):
            if k_val in self.instances:
                # Reuse existing instance
                child_instance = self.instances[k_val]
                updated_child_node_attrs = self._child_node_attrs_dict(item)
                
                # Update properties (using refrain to batch reactions)
                with child_instance.refrain() as refrained:
                    for k, v in updated_child_node_attrs.items():
                        setattr(refrained, k, v)
                
                sources[i] = old_key_to_idx[k_val]
                new_instances_map[k_val] = child_instance
                
                # Ensure data-item-key is set on the correct node
                existing_cb = _cb_by_instance[id(child_instance)]
                existing_cb.node.setAttribute('data-item-key', str(k_val))
            else:
                # New creation — mount immediately after the template node (self.node)
                # so items appear in insertion order without a separate reorder pass.
                cloned_element = self._new_clone()
                updated_child_node_attrs = self._child_node_attrs_dict(item)
                childcomponent_py = self._child_component_class(**updated_child_node_attrs)

                if '-' in (tag:=str.lower(cloned_element.tagName)):
                    child_instance = childcomponent_py.mount(cloned_element, replace=False, **updated_child_node_attrs)
                    target_node = cloned_element
                    setattr(target_node, '__basis_instance__', child_instance)
                else:
                    # Use a temporary fragment then insertBefore to place correctly
                    fragment = self.component_instance._create_document_fragment()
                    child_instance = childcomponent_py.mount(fragment, replace=False, **updated_child_node_attrs)
                    target_node = child_instance.__element__

                target_node.setAttribute('data-item-key', str(k_val))
                
                # Find anchor: after the last-inserted item, or before _after_node for the first
                if new_instances_list:
                    # Search for the ChildBinding to get the node
                    last_cb = _cb_by_instance[id(new_instances_list[-1])]
                    insert_after = last_cb.node
                    anchor = insert_after.nextSibling
                else:
                    # First item: insert at the slot where the template was
                    anchor = getattr(self, '_after_node', None)

                # Ensure anchor is actually a child of the parent
                if anchor is not None:
                    try:
                        if getattr(anchor, 'parentNode', None) != self.parent:
                            anchor = None
                    except Exception:
                        anchor = None

                self.parent.insertBefore(target_node, anchor)
                
                new_cb = ChildBinding(component_instance=self.component_instance,
                                      node=target_node,
                                      childclass=childcomponent_py,
                                      childinstance=child_instance,
                                      loop_binding=self)
                self.component_instance.add_binding(new_cb)
                _cb_by_instance[id(child_instance)] = new_cb
                
                new_instances_map[k_val] = child_instance
                sources[i] = -1

            new_instances_list.append(new_instances_map[k_val])

        # 4. Movement Phase (LIS) — only needed when existing items may have moved
        # If all items are new (sources all -1) they are already in order, skip.
        has_existing = any(s != -1 for s in sources)
        if has_existing:
            actual_sources = [s for s in sources if s != -1]
            lis_values_indices = get_lis_indices(actual_sources)
            
            # Map LIS indices back to the 'sources' (new list) indices
            lis_indices_in_new_list = set()
            j = 0
            for i, s in enumerate(sources):
                if s != -1:
                    if j in lis_values_indices:
                        lis_indices_in_new_list.add(i)
                    j += 1

            # 5. Reorder items in DOM (backwards for stable insertBefore)
            # Start anchor from the end of our known item block
            last_cb = _cb_by_instance[id(new_instances_list[-1])]
            last_item_node = last_cb.node
            next_node = last_item_node.nextSibling
            for i in range(len(new_keys) - 1, -1, -1):
                instance = new_instances_list[i]
                # Find the node from the existing ChildBinding
                cb = _cb_by_instance[id(instance)]
                node = cb.node
                
                # Move if it is a new item (sources[i] == -1) OR an existing item not in LIS
                if sources[i] == -1 or i not in lis_indices_in_new_list:
                    if node.nextSibling != next_node:
                        self.parent.insertBefore(node, next_node)
                
                next_node = node

        self.instances = new_instances_map

    def marked_for_hydration(self):
        return [self.node, self.parent, *[inst.__element__ for inst in self.instances.values() if inst.__element__ is not None]]

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        cloned_node = node.cloneNode(True)
        
        # Capture parent and the sibling that comes after the template node,
        # then remove the template node entirely from the DOM.
        # (Must capture before remove() since parentNode becomes None after.)
        parent_node = node.parentNode
        after_node = node.nextSibling
        node.remove()
        
        instance = cls(
            component_instance=component_instance, 
            node=node,
            clone=cloned_node,
            parent=parent_node,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs,
        )
        
        instance._after_node = after_node
        
        return instance

@dataclass
class SlotBinding(NodeBinding):
    name: str | None = None
    is_default: bool = True
    
    @property
    def fields(self):
        return []



def _eval_ast(node, context, allowed_builtins):
    def _eval(node):
        if isinstance(node, ast.Expression):
            return _eval(node.body)

        elif isinstance(node, ast.Name):
            if node.id in allowed_builtins:
                return allowed_builtins[node.id]

            # Check context (can be a dict or a component instance)
            if isinstance(context, dict):
                if node.id in context:
                    return context[node.id]
            else:
                if hasattr(context, node.id):
                    return getattr(context, node.id)
            
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
            
            base_comp = allowed_builtins.get('BaseComponent')
            if base_comp and val is getattr(base_comp, 'S', None):
                if key not in val:
                    return MissingStore()
            return val[key]

        elif isinstance(node, ast.Call):
            func = _eval(node.func)
            args = [_eval(arg) for arg in node.args]
            kwargs = {kw.arg: _eval(kw.value) for kw in node.keywords}
            return func(*args, **kwargs)

        elif isinstance(node, ast.Constant):
            return node.value

        elif isinstance(node, ast.BinOp):
            left = _eval(node.left)
            right = _eval(node.right)
            op_type = type(node.op)
            if op_type in _BINOP_MAP:
                return _BINOP_MAP[op_type](left, right)
            raise ValueError(f"Unsupported binop {op_type}")

        elif isinstance(node, ast.Compare):
            left = _eval(node.left)
            for op, comparator in zip(node.ops, node.comparators):
                right = _eval(comparator)
                op_type = type(op)
                if op_type == ast.NotIn:
                    res = not operator.contains(right, left)
                elif op_type in _CMPOP_MAP:
                    if op_type == ast.In:
                        res = _CMPOP_MAP[op_type](right, left)
                    else:
                        res = _CMPOP_MAP[op_type](left, right)
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
                last_val = None
                for val in node.values:
                    last_val = _eval(val)
                    if not last_val:
                        return last_val
                return last_val
            elif isinstance(node.op, ast.Or):
                last_val = None
                for val in node.values:
                    last_val = _eval(val)
                    if last_val:
                        return last_val
                return last_val

        else:
            raise ValueError(f"Unsupported AST node type: {type(node).__name__}")
            
    return _eval(node)

def _report_binding_error(
    expr_str,
    context,
    exc,
    *,
    component=None,
    binding_type=None,
    template=None,
    template_line=None,
    stage="eval",
):
    """Record a structured :class:`BindingError` (when a sink is registered) and
    tell the caller whether it was handled.

    Returns True when a sink consumed the record — the caller should then return
    the empty value (``""``) so the raw ``[Error: ...]`` string never reaches the
    rendered DOM.  Returns False when no sink is installed; the caller keeps the
    legacy ``[Error: ...]`` sentinel (transition path).
    """
    # Callers pass a component *instance*; the record stores the class name
    # (instances are not JSON-serializable and are useless to an overlay).
    if component is not None and not isinstance(component, str):
        _cls = getattr(component, "__class__", component)
        component = getattr(_cls, "__name__", None) or str(component)
    elif component is None and not isinstance(context, dict):
        _cls = getattr(context, "__class__", None)
        if _cls is not None:
            component = getattr(_cls, "__name__", None) or type(context).__name__

    # Prefer the component's authored template for ``template_line`` reporting
    # (it has real line numbers); fall back to the binding's own content, then
    # the expression itself.
    src_template = None
    if not isinstance(component, str) and component is not None:
        src_template = getattr(getattr(component, "__class__", None), "__templatestr__", None)
    if src_template is None and not isinstance(context, dict):
        src_template = getattr(getattr(context, "__class__", None), "__templatestr__", None)
    if src_template:
        template = src_template
    if template is None:
        template = expr_str
    if template_line is None:
        template_line = find_template_line(template, expr_str)

    phase = "client" if IS_CLIENT else "server"
    recorded = record_error(
        component=component,
        binding_type=binding_type,
        expr=expr_str,
        template=template,
        error=str(exc),
        traceback=traceback.format_exc(),
        phase=phase,
        template_line=template_line,
        hint=import_error_hint(exc, phase),
    )

    # Server-side: keep a log line (the overlay lives on the client).
    # Client-side: the overlay/global replace console spam, so only log when
    # nothing consumed the record (legacy path).  Also fixes the old bug where
    # ``context`` was passed as print's ``file=`` positional argument.
    if not recorded or phase == "server":
        location = f" ({binding_type})" if binding_type else ""
        print(f"[basis] {stage} error evaluating '{expr_str}'{location}: {exc}")
    return recorded


def safe_eval(expr_str, context, allowed_builtins, tree=None, *,
              component=None, binding_type=None, template=None, template_line=None,
              record=True):

    if expr_str in allowed_builtins:
        return allowed_builtins[expr_str]

    if tree is None:
        try:
            tree = ast.parse(expr_str, mode='eval')
            #desugared = desugar_expression(expr_str)
            #tree = ast.parse(desugared, mode='eval')
        except Exception as e:
            if not record:
                return ""
            if _report_binding_error(expr_str, context, e, component=component,
                                     binding_type=binding_type, template=template,
                                     template_line=template_line, stage="parse"):
                return EVAL_ERROR
            return f"{ERROR_PREFIX}{expr_str}]"

    try:
        return _eval_ast(tree.body if isinstance(tree, ast.Expression) else tree, context, allowed_builtins)
    except Exception as e:
        if not record:
            return ""
        if _report_binding_error(expr_str, context, e, component=component,
                                 binding_type=binding_type, template=template,
                                 template_line=template_line, stage="eval"):
            return EVAL_ERROR
        return f"{ERROR_PREFIX}{expr_str}]"

def safe_format(template_str, context, allowed_builtins, *,
                component=None, binding_type=None, template=None, template_line=None,
                record=True):

    result = ""
    fname = None
    try:
        formatter = Formatter()
        for literal_text, fname, format_spec, conversion in formatter.parse(template_str):
            result += literal_text
            if fname is not None:
                val = safe_eval(fname, context, allowed_builtins,
                                component=component, binding_type=binding_type,
                                template=template, template_line=template_line,
                                record=record)
                if val is EVAL_ERROR:
                    # A field failed and was recorded — abort the whole template
                    # to the empty value rather than returning a partial string.
                    return ""
                if format_spec:
                    result += format(val, format_spec)
                else:
                    result += str(val)
    except Exception as e:
        if not record:
            return ""
        if _report_binding_error(fname or template_str, context, e,
                                 component=component, binding_type=binding_type,
                                 template=template or template_str,
                                 template_line=template_line, stage="eval"):
            return ""
        return f"{ERROR_PREFIX}{template_str}]"
    return result

def safe_format_with_stores(template_str, context, allowed_builtins, store_registry, component_instance_registry, ast_trees=None, *,
                            component=None, binding_type=None, template=None, template_line=None,
                            record=True):

    result = ""
    fname = None
    try:
        for literal_text, fname, format_spec, conversion in _FORMATTER.parse(template_str):
            result += literal_text
            if fname is not None:
                if fname in allowed_builtins:
                    val = allowed_builtins[fname]
                else:
                    ast_tree = ast_trees.get(fname) if ast_trees else None

                    # If we have an AST tree, it should be the desugared one.
                    # safe_eval will handle evaluating BaseComponent.S[...] or BaseComponent.C[...]
                    # if we provide the tree.
                    if ast_tree:
                        val = safe_eval(fname, context, allowed_builtins, tree=ast_tree,
                                        component=component, binding_type=binding_type,
                                        template=template, template_line=template_line,
                                        record=record)
                    elif fname.startswith("$"):
                        store_name, attr_name = fname.strip("$").split(".")
                        store = store_registry.get(store_name)
                        if store is None:
                            val = None
                        else:
                            val = getattr(store, attr_name, None)
                    elif fname.startswith("#"):
                        component_name, attr_name = fname.strip("#").split(".")
                        if component_name in component_instance_registry:
                            val = getattr(component_instance_registry[component_name], attr_name)
                        else:
                            val = ""
                    else:
                        val = safe_eval(fname, context, allowed_builtins,
                                        component=component, binding_type=binding_type,
                                        template=template, template_line=template_line,
                                        record=record)

                if val is EVAL_ERROR:
                    # A field failed and was recorded — abort the whole template
                    # to the empty value rather than returning a partial string.
                    return ""
                if val is None:
                    val = ""

                if format_spec:
                    result += format(val, format_spec)
                else:
                    result += str(val)
    except Exception as e:
        if not record:
            return ""
        if _report_binding_error(fname or template_str, context, e,
                                 component=component, binding_type=binding_type,
                                 template=template or template_str,
                                 template_line=template_line, stage="eval"):
            return ""
        return f"{ERROR_PREFIX}{template_str}]"

    return result

def extract_dependencies(template_str, allowed_builtins=ALLOWED_BUILTINS):
    """
    Extracts dependencies from a template string and returns a tuple:
    (list of dependencies, dictionary of desugared AST trees mapping fname -> tree).
    """
    deps = set()
    trees = {}

    try:
        parsed_template = list(_FORMATTER.parse(template_str))
    except ValueError:
        # Handle cases where template_str is not a valid format string (e.g. CSS)
        return [], {}
    
    fnames = [fname for _, fname, _, _ in parsed_template if fname is not None]
    
    has_expr = any(fnames)

    if not has_expr:
        return [], {}
    
    for fname in fnames:

        desugared = desugar_expression(fname)

        try:
            tree = ast.parse(desugared, mode='eval')
            trees[fname] = tree

            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    if node.id not in allowed_builtins and node.id not in ['BaseComponent'] and isinstance(getattr(node, 'ctx', None), ast.Load):
                        deps.add(node.id)
                elif isinstance(node, ast.Attribute):
                    # Detect BaseComponent.S['store'].attr or BaseComponent.C['comp'].attr
                    if isinstance(node.value, ast.Subscript) and \
                       isinstance(node.value.value, ast.Attribute) and \
                       isinstance(node.value.value.value, ast.Name) and \
                       node.value.value.value.id == 'BaseComponent' and \
                       node.value.value.attr in ['S', 'C']:
                        
                        s_name = None
                        if isinstance(node.value.slice, ast.Constant):
                            s_name = node.value.slice.value
                        elif hasattr(ast, 'Index') and isinstance(node.value.slice, ast.Index) and isinstance(node.value.slice.value, ast.Constant):
                            s_name = node.value.slice.value.value
                        
                        if s_name:
                            prefix = '$' if node.value.value.attr == 'S' else '#'
                            deps.add(f"{prefix}{s_name}.{node.attr}")
                
                elif isinstance(node, ast.Subscript):
                    # Fallback for just BaseComponent.S['store'] without attribute
                    if isinstance(node.value, ast.Attribute) and \
                       isinstance(node.value.value, ast.Name) and \
                       node.value.value.id == 'BaseComponent' and \
                       node.value.attr in ['S', 'C']:
                        
                        s_name = None
                        if isinstance(node.slice, ast.Constant):
                            s_name = node.slice.value
                        elif hasattr(ast, 'Index') and isinstance(node.slice, ast.Index) and isinstance(node.slice.value, ast.Constant):
                            s_name = node.slice.value.value
                        
                        if s_name:
                            prefix = '$' if node.value.attr == 'S' else '#'
                            deps.add(f"{prefix}{s_name}")

        except SyntaxError:
            print(f"Error parsing expression: {desugared}")
        except Exception as e:
            print(f"Error extracting dependencies for {desugared}: {e}")

    return list(deps), trees


def _process_standard_attr_bindings(component_instance, element, attribute_names):

    bindings = []
    fields = []

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

        fieldnames, ast_trees_dict = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
        if len(fieldnames):
            bindings.append(AttributeBinding(component_instance=component_instance, node=element, attr=other_attr_no_braces, content=other_attr_value, fields=fieldnames, is_boolean=other_attr_isboolean))
            fields += fieldnames
            
    return bindings, fields


def _process_self_attr_bindings(component_instance, attrs_dict:dict):

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
            fieldnames, ast_trees_dict = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
            if len(fieldnames):
                bindings.append(SelfAttributeBinding(
                    component_instance=component_instance,
                    node=component_instance.__element__,
                    attr=other_attr_no_braces,
                    content=other_attr_value,
                    fields=fieldnames,
                    is_boolean=other_attr_isboolean,
                    ast_trees=ast_trees_dict)
                )
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

    bindings = []
    fields = []

    if node.parentElement and str.lower(node.parentElement.tagName) in ['style', 'script']:
        return [], []
    
    text_content = node.textContent
    
    fieldnames, ast_trees_dict = extract_dependencies(text_content, ALLOWED_BUILTINS)

    if len(fieldnames):
        bindings.append(TextBinding(component_instance=component_instance, \
                                    node=node, \
                                    content=text_content, \
                                    fields=fieldnames, \
                                    parent=node.parentNode))
        fields += fieldnames

    return bindings, fields



def get_lis_indices(arr: list[int]) -> list[int]:
    """
    Finds the indices of the longest increasing subsequence in O(n log n).
    Example: [1, 3, 0, 2, 4] -> [0, 1, 4] (values 1, 3, 4)
    """
    if not arr:
        return []
        
    p = [0] * len(arr)
    m = [0] * (len(arr) + 1)
    l = 0
    
    for i in range(len(arr)):
        # Binary search for the smallest value in m >= arr[i]
        lo = 1
        hi = l
        while lo <= hi:
            mid = (lo + hi) // 2
            if arr[m[mid]] < arr[i]:
                lo = mid + 1
            else:
                hi = mid - 1
        
        new_l = lo
        p[i] = m[new_l - 1]
        m[new_l] = i
        
        if new_l > l:
            l = new_l
            
    # Backtrack
    res = [0] * l
    k = m[l]
    for i in range(l - 1, -1, -1):
        res[i] = k
        k = p[k]
        
    return res

__all__ = ['Binding', 'SelfBinding', 'TextBinding', 'AttributeBinding', \
            'ModelBinding', 'EventBinding', 'IfBinding', 'ChildBinding', \
            'LoopBinding', 'SlotBinding', \
            'safe_eval', 'safe_format', 'safe_format_with_stores', \
            'extract_dependencies', 'Refrain', \
            '_process_standard_attr_bindings', '_process_event_attr_bindings', \
            '_process_text_bindings']
