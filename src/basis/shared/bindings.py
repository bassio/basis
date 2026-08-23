import dataclasses
from dataclasses import dataclass, field
import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    # BaseComponent is the common base of the client/server Component classes
    # (which live in modules that import bindings), so it can only be
    # referenced as a type here, never imported at runtime.
    from basis.shared.base_component import BaseComponent

# Refrain has moved to reactive.py — re-export for backward compatibility
from basis.shared.reactive import Refrain
from basis.shared.validation import validate_field, validate_model, ValidationError
# Error sentinels used by binding updates; the structured recording
# machinery lives in expr.py (see its module docstring).
from basis.shared.errors import (
    ERROR_PREFIX,
    EVAL_ERROR,
    SILENT_ERROR,
)

# The safe expression language (desugar, _eval_ast, safe_eval, safe_format,
# extract_dependencies, LoopScope, ALLOWED_BUILTINS, _FORMATTER,
# IS_CLIENT/ffi/window, _report_binding_error).  Re-exported here for backwards
# compatibility — base_component, store_provider and several tests import them
# from ``basis.shared.bindings``.
from basis.shared.expr import (
    ALLOWED_BUILTINS,
    IS_CLIENT,
    LoopScope,
    _FORMATTER,
    _report_binding_error,
    desugar_expression,
    extract_dependencies,
    ffi,
    safe_eval,
    safe_format,
    window,
)

# Loop re-pointing to the live SSR tree lives in hydration.py (the module that
# owns canonical paths); the loop engine lives in loop.py.
from basis.shared.hydration import repoint_loop_to_ssr
from basis.shared.loop import (
    LoopBodyBuilder,
    LoopItem,
    Reconciler,
    derive_keys,
)


@dataclass
class BindingBlueprint:
    binding_class: type
    node_index: int
    kwargs: dict = field(default_factory=dict)
    ast_trees: dict = field(default_factory=dict)


@dataclass(kw_only=True)
class Binding(object):
    component_instance: "BaseComponent"

    @property
    def component_class(self):
        return self.component_instance.__class__

    # --- Lifecycle ---------------------------------------------------------
    # Uniform contract: from_blueprint is PURE construction; DOM setup happens
    # in activate() (once, at mount — called by add_binding / loop-body
    # instantiation); update() syncs state -> DOM; destroy() tears down
    # (called by remove_binding / LoopItem.dispose).  Listener bindings
    # implement attach(to_node) / detach(); structural bindings override
    # activate()/destroy() directly.  The base defaults make the lifecycle a
    # no-op until a subclass opts in.

    def activate(self):
        """One-time mount setup: wire DOM listeners to the binding's node.

        Base implementation calls ``attach(self.node)`` when the subclass
        provides one; structural subclasses override this directly.
        """
        attach = getattr(self, "attach", None)
        if attach is not None:
            attach(self.node)

    def destroy(self):
        """Teardown: detach listeners / unmount children.

        Base implementation calls ``detach()`` when the subclass provides one;
        structural subclasses override this directly.
        """
        detach = getattr(self, "detach", None)
        if detach is not None:
            detach()

