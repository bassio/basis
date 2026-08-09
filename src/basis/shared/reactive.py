import ast
import inspect
import weakref
from typing import Callable, Set, Dict, List, Any


# ──────────────────────────────────────────────
# DAG Node Types
# ──────────────────────────────────────────────

class ReactiveNode:
    def __init__(self, name: str):
        self.name = name
        self.dependencies: Set['ReactiveNode'] = set()
        self.dependents: Set['ReactiveNode'] = set()
        self.stale = True

    def add_dependency(self, node: 'ReactiveNode'):
        if node not in self.dependencies:
            self.dependencies.add(node)
            node.dependents.add(self)

    def mark_stale(self):
        if not self.stale:
            self.stale = True
            for dependent in self.dependents:
                dependent.mark_stale()

    def update(self):
        raise NotImplementedError

class StateNode(ReactiveNode):
    """Represents a source of truth (raw attribute)."""
    def __init__(self, name: str):
        super().__init__(name)
        self.stale = False

    def update(self):
        self.stale = False

class ComputedNode(ReactiveNode):
    """Represents a derived value that depends on other nodes."""
    def __init__(self, name: str, func: Callable, owner: Any):
        super().__init__(name)
        self.func = func
        self.owner = weakref.ref(owner)
        self.value = None

    def update(self):
        if not self.stale:
            return self.value
        
        # Ensure dependencies are updated first
        for dep in self.dependencies:
            dep.update()
            
        owner = self.owner()
        if owner:
            self.value = self.func(owner)
        
        self.stale = False
        return self.value

class EffectNode(ReactiveNode):
    """Represents a side-effect (e.g., DOM binding or subscription notification)."""
    def __init__(self, name: str, update_func: Callable):
        super().__init__(name)
        self.update_func = update_func

    def update(self):
        if self.stale:
            # First, ensure all dependencies are updated (especially computed ones)
            for dep in self.dependencies:
                dep.update()

            self.update_func()
            self.stale = False


# ──────────────────────────────────────────────
# Dependency Graph
# ──────────────────────────────────────────────

class DependencyGraph:
    def __init__(self):
        self.nodes: Dict[str, ReactiveNode] = {}
        self.effects: List[EffectNode] = []
        self._wildcard_effects: List[EffectNode] = []

    def get_or_create_state(self, name: str) -> StateNode:
        if name not in self.nodes:
            node = StateNode(name)
            self.nodes[name] = node
            # Wire any existing wildcard effects to this new state node
            for wc_effect in self._wildcard_effects:
                wc_effect.add_dependency(node)
        return self.nodes[name]

    def add_computed(self, name: str, func: Callable, owner: Any, dependencies: List[str]):
        new_node = ComputedNode(name, func, owner)
        
        if name in self.nodes:
            old_node = self.nodes[name]
            # Transfer dependents to the new node
            new_node.dependents = old_node.dependents
            for dependent in new_node.dependents:
                # Update the dependent's dependency set
                if old_node in dependent.dependencies:
                    dependent.dependencies.remove(old_node)
                    dependent.dependencies.add(new_node)
        
        self.nodes[name] = new_node
        for dep_name in dependencies:
            dep_node = self.nodes.get(dep_name) or self.get_or_create_state(dep_name)
            new_node.add_dependency(dep_node)
        # Wire any existing wildcard effects to this new computed node
        for wc_effect in self._wildcard_effects:
            wc_effect.add_dependency(new_node)
        return new_node

    def add_effect(self, name: str, update_func: Callable, dependencies: List[str]):
        node = EffectNode(name, update_func)
        node.stale = False  # start clean; becomes stale only when a dependency triggers
        self.nodes[name] = node
        self.effects.append(node)
        for dep_name in dependencies:
            dep_node = self.nodes.get(dep_name) or self.get_or_create_state(dep_name)
            node.add_dependency(dep_node)
        return node

    def add_wildcard_effect(self, name: str, update_func: Callable):
        """Register an effect that depends on ALL current and future state/computed nodes."""
        node = EffectNode(name, update_func)
        node.stale = False  # start clean; becomes stale only when a dependency triggers
        self.nodes[name] = node
        self.effects.append(node)
        self._wildcard_effects.append(node)
        # Wire to all existing state and computed nodes
        for existing_node in self.nodes.values():
            if isinstance(existing_node, (StateNode, ComputedNode)):
                node.add_dependency(existing_node)
        return node

    def remove_effect(self, name: str):
        node = self.nodes.pop(name, None)
        if node and node in self.effects:
            self.effects.remove(node)
        if node and node in self._wildcard_effects:
            self._wildcard_effects.remove(node)

    def trigger(self, name: str):
        if name in self.nodes:
            node = self.nodes[name]
            node.mark_stale()
            if isinstance(node, StateNode):
                node.stale = False
            self.process_updates()

    def trigger_batch(self, names: List[str]):
        for name in names:
            if name in self.nodes:
                node = self.nodes[name]
                node.mark_stale()
                if isinstance(node, StateNode):
                    node.stale = False
        self.process_updates()

    def process_updates(self):
        """Update all stale effect nodes."""
        for node in self.effects:
            if node.stale:
                node.update()


