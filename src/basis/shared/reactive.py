import contextlib
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

    def clear_dependencies(self):
        """Drop all current dependencies (removing this node from each old
        dependency's ``dependents`` set) so dependencies can be re-collected."""
        for dep in self.dependencies:
            dep.dependents.discard(self)
        self.dependencies.clear()

    def mark_stale(self):
        if not self.stale:
            self.stale = True
            for dependent in self.dependents:
                dependent.mark_stale()

    def update(self):
        raise NotImplementedError


# ──────────────────────────────────────────────
# Reactive read-tracking (execution-tracked deps)
# ──────────────────────────────────────────────

# Stack of "trackers" — the computed/effect currently being evaluated. While
# non-empty, ReactiveObject.__getattribute__ records every public reactive read
# against the innermost tracker. Empty in the common path (zero overhead).
_tracker_stack: List[ReactiveNode] = []

# Effects marked stale but not yet flushed. Cross-object edges mark dependents
# on OTHER objects' graphs, so a trigger on any graph flushes them all.
_dirty_effects = set()


class _TrackingProbe(ReactiveNode):
    """Ephemeral tracker used by ``ReactiveObject._tracked_reads``. Records
    reads into its own dependency set without wiring dependents back onto the
    read nodes (P1 probe — no cross-edge side effects)."""

    def __init__(self):
        super().__init__("__tracking_probe__")

    def add_dependency(self, node: ReactiveNode):
        self.dependencies.add(node)


def _start_tracking(node: ReactiveNode):
    _tracker_stack.append(node)


def _stop_tracking(node: ReactiveNode):
    # Pop the innermost tracker; tolerate a mismatched/unbalanced stack.
    if _tracker_stack and _tracker_stack[-1] is node:
        _tracker_stack.pop()
    elif node in _tracker_stack:
        _tracker_stack.remove(node)


@contextlib.contextmanager
def _track(node: ReactiveNode):
    _start_tracking(node)
    try:
        yield
    finally:
        _stop_tracking(node)


class StateNode(ReactiveNode):
    """Represents a source of truth (raw attribute)."""
    def __init__(self, name: str):
        super().__init__(name)
        self.stale = False

    def update(self):
        self.stale = False

class ComputedNode(ReactiveNode):
    """Represents a derived value that depends on other nodes.

    Dependencies are discovered by EXECUTION TRACKING: every update() runs the
    body under a tracking context (``_track``), so each reactive read — even
    through helper methods, ``getattr``, or another object — becomes a real DAG
    edge. Declared dependencies (``@computed(dependencies=[...])``) are
    re-attached on every update. Values are computed lazily on first access and
    memoized while not stale.
    """
    def __init__(self, name: str, func: Callable, owner: Any):
        super().__init__(name)
        self.func = func
        self.owner = weakref.ref(owner)
        self.value = None
        # A fresh lazy node is NOT "stale" in the propagation sense: if it
        # started stale, the first mark_stale() would short-circuit and never
        # cascade to dependents (effects/loops/subscriptions would not fire).
        self.stale = False
        self._computed = False  # has the body been evaluated at least once?
        self._declared_deps: List[ReactiveNode] = []
        self._computing = False
        # @derived nodes (per-loop-item) may legitimately have no tracked deps
        # (item-data-only reads) — the empty-dep dev warning is @computed-only.
        self.is_derived = False
        self._warned_empty = False

    def add_declared(self, node: ReactiveNode):
        self._declared_deps.append(node)
        self.add_dependency(node)

    def update(self):
        if self._computed and not self.stale:
            return self.value

        if self._computing:
            raise RecursionError(
                f"Circular @computed dependency detected involving '{self.name}'"
            )
        self._computing = True
        try:
            # Ensure current dependencies are fresh before recomputing.
            for dep in list(self.dependencies):
                dep.update()

            owner = self.owner()
            if owner is None:
                self.value = None
                self.stale = False
                self._computed = True
                return None

            # Re-collect dependencies by executing the body under a tracking
            # context, then re-attach the declared ones (manual
            # dependencies=[...] and AST pre-wiring may not be re-read).
            self.clear_dependencies()
            with _track(self):
                self.value = self.func(owner)
            for node in self._declared_deps:
                self.add_dependency(node)

            self.stale = False
            self._computed = True
            if (not self.is_derived and not self._warned_empty
                    and not self.dependencies):
                self._warned_empty = True
                print(
                    f"Basis Reactivity Warning: computed '{self.name}' has no "
                    f"reactive dependencies — it will never recompute. Read a "
                    f"reactive field, or pass dependencies=[...]."
                )
            return self.value
        finally:
            self._computing = False

    def invalidate(self):
        """Drop the memo without cascading to dependents.

        Used on loop-item reuse (P4c): a @derived's dependencies haven't
        changed, but its input key (the item value) has — the caller re-renders
        explicitly, so no propagation is wanted (a full ``mark_stale`` would
        re-enqueue the owner effect mid-flush and double-render).
        """
        self.stale = True

    def prime_deps(self):
        """Eagerly establish dependency edges by dry-running the body under a
        tracking probe (no value is computed or memoized; errors are swallowed).

        Called at registration so a @computed that is subscribed to but never
        read in a template (e.g. a Store computed a component watches via
        ``$store.x``) still propagates when its deps change.  The real update()
        re-collects deps lazily on first access, so this is only an edge-priming
        pass — it must NOT abort the mount (the P2 lazy-boot fix).
        """
        if self._computed:
            return
        owner = self.owner()
        if owner is None:
            return
        try:
            probe = _TrackingProbe()
            with _track(probe):
                self.func(owner)
            for dep in probe.dependencies:
                self.add_dependency(dep)
        except Exception:
            pass

