import ast
from dataclasses import dataclass, field
import inspect
import json
import operator
import re
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
            ast_trees=self.ast_trees
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
    
    def update(self):
        # Always evaluate in the context of the component that owns the binding (the parent)
        context = self.component_instance
        store_registry = self.component_instance.__class__.S
        instance_registry = self.component_instance.__class__._instance_registry

        # Detect if it's a single expression like "{val}" or an interpolation like "count: {val}"
        formatter = Formatter()
        try:
            parsed = list(formatter.parse(self.content))
        except ValueError:
            # Handle cases where content is not a valid format string
            parsed = []

        is_single_expr = len(parsed) == 1 and parsed[0][1] is not None and not parsed[0][0]
        
        if is_single_expr:
            fname = parsed[0][1]
            ast_tree = self.ast_trees.get(fname)
            evaluated_val = safe_eval(fname, context, ALLOWED_BUILTINS, tree=ast_tree)
            
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
                ast_trees=self.ast_trees
            )
            final_dom_val = evaluated_val

        # Update the DOM node
        if self.is_boolean:
            bool_val = bool(evaluated_val) if is_single_expr else str(final_dom_val).lower() == 'true'
            self.node.toggleAttribute(self.attr, bool_val)
        else:
            self.node.setAttribute(self.attr, str(final_dom_val))

        # Prop Synchronization: If the node is a Basis component instance, update its Python property.
        if hasattr(self.node, '__basis_instance__'):
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
                                                ast_trees=self.ast_trees)

            if self.is_boolean:
                bool_val = str(final_val).lower() == 'true'
                # following line was causing circular updates in react()
                # setattr(self.component_instance, self.attr, bool_val)
                # replaced with below
                self.component_instance.__dict__[self.attr] = final_val
            else:
                # following line was causing circular updates in react()
                # setattr(self.component_instance, self.attr, final_val)
                # replaced with below
                self.component_instance.__dict__[self.attr] = final_val

        else:
            formatter = Formatter()
            _, fname, _, _ = next(iter(formatter.parse(self.content)))
            evaluated_val = safe_eval(fname, context, ALLOWED_BUILTINS, tree=self.ast_trees.get(fname))
            final_val = json.dumps(evaluated_val)
            self.component_instance.__dict__[self.attr] = final_val

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
            ast_trees=self.ast_trees
        )
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
        expr_eval = bool(safe_eval(self.expr, self.component_instance, ALLOWED_BUILTINS, tree=self.ast_trees.get(self.expr)))
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
        dom_child_node_attrs = {a: node.getAttribute(a) for a in node.getAttributeNames()}
        
        if not getattr(node, '__basis_mounted__', False):
            child_instance = childcomponent_py.mount(node, replace=False, **dom_child_node_attrs)
            node.__basis_mounted__ = True
            
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
    item:str
    collection:str
    clone:object
    parent:object
    ast_trees: dict = field(default_factory=dict, repr=False)

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

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        cloned_node = node.cloneNode(True)
        
        instance = cls(
            component_instance=component_instance, 
            node=node,
            clone=cloned_node,
            parent=node.parentNode,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs,
        )
        
        return instance

@dataclass(kw_only=True)
class KeyedLoopBinding(NodeBinding):
    item:str
    collection:str
    clone:object
    parent:object
    key:str
    instances:dict = field(default_factory=dict)
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

    @classmethod
    def from_blueprint(cls, component_instance, node, blueprint):
        cloned_node = node.cloneNode(True)
        
        instance = cls(
            component_instance=component_instance, 
            node=node,
            clone=cloned_node,
            parent=node.parentNode,
            ast_trees=blueprint.ast_trees,
            **blueprint.kwargs,
        )
        
        return instance

@dataclass(kw_only=True)
class SmartKeyedLoopBinding(KeyedLoopBinding):
    """
    Experimental high-performance keyed loop reconciliation using the 
    Longest Increasing Subsequence (LIS) algorithm.
    """
    def update(self):
        # 1. Prepare data
        new_keys = self.get_collection_keys()
        new_items = self.get_collection_items()
        
        # 2. Removal Phase
        # Find instances that are no longer in the new keys
        new_keys_set = set(new_keys)
        removed_keys = [k for k in self.instances.keys() if k not in new_keys_set]
        for r_key in removed_keys:
            old_instance = self.instances[r_key]
            # Remove from DOM
            if old_instance.__element__ and old_instance.__element__.parentNode:
                old_instance.__element__.remove()
            
            # Remove associated bindings from the parent component
            bindings_to_rem = [cb for cb in self.component_instance.__bindings__ 
                              if isinstance(cb, ChildBinding) and cb.childinstance == old_instance]
            for rem in bindings_to_rem:
                self.component_instance.remove_binding(rem)
            
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
            else:
                # New creation
                cloned_element = self._new_clone()
                updated_child_node_attrs = self._child_node_attrs_dict(item)
                childcomponent_py = self._child_component_class()
                
                # Mount to parent (will be moved to correct position later)
                child_instance = childcomponent_py.mount(self.parent, replace=False, **updated_child_node_attrs)
                child_instance.__element__.setAttribute('data-item-key', str(k_val))
                
                new_cb = ChildBinding(component_instance=self.component_instance,
                                      node=child_instance.__element__,
                                      childclass=childcomponent_py,
                                      childinstance=child_instance,
                                      loop_binding=self)
                self.component_instance.add_binding(new_cb)
                
                new_instances_map[k_val] = child_instance
                sources[i] = -1

            new_instances_list.append(new_instances_map[k_val])

        # 4. Movement Phase (LIS)
        # Find LIS of the original positions to minimize moves
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

        # 5. Reorder in DOM (Iterate backwards for stable insertBefore)
        next_node = None
        for i in range(len(new_keys) - 1, -1, -1):
            instance = new_instances_list[i]
            node = instance.__element__
            
            # If it's a new item or not in the LIS, it must be moved/inserted
            if sources[i] == -1 or i not in lis_indices_in_new_list:
                self.parent.insertBefore(node, next_node)
            
            next_node = node
            
        self.instances = new_instances_map

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
            # Check context (can be a dict or a component instance)
            if isinstance(context, dict):
                if node.id in context:
                    return context[node.id]
            else:
                if hasattr(context, node.id):
                    return getattr(context, node.id)
            
            if node.id in allowed_builtins:
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
            
    return _eval(node)