# ──────────────────────────────────────────────
# AST-based Dependency Extraction
# ──────────────────────────────────────────────

class DependencyVisitor(ast.NodeVisitor):
    def __init__(self, self_name='self'):
        self.self_name = self_name
        self.dependencies = set()

    def _get_full_attr_path(self, node):
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._get_full_attr_path(node.value)
            if base:
                return f"{base}.{node.attr}"
        return None

    def visit_Attribute(self, node):
        path = self._get_full_attr_path(node)
        if path and path.startswith(self.self_name + "."):
            # strip 'self.'
            dep = path[len(self.self_name)+1:]
            self.dependencies.add(dep)
        self.generic_visit(node)

def extract_func_dependencies(func) -> List[str]:
    try:
        source = inspect.getsource(func)
        # Handle indentation and potential decorator noise
        source = inspect.cleandoc(source)
        tree = ast.parse(source)
        
        # We look for the first function definition
        func_def = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_def = node
                break
        
        if not func_def:
            return []

        # Determine the name of 'self'
        self_name = 'self'
        if func_def.args.args:
            self_name = func_def.args.args[0].arg
        
        visitor = DependencyVisitor(self_name=self_name)
        visitor.visit(func_def)
        return list(visitor.dependencies)
    except Exception as e:
        print(f"Basis Reactivity Warning: Could not automatically detect dependencies for '{func.__name__}': {e}")
        return []


# ──────────────────────────────────────────────
# @computed Decorator
# ──────────────────────────────────────────────

def computed(args=None, dependencies=None):
    """
    Decorator to mark a method as a computed property.
    Can be used as @computed or @computed(dependencies=['a', 'b'])
    """
    def decorator(func):
        # Store metadata on the function itself
        func._is_computed = True
        # Use provided dependencies or try to auto-detect
        actual_deps = dependencies if dependencies is not None else extract_func_dependencies(func)
        func._dependencies = actual_deps
        
        @property
        def wrapper(self):
            # Integration with the owner's DAG
            if not hasattr(self, '_dag_nodes'):
                return func(self)
            
            node = self._dag_nodes.get(func.__name__)
            if not node:
                # Fallback if node hasn't been initialized yet
                return func(self)
            return node.update()
        
        # Copy metadata to the fget of the property for ReactiveObject to find
        wrapper.fget._dependencies = func._dependencies
        wrapper.fget._is_computed = True
        wrapper.fget._original_func = func
            
        return wrapper

    # Handle both @computed and @computed(...)
    if callable(args):
        return decorator(args)
    
    # If args was provided but it's not the function, it might be the dependencies list
    # though we prefer using the named 'dependencies' keyword.
    if args is not None and dependencies is None:
        dependencies = args
        
    return decorator


# ──────────────────────────────────────────────
# Refrain — Batched Update Context Manager
# ──────────────────────────────────────────────

class Refrain(object):
    def __init__(self, owner):
        self.__dict__['inner_dict'] = {}
        self.__dict__['owner'] = owner
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
            self.owner.__dict__[k] = v
        
        # Collect all fields that need to react
        fields_to_react = inner_dict_keys + [k for k in self.forced_reactivity if k not in inner_dict_keys]

        if fields_to_react:
            self.owner._dag.trigger_batch(fields_to_react)


# ──────────────────────────────────────────────
# ReactiveObject — Common Base Class
# ──────────────────────────────────────────────

class ReactiveObject:
    """
    Base class providing unified DAG-based reactivity.
    Both BaseComponent and Store inherit from this.
    """

    def __init__(self):
        super().__init__()
        self.__dict__['_dag'] = DependencyGraph()
        self.__dict__['_dag_nodes'] = self._dag.nodes

    def __setattr__(self, name, value):
        # Private attributes bypass the DAG entirely
        if name.startswith('_'):
            self.__dict__[name] = value
            return

        if name not in self.__dict__:
            # Initial assignment of a new attribute -> always trigger DAG
            self.__dict__[name] = value
            self._dag.get_or_create_state(name)
            self._dag.trigger(name)
        else:
            # Updating an existing attribute -> fast change detection
            old_value = self.__dict__[name]
            self.__dict__[name] = value
            
            if value is not old_value:
                if isinstance(value, (list, dict, set, tuple)) \
                or value != old_value:
                    self._dag.trigger(name)

    def react(self, names: list[str]):
        if isinstance(names, str):
            raise Exception("Please pass only a list of strings to react().")
        self._dag.trigger_batch(names)

    def refrain(self):
        return Refrain(self)

    def _init_computed(self):
        """Scan class for @computed methods and register them as ComputedNodes in the DAG."""
        for name, member in inspect.getmembers(self.__class__):
            member_func = getattr(member, 'fget', member)
            if hasattr(member_func, '_is_computed'):
                deps = getattr(member_func, '_dependencies', [])
                original_func = getattr(member_func, '_original_func', None)
                if original_func:
                    node = self._dag.add_computed(name, original_func, self, deps)
                    # Force an initial calculation so we don't start with None
                    node.update()