class EffectNode(ReactiveNode):
    """Represents a side-effect (e.g., DOM binding or subscription notification)."""
    def __init__(self, name: str, update_func: Callable):
        super().__init__(name)
        self.update_func = update_func

    def update(self):
        if self.stale:
            # Computed dependencies update lazily when the update_func reads
            # them (via their @computed property). There is no eager dep pass
            # here — an error inside a computed surfaces through the binding's
            # error-tolerant evaluation instead of aborting the whole effect.
            self.update_func()
            self.stale = False

    def mark_stale(self):
        if not self.stale:
            self.stale = True
            _dirty_effects.add(self)
            for dependent in self.dependents:
                dependent.mark_stale()


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
            new_node.add_declared(dep_node)
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
        if node:
            _dirty_effects.discard(node)

    def remove_node(self, name: str):
        """Remove any node (state, computed, or effect) by name, detaching it
        from both its dependencies and dependents so nothing dangles."""
        node = self.nodes.pop(name, None)
        if node is None:
            return
        for dep in node.dependencies:
            dep.dependents.discard(node)
        for depd in node.dependents:
            depd.dependencies.discard(node)
        if node in self.effects:
            self.effects.remove(node)
        if node in self._wildcard_effects:
            self._wildcard_effects.remove(node)
        _dirty_effects.discard(node)

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
        """Flush stale effects across ALL objects' graphs. Cross-object edges
        mark dependents on other objects, so a trigger on any graph drains the
        shared dirty queue (each effect runs at most once per flush)."""
        while _dirty_effects:
            effect = _dirty_effects.pop()
            effect.update()


# ──────────────────────────────────────────────
# Reactive scopes — grouped teardown (P4)
# ──────────────────────────────────────────────

class ReactiveScope:
    """Owns the effects/computeds/subscriptions created inside a dynamic region
    of a component tree (a loop item, a region contribution, a mounted child, a
    subscription, a component instance) so they are torn down together with one
    ``destroy()`` call.

    Nodes still live on their owner's per-object ``DependencyGraph``; the scope
    merely records ``(graph, name)`` pairs (plus child scopes) so removal is a
    single pass. ``destroy()`` is idempotent.
    """

    def __init__(self, parent=None):
        self.parent = parent
        self.children = []
        self._effects = []      # list[(DependencyGraph, name)]
        self._computeds = []    # list[(DependencyGraph, name)]
        if parent is not None:
            parent.children.append(self)

    def child(self):
        """Create a child scope (auto-linked to this one)."""
        return ReactiveScope(parent=self)

    def add_effect(self, graph, name, update_func, dependencies):
        graph.add_effect(name, update_func, dependencies)
        self._effects.append((graph, name))

    def add_computed(self, graph, name, func, owner, dependencies):
        node = graph.add_computed(name, func, owner, dependencies)
        self._computeds.append((graph, name))
        return node

    def record_effect(self, graph, name):
        """Record an effect created elsewhere (e.g. a subscription edge on a
        target's graph) so ``destroy()`` removes it from that graph."""
        self._effects.append((graph, name))

    def destroy(self):
        """Tear down every owned resource (recursively) and detach from the
        parent scope. Idempotent."""
        for child in list(self.children):
            child.destroy()
        for graph, name in self._effects:
            graph.remove_effect(name)
        for graph, name in self._computeds:
            graph.remove_node(name)
        self._effects = []
        self._computeds = []
        self.children = []
        if self.parent is not None and self in self.parent.children:
            self.parent.children.remove(self)