def safe_eval(expr_str, context, allowed_builtins, tree=None):
    if tree is None:
        try:
            tree = ast.parse(expr_str, mode='eval')
        except Exception as e:
            print(f"Failed to parse {expr_str}: {e}")
            return f"[Error: {expr_str}]"
    
    try:
        return _eval_ast(tree.body if isinstance(tree, ast.Expression) else tree, context, allowed_builtins)
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

def safe_format_with_stores(template_str, context, allowed_builtins, store_registry, component_instance_registry, ast_trees=None):
    
    result = ""
    formatter = Formatter()
    for literal_text, fname, format_spec, conversion in formatter.parse(template_str):
        result += literal_text
        if fname is not None:
            ast_tree = ast_trees.get(fname) if ast_trees else None
            
            # If we have an AST tree, it should be the desugared one.
            # safe_eval will handle evaluating BaseComponent.S[...] or BaseComponent.C[...]
            # if we provide the tree.
            if ast_tree:
                val = safe_eval(fname, context, allowed_builtins, tree=ast_tree)
            elif fname.startswith("$"):
                store_name, attr_name = fname.strip("$").split(".")
                val = getattr(store_registry[store_name], attr_name)
            elif fname.startswith("#"):
                component_name, attr_name = fname.strip("#").split(".")
                if component_name in component_instance_registry:
                    val = getattr(component_instance_registry[component_name], attr_name)
                else:
                    val = ""
            else:
                val = safe_eval(fname, context, allowed_builtins)
            
            if format_spec:
                result += format(val, format_spec)
            else:
                result += str(val)
    
    return result

def extract_dependencies(template_str, allowed_builtins=ALLOWED_BUILTINS):
    """
    Extracts dependencies from a template string and returns a tuple:
    (list of dependencies, dictionary of desugared AST trees mapping fname -> tree).
    """
    formatter = Formatter()
    deps = set()
    trees = {}

    try:
        parsed_template = list(formatter.parse(template_str))
    except ValueError:
        # Handle cases where template_str is not a valid format string (e.g. CSS)
        return [], {}
    
    fnames = [fname for _, fname, _, _ in parsed_template]
    
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
                            #deps.add(f"{prefix}{s_name}")

        except SyntaxError:
            print(f"Error parsing expression: {desugared}")
        except Exception as e:
            print(f"Error extracting dependencies for {desugared}: {e}")

    return list(deps), trees


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

        fieldnames, ast_trees_dict = extract_dependencies(other_attr_value, ALLOWED_BUILTINS)
        if len(fieldnames):
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

    formatter = Formatter()

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


class Refrain(object):
    def __init__(self, component):
        self.__dict__['inner_dict'] = {}
        self.__dict__['component'] = component
        self.__dict__['forced_reactivity'] = set()

    def __enter__(self):
        return self
    
    def __setattr__(self, name, value):
        self.inner_dict[name] = value

    def force_react(self, name):
        self.forced_reactivity.add(name)

    def __exit__(self, exc_type, exc_val, exc_tb):
        inner_dict = self.__dict__['inner_dict']
        inner_dict_keys = list(inner_dict.keys())
        for k, v in inner_dict.items():
            self.component.__dict__[k] = v
        
        # Collect all fields that need to react
        fields_to_react = inner_dict_keys + [k for k in self.forced_reactivity if k not in inner_dict_keys]

        if fields_to_react:
            self.component._dag.trigger_batch(fields_to_react)



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
            'LoopBinding', 'KeyedLoopBinding', 'SmartKeyedLoopBinding', 'SlotBinding', \
            'safe_eval', 'safe_format', 'safe_format_with_stores', \
            'extract_dependencies', 'Refrain', \
            '_process_standard_attr_bindings', '_process_event_attr_bindings', \
            '_process_text_bindings']
