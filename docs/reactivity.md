# Reactivity in Basis

Basis is powered by a high-performance **Directed Acyclic Graph (DAG)** reactivity engine. Unlike other frameworks that rely on a Virtual DOM and complex diffing algorithms, Basis knows exactly which part of the UI depends on which piece of state.

## State Nodes

Any attribute defined on a `Component` class automatically becomes a **State Node**.

```python
class MyComponent(Component):
    count = 0
```

When you update `self.count`, the DAG triggers all dependent nodes.

## Computed Properties

You can create derived state using the `@computed` decorator. Basis discovers a computed's dependencies by **execution tracking**: whatever reactive attributes the body actually reads when it runs become DAG edges — including reads through helper methods, `getattr`, or other stores and components.

```python
from basis.shared.reactive import computed

class MyComponent(Component):
    count = 1

    def _triple(self):
        return self.count * 3

    @computed
    def doubled(self):
        return self.count * 2

    @computed
    def tripled(self):
        return self._triple()   # helper indirection is still tracked
```

In the template:
```html
<p>Count: {count}</p>
<p>Doubled: {doubled}</p>
```
When `count` changes, `doubled` (and `tripled`) are recalculated, and only the relevant parts of the DOM are updated.

Computed values are **lazy** and **memoized** — the body runs at most once per dependency change. If a computed computes with no reactive dependencies at all, Basis warns once, because it can never recompute.

### Rules of reactivity

- **Assignment triggers**: `self.count = 2` marks every dependent stale.
- **In-place mutation does not**: `self.items.append(...)` does not trigger — reassign the list, or call `react([...])`.
- **Dependencies are runtime reads**: helper methods, `getattr`, dotted chains, and other `ReactiveObject`s all count.
- **Cross-store / cross-component edges are real**: a computed can read another store or component directly.
- **Manual override**: use `@computed(dependencies=[...])` for a dependency the body doesn't read (e.g. a `$store.x` relay).
- **Per-loop-item values**: use `@derived` for one memoized value per loop item — see [Loop Bindings](05_reactivity/loop-bindings.md).

## Fine-Grained Updates

Because Basis understands the dependency graph:
1. It identifies the exact DOM nodes (text nodes, attributes, etc.) that depend on a State Node.
2. It updates those nodes directly using native browser APIs.
3. It bypasses the overhead of re-rendering entire component trees.

## Two-Way Binding

The `bind` attribute simplifies form handling:

```html
<input bind="{username}">
```

This is equivalent to:
- A text binding that sets the input value to `username`.
- An event listener that updates `username` whenever the input changes.

Everything stays in sync with zero boilerplate.