# ──────────────────────────────────────────────
# @computed Decorator
# ──────────────────────────────────────────────

def computed(args=None, dependencies=None):
    """
    Decorator to mark a method as a computed property — a memoized, lazily
    computed value whose dependencies are discovered by EXECUTION TRACKING when
    the body first runs (every reactive read becomes a real DAG edge). An
    explicit ``dependencies=[...]`` list (e.g. ``["$store.x"]`` relay deps) is
    honored and re-attached on every update.
    Can be used as @computed or @computed(dependencies=['a', 'b'])
    """
    def decorator(func):
        # Store metadata on the function itself
        func._is_computed = True
        # Declared deps only — the body's reactive reads are tracked at run time.
        actual_deps = dependencies if dependencies is not None else []
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


def derived(func):
    """Decorator marking a method as a per-context (keyed) derived value.

    Unlike ``@computed`` (one reactive property per object), a ``@derived``
    method is a reactive FUNCTION: the surrounding context builder (e.g. the
    loop body builder) instantiates one ``ComputedNode`` per key — per loop
    item — each memoized and invalidated by execution-tracked dependencies
    (owner/store reads) or by a new key arriving (item reuse). See
    REACTIVITY-OVERHAUL.md P4c.

    V1: dependencies are discovered by execution tracking only (no
    ``dependencies=[...]`` escape hatch) — revisit in P5.
    """
    func._is_derived = True
    return func


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
        # Root reactive scope — owns the effects/computeds/subscriptions this
        # object creates so they can be torn down together (P4).
        self.__dict__['_scope'] = ReactiveScope()

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

    def __getattribute__(self, name):
        # Execution read-tracking (P1, additive). When a computed/effect is
        # being evaluated (a tracker is on the stack), every public reactive
        # read is recorded against the innermost tracker. No tracker -> plain
        # attribute lookup (the common path — zero behavior change).
        if _tracker_stack and not name.startswith('_'):
            node = self._resolve_read_node(name)
            if node is not None:
                _tracker_stack[-1].add_dependency(node)
        return object.__getattribute__(self, name)

    def _resolve_read_node(self, name):
        """Map a public attribute read to its DAG node (state or computed), or
        None when the attribute is not a registered reactive value. During
        tracking, a real public attribute (a class default, or a cross-object
        read) is promoted to a StateNode on demand so future assignments trigger
        it."""
        dag_nodes = self.__dict__.get('_dag_nodes')
        if dag_nodes is None:
            return None
        node = dag_nodes.get(name)
        if isinstance(node, (StateNode, ComputedNode)):
            return node
        if _tracker_stack and self._is_trackable_attr(name):
            return self._dag.get_or_create_state(name)
        return None

    def _is_trackable_attr(self, name):
        """True when ``name`` resolves to a real, non-callable attribute on this
        object (instance or class level) — i.e. a would-be StateNode."""
        if name.startswith('_'):
            return False
        if name in self.__dict__:
            return not callable(self.__dict__[name])
        for klass in type(self).__mro__:
            if name in klass.__dict__:
                value = klass.__dict__[name]
                if isinstance(value, property):
                    return False
                return not callable(value)
        return False

    def _tracked_reads(self, func):
        """Run ``func(self)`` inside a fresh tracking context and return the
        set of DAG nodes the body read — across objects. P1 additive plumbing;
        ``ComputedNode.update`` switches to this as its dependency source in P2."""
        probe = _TrackingProbe()
        with _track(probe):
            func(self)
        return probe.dependencies

    def react(self, names: list[str]):
        if isinstance(names, str):
            raise Exception("Please pass only a list of strings to react().")
        self._dag.trigger_batch(names)

    def refrain(self):
        return Refrain(self)

    def _init_computed(self):
        """Scan class for @computed methods and register them as ComputedNodes.
        Values are computed lazily on first access, with dependencies discovered
        by execution tracking at that point.  Dependency EDGES are primed
        eagerly (a tracking dry-run that computes no value and swallows errors)
        so a computed that is subscribed to but never rendered still
        propagates."""
        for name, member in inspect.getmembers(self.__class__):
            member_func = getattr(member, 'fget', member)
            if hasattr(member_func, '_is_computed'):
                deps = getattr(member_func, '_dependencies', [])
                original_func = getattr(member_func, '_original_func', None)
                if original_func:
                    node = self._dag.add_computed(name, original_func, self, deps)
                    node.prime_deps()