@dataclass(kw_only=True)
class NodeBinding(Binding):
    node:object
    ast_trees: dict
    scope: object = field(default=None, repr=False)

    def marked_for_hydration(self):
        return [self.node]

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        # Pure construction — component/store subscriptions are wired in
        # BaseComponent.__init_fields__.
        return cls(
            component_instance=component_instance, 
            node=node, 
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs, 
        )
            
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

        self.node.textContent = safe_format(
            self.content,
            context,
            ALLOWED_BUILTINS,
            ast_trees=self.ast_trees,
            component=self.component_instance,
            binding_type="TextBinding",
            template=self.content,
            scope=self.scope,
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

        if self._is_single_expr:
            ast_tree = self.ast_trees.get(self._single_fname)
            evaluated_val = safe_eval(self._single_fname, context, ALLOWED_BUILTINS, tree=ast_tree,
                                      component=self.component_instance,
                                      binding_type="AttributeBinding",
                                      template=self.content,
                                      scope=self.scope)
            
            # For the DOM attribute, we convert to string/JSON
            if isinstance(evaluated_val, (list, dict)):
                final_dom_val = json.dumps(evaluated_val)
            else:
                final_dom_val = evaluated_val
        else:
            evaluated_val = safe_format(
                self.content,
                context,
                ALLOWED_BUILTINS,
                ast_trees=self.ast_trees,
                component=self.component_instance,
                binding_type="AttributeBinding",
                template=self.content,
                scope=self.scope,
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

        if self.attr not in ["in"]:
            final_val = safe_format(self.content,
                                    context,
                                    ALLOWED_BUILTINS,
                                    ast_trees=self.ast_trees,
                                    component=self.component_instance,
                                    binding_type="SelfAttributeBinding",
                                    template=self.content,
                                    scope=self.scope)

            if self.is_boolean:
                bool_val = str(final_val).lower() == 'true'
                setattr(self.component_instance, self.attr, bool_val)
            else:
                setattr(self.component_instance, self.attr, final_val)

        else:
            _, fname, _, _ = next(iter(_FORMATTER.parse(self.content)))
            evaluated_val = safe_eval(fname, context, ALLOWED_BUILTINS, tree=self.ast_trees.get(fname),
                                      component=self.component_instance,
                                      binding_type="SelfAttributeBinding",
                                      template=self.content,
                                      scope=self.scope)
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

        final_dom_val = safe_format(
            self.content,
            context,
            ALLOWED_BUILTINS,
            ast_trees=self.ast_trees,
            component=self.component_instance,
            binding_type="TextContentAttributeBinding",
            template=self.content,
            scope=self.scope,
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
    _input_type: str = field(default="text", init=False, repr=False)
    _bound_event: str = field(default="input", init=False, repr=False)

    @property
    def fields(self):
        return [self.field]

    @staticmethod
    def _bound_event_for(node, input_type):
        """The DOM event that syncs this input: 'change' for checkbox/radio/
        select (their value only commits on change), 'input' otherwise."""
        tag_name = str.lower(node.tagName) if hasattr(node, "tagName") else ""
        if tag_name == "input" and input_type in ("checkbox", "radio"):
            return "change"
        if tag_name == "select":
            return "change"
        return "input"

    def attach(self, to_node):
        """Wire the two-way input listener to ``to_node``.

        Builds the update handler for this input's type, wraps it once via
        ``_create_function_proxy``, and attaches it for the bound event.
        Re-pointable: called by ``activate()`` at mount and again during SSR
        hydration after the binding's node is re-pointed to the live SSR node.
        Idempotent — a previously attached proxy for this event is removed
        first, so re-attaching to the same node never leaks duplicates.
        """
        event = self._bound_event
        old_proxy = getattr(self, "_proxy", None)
        if old_proxy is not None:
            remover = getattr(to_node, "removeEventListener", None)
            if remover is not None:
                try:
                    remover(event, old_proxy)
                except Exception:
                    pass
        handler = self.component_instance._create_update_handler(self.field, self._input_type)
        proxy = self.component_instance._create_function_proxy(handler)
        if hasattr(to_node, "hasAttribute") and to_node.hasAttribute(f"on{event}"):
            to_node.removeAttribute(f"on{event}")
        if hasattr(to_node, "addEventListener"):
            to_node.addEventListener(event, proxy)
        else:
            setattr(to_node, f"on{event}", proxy)
        self._proxy = proxy

    def detach(self):
        """Remove the previously attached input listener from the current node."""
        proxy = getattr(self, "_proxy", None)
        if proxy is None:
            return
        remover = getattr(self.node, "removeEventListener", None)
        if remover is not None:
            try:
                remover(self._bound_event, proxy)
            except Exception:
                pass
        self._proxy = None

    def update(self):
        val = getattr(self.component_instance, self.field)
        if self._input_type == "checkbox":
            self.node.checked = bool(val)
        else:
            self.node.value = str(val) if val is not None else ""

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        field = blueprint.kwargs["field"]
        input_type = node.getAttribute("type") if hasattr(node, "hasAttribute") and node.hasAttribute("type") else "text"

        instance = cls(
            component_instance=component_instance,
            node=node,
            ast_trees=blueprint.ast_trees,
            field=field,
        )
        instance._input_type = input_type
        instance._bound_event = cls._bound_event_for(node, input_type)
        # Pure construction — DOM setup happens in activate() (called by
        # add_binding / loop-body instantiation).
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
        # No listeners here — activate() attaches them.

    @property
    def node(self):
        return self._node

    @node.setter
    def node(self, val):
        # Re-pointing the node: detach from the current one (listeners only
        # exist after activate()).  Attaching to the new one happens via
        # activate() / hydration re-attach.
        if hasattr(self, "_node") and self._node:
            self._remove_listeners(self._node)
        self._node = val

    @property
    def fields(self):
        return [self.target_expression]

    def attach(self, to_node):
        """Wire the input/blur/submit listeners to ``to_node`` — at mount (via
        ``activate()``) and again on SSR hydration re-attach."""
        if not to_node:
            return
        self._input_proxy = self.component_instance._create_function_proxy(self.handle_input)
        self._blur_proxy = self.component_instance._create_function_proxy(self.handle_blur)
        self._submit_proxy = self.component_instance._create_function_proxy(self.handle_submit)
        if hasattr(to_node, "addEventListener"):
            to_node.addEventListener("input", self._input_proxy)
            to_node.addEventListener("change", self._input_proxy)
            to_node.addEventListener("blur", self._blur_proxy)
            to_node.addEventListener("submit", self._submit_proxy)
        else:
            setattr(to_node, "oninput", self._input_proxy)
            setattr(to_node, "onchange", self._input_proxy)
            setattr(to_node, "onblur", self._blur_proxy)
            setattr(to_node, "onsubmit", self._submit_proxy)

    def detach(self):
        """Remove the listeners from the current node (teardown)."""
        self._remove_listeners(self._node)

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
                scope=self.scope,
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
        # Not reactive: an EventBinding is a pure DOM listener, not a DAG
        # effect (it has no update()).  Its target is a handler METHOD name,
        # which is never a state field — returning it here leaked handler
        # names into __fields__ (dead StateNodes) and into the HMR state
        # snapshot (stale bound-method restores).  The property must still
        # exist: loop code reads binding.fields on every body binding.
        return []

    def attach(self, to_node):
        """Wire the handler to ``to_node``.

        Re-pointable: called by ``activate()`` at mount and again during SSR
        hydration after the binding's node is re-pointed to the live SSR node.
        Idempotent — a previously attached proxy for this event is removed
        first, so re-attaching to the same node never leaks duplicates.
        """
        event_name = self.event.removeprefix("on")
        old_proxy = getattr(self, "_proxy", None)
        if old_proxy is not None:
            remover = getattr(to_node, "removeEventListener", None)
            if remover is not None:
                try:
                    remover(event_name, old_proxy)
                except Exception:
                    pass

        if isinstance(self.target_fn, str):
            func_obj = getattr(self.component_instance, self.target_fn)
            handler = self.component_instance._create_function_proxy(func_obj)
        else:
            handler = self.target_fn

        if hasattr(to_node, "hasAttribute") and to_node.hasAttribute(self.event):
            to_node.removeAttribute(self.event)
        if hasattr(to_node, "addEventListener"):
            to_node.addEventListener(event_name, handler)
        else:
            setattr(to_node, self.event, handler)
        self._proxy = handler

    def detach(self):
        """Remove the previously attached handler from the current node."""
        proxy = getattr(self, "_proxy", None)
        if proxy is None:
            return
        remover = getattr(self.node, "removeEventListener", None)
        if remover is not None:
            try:
                remover(self.event.removeprefix("on"), proxy)
            except Exception:
                pass
        self._proxy = None

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        # Pure construction — DOM setup happens in activate() (called by
        # add_binding / loop-body instantiation).
        return cls(
            component_instance=component_instance,
            node=node,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs,
        )

@dataclass(kw_only=True)
class IfBinding(NodeBinding):
    expr: str
    anchor: object = None
    is_visible: bool = True
    fields: list = field(default_factory=list)

    def update(self):
        expr_eval = bool(safe_eval(self.expr, self.component_instance, ALLOWED_BUILTINS, tree=self.ast_trees.get(self.expr),
                                   component=self.component_instance,
                                   binding_type="IfBinding",
                                   template=self.expr,
                                   scope=self.scope))
        if expr_eval == self.is_visible:
            return  # visibility unchanged — skip DOM mutation
        if expr_eval == False:
            self.node.remove()
        else:
            self.anchor.after(self.node)
        self.is_visible = expr_eval

    def marked_for_hydration(self):
        return [self.node, self.anchor]

    def activate(self):
        """Create the ``display: contents`` anchor that holds the if-node's
        position."""
        anchor = self.component_instance._create_element("div")
        anchor.setAttribute("style", "display: contents;")
        anchor.setAttribute("data-if-expression", "{" + self.expr + "}")
        self.node.parentNode.insertBefore(anchor, self.node)
        self.anchor = anchor

    def destroy(self):
        """Remove the anchor (teardown)."""
        if self.anchor is not None:
            try:
                self.anchor.remove()
            except Exception:
                pass
        self.anchor = None

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        # Pure construction — activate() creates the anchor.
        return cls(
            component_instance=component_instance,
            node=node,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs
        )


@dataclass(kw_only=True)
class ChildBinding(NodeBinding):
    childclass:str
    childinstance:object=None
    attr_bindings: "list[SelfAttributeBinding]" = field(default_factory=list)
    loop_binding: "LoopBinding | None" = None
    ast_trees: dict = field(default_factory=dict, init=True, repr=False)
    _static_attrs: dict = field(default_factory=dict, init=False, repr=False)

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

        # Pure construction — mounting happens in activate().
        # A node that is already mounted (re-initialization on a live node) is
        # not re-bound.
        if getattr(node, '__basis_mounted__', False):
            return None

        instance = cls(
            component_instance=component_instance,
            node=node,
            childclass=childcomponent_py,
            childinstance=None,
            ast_trees=blueprint.ast_trees,
        )
        instance._static_attrs = dom_child_node_attrs
        return instance

    def activate(self):
        """Mount the child component into this binding's node (once, at mount).

        Skips when the caller already mounted the child (loop custom-element
        children and ``mount()`` nested children pass ``childinstance``).
        """
        if self.childinstance is not None:
            return  # already mounted by the caller
        if getattr(self.node, '__basis_mounted__', False):
            return
        child_instance = self.childclass.mount(self.node, replace=False, **self._static_attrs)
        self.node.__basis_mounted__ = True
        # CRITICAL: links the DOM wrapper node to the Python component instance.
        # It enables AttributeBinding.update() on the parent to correctly sync
        # reactive property changes down to the child component instance.
        setattr(self.node, '__basis_instance__', child_instance)
        self.childinstance = child_instance

    def destroy(self):
        """Teardown: clear the mounted child reference (its node/listeners/DAG
        are reclaimed with the subtree)."""
        self.childinstance = None

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
    body_blueprints: list = field(default_factory=list, repr=False)
    enclosing_scope: object = field(default=None, repr=False)

    @property
    def fields(self):
        # Return the REAL owner deps of the `in=` collection expression (e.g.
        # `{data['list']}` → ["data"], `{$store.list}` → ["$store.list"],
        # `{visible}` → ["visible"]) so the owner DAG re-runs the loop when its
        # collection's dependencies change — not the raw expression string,
        # which never matches a DAG node name.
        fieldnames, _ = extract_dependencies(
            "{" + self.collection + "}", ALLOWED_BUILTINS)
        return fieldnames

    def _collection_value(self):
        """Evaluate the `in=` collection expression (a real expression, not a
        single getattr) against the owner + enclosing loop scopes, so
        `in="{groups}"`, `in="{data['list']}"`,
        `in="{grp['items']}"` (nested) and `in="{$store.list}"` all work.
        Evaluation failures yield an empty collection (never an error string
        rendered into the loop)."""
        val = safe_eval(
            self.collection,
            self.component_instance,
            ALLOWED_BUILTINS,
            tree=self.ast_trees.get(self.collection),
            component=self.component_instance,
            binding_type="LoopBinding",
            template=self.collection,
            scope=self.enclosing_scope,
        )
        if val is EVAL_ERROR or val is SILENT_ERROR:
            return []
        if isinstance(val, str) and val.startswith(ERROR_PREFIX):
            return []
        if val is None:
            return []
        return val

    def _builder(self):
        return LoopBodyBuilder(
            component_instance=self.component_instance,
            body_blueprints=self.body_blueprints,
            item=self.item,
            enclosing_scope=self.enclosing_scope,
            clone=self.clone,
        )

    def update(self):
        """Reconcile the loop: resolve the collection, derive keys, ask the
        Reconciler for the op plan, then apply the ops to the DOM."""
        collection_value = self._collection_value()
        if not isinstance(collection_value, (list, tuple)):
            collection_value = list(collection_value)
        new_keys = derive_keys(collection_value, self.key)
        ops = Reconciler.diff(list(self.instances.keys()), new_keys)
        builder = self._builder()

        new_map = {}
        new_list = []
        prev = None
        for op in ops:
            if op.kind == "remove":
                self._remove_item(self.instances[op.key])
                del self.instances[op.key]
            elif op.kind == "create":
                entry = self._create_item(builder, collection_value[op.index], op.key, prev)
                new_map[op.key] = entry
                new_list.append(entry)
                prev = entry
            elif op.kind == "update":
                entry = self._update_item(builder, op.key, collection_value[op.index])
                new_map[op.key] = entry
                new_list.append(entry)
                prev = entry

        move_keys = {op.key for op in ops if op.kind == "move"}
        if move_keys:
            next_node = new_list[-1].node.nextSibling
            for i in range(len(new_list) - 1, -1, -1):
                entry = new_list[i]
                node = entry.node
                if entry.key in move_keys and node.nextSibling != next_node:
                    self.parent.insertBefore(node, next_node)
                next_node = node

        self.instances = new_map

    def _remove_item(self, entry):
        """Dispose an item (scoped owner-DAG effects + body listeners), drop its
        ChildBinding, and remove the wrapper node."""
        entry.dispose()
        if entry.child_binding is not None:
            self.component_instance.remove_binding(entry.child_binding)
        node = entry.node
        if node is not None and getattr(node, "parentNode", None):
            node.remove()

    def _create_item(self, builder, item_value, key, prev):
        """Build a new LoopItem, insert it after ``prev`` (or at the template's
        former slot for the first item), and register its component/effects."""
        cloned = builder.new_clone()
        tag = str.lower(cloned.tagName)
        if "-" in tag:
            # Custom-element loop child: the registered class owns its template
            # and lifecycle; per-item data flows via props only.
            child_cls = self.component_instance.__class__._registry[tag]
            child = child_cls.mount(cloned, replace=False, **builder.child_props(item_value))
            setattr(cloned, "__basis_instance__", child)
            entry = LoopItem(
                node=cloned, bindings=[], key=key,
                scope=LoopScope({self.item: item_value}, parent=self.enclosing_scope),
                instance=child,
            )
            # Keep a ChildBinding so hydration and get_bindings(recursive=True)
            # still see the child as a component.
            cb = ChildBinding(component_instance=self.component_instance,
                              node=cloned, childclass=child_cls,
                              childinstance=child, loop_binding=self)
            self.component_instance.add_binding(cb)
            entry.child_binding = cb
        else:
            # Plain loop body -> thin LoopItem with owner-bound bindings.
            entry = builder.build(item_value, key)
        entry.node.setAttribute("data-item-key", str(key))
        self._insert(entry, prev)
        if entry.instance is None:
            entry.render()
        return entry

    def _update_item(self, builder, key, item_value):
        """Reuse an existing LoopItem for a stable key: refresh the item overlay,
        re-render the plain body or push props to the custom-element child."""
        entry = self.instances[key]
        entry.scope.vars[self.item] = item_value
        if entry.instance is not None:
            props = builder.child_props(item_value)
            with entry.instance.refrain() as refrained:
                for k, v in props.items():
                    setattr(refrained, k, v)
        else:
            # Item reuse: the deriveds' deps haven't changed, but their input
            # key has — drop their memos (no cascade) before re-rendering so
            # {derived} re-evaluates against the new item value.
            entry.invalidate_derived()
            entry.render()
        entry.node.setAttribute("data-item-key", str(key))
        return entry

    def _insert(self, entry, prev):
        """Insert ``entry`` after the previous new item, or at the template's
        former slot for the first item."""
        anchor = prev.node.nextSibling if prev is not None else getattr(self, "_after_node", None)
        if anchor is not None:
            try:
                if getattr(anchor, "parentNode", None) != self.parent:
                    anchor = None
            except Exception:
                anchor = None
        self.parent.insertBefore(entry.node, anchor)

    def _plain_body_bindings(self):
        """Every owner-bound body binding across all plain LoopItems, recursing
        into nested loops (custom-element children are excluded — they keep
        their own component subtrees)."""
        for it in self.instances.values():
            if it.instance is not None:
                continue
            for b in it.bindings:
                yield b
                if isinstance(b, LoopBinding):
                    yield from b._plain_body_bindings()

    def marked_for_hydration(self):
        """Stamping targets: the loop template node, its parent, every item's
        wrapper node, and each body binding's nodes (recursively), so the server
        stamps data-hydration-id across the whole loop body."""
        nodes = [self.node, self.parent]
        nodes.extend(it.node for it in self.instances.values())
        for b in self._plain_body_bindings():
            nodes.extend(b.marked_for_hydration())
        return [n for n in nodes if n is not None]

    def text_binding_nodes(self):
        """Body TextBinding nodes (for data-basis-text ordinal stamping)."""
        return [b.node for b in self._plain_body_bindings()
                if type(b).__name__ == "TextBinding"]

    def all_body_bindings(self):
        """Every owner-bound body binding across all plain LoopItems
        (flattened, recursing into nested loops)."""
        return list(self._plain_body_bindings())

    def component_children(self):
        """The mounted custom-element children (component roots) at every loop
        level, so they keep participating in hydration as components."""
        out = [it.instance for it in self.instances.values() if it.instance is not None]
        for b in self._plain_body_bindings():
            if isinstance(b, LoopBinding):
                out.extend(b.component_children())
        return out

    def repoint_to_ssr(self, ssr_parent, report=None):
        """Structural (canonical-path) re-pointing of a loop to the live SSR
        tree.  Implementation lives in ``shared/hydration.repoint_loop_to_ssr``
        (the module that owns canonical-path tree matching)."""
        return repoint_loop_to_ssr(self, ssr_parent, report)

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint,
                       enclosing_scope=None):
        cloned_node = node.cloneNode(True)

        # Capture parent and the sibling that comes after the template node
        # BEFORE the template node is removed in activate() (parentNode becomes
        # None after remove()).
        parent_node = node.parentNode
        after_node = node.nextSibling

        kwargs = dict(blueprint.kwargs)
        body_blueprints = kwargs.pop('body_blueprints', None) or []
        if enclosing_scope is None:
            enclosing_scope = kwargs.pop('enclosing_scope', None)
        else:
            # An explicit enclosing scope wins (nested loops); never leak into cls().
            kwargs.pop('enclosing_scope', None)

        instance = cls(
            component_instance=component_instance, 
            node=node,
            clone=cloned_node,
            parent=parent_node,
            ast_trees=blueprint.ast_trees,
            body_blueprints=body_blueprints,
            enclosing_scope=enclosing_scope,
            **kwargs,
        )
        
        instance._after_node = after_node
        
        return instance

    def activate(self):
        """Remove the loop template node from the DOM — the loop's items are
        inserted at its former slot (parent/_after_node were captured in
        from_blueprint before the remove)."""
        self.node.remove()

    def destroy(self):
        """Tear down the whole loop: remove each item's child binding, dispose
        each item (body listeners + scoped owner-DAG effects), and clear the
        map. (Per-item removal during update() is handled inline there.)"""
        for entry in list(self.instances.values()):
            if entry.child_binding is not None:
                self.component_instance.remove_binding(entry.child_binding)
            entry.dispose()
        self.instances.clear()

@dataclass
class SlotBinding(NodeBinding):
    name: str | None = None
    is_default: bool = True
    
    @property
    def fields(self):
        return []









__all__ = ['Binding', 'SelfBinding', 'TextBinding', 'AttributeBinding', \
            'ModelBinding', 'EventBinding', 'IfBinding', 'ChildBinding', \
            'LoopBinding', 'SlotBinding', \
            'safe_eval', 'safe_format', \
            'extract_dependencies', 'Refrain']
