import ast
import inspect
import weakref
from typing import Callable, Set, Dict, List, Any

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
    """Represents a side-effect (e.g., DOM binding)."""
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

class DependencyGraph:
    def __init__(self):
        self.nodes: Dict[str, ReactiveNode] = {}
        self.effects: List[EffectNode] = []

    def get_or_create_state(self, name: str) -> StateNode:
        if name not in self.nodes:
            self.nodes[name] = StateNode(name)
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
        return new_node

    def add_effect(self, name: str, update_func: Callable, dependencies: List[str]):
        node = EffectNode(name, update_func)
        self.nodes[name] = node
        self.effects.append(node)
        for dep_name in dependencies:
            dep_node = self.nodes.get(dep_name) or self.get_or_create_state(dep_name)
            node.add_dependency(dep_node)
        return node

    def remove_effect(self, name: str):
        node = self.nodes.pop(name, None)
        if node and node in self.effects:
            self.effects.remove(node)

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
            # Integration with the component's DAG
            if not hasattr(self, '_dag_nodes'):
                return func(self)
            
            node = self._dag_nodes.get(func.__name__)
            if not node:
                # Fallback if node hasn't been initialized yet
                return func(self)
            return node.update()
        
        # Copy metadata to the fget of the property for BaseComponent to find
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
