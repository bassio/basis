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

You can create derived state using the `@computed` decorator. Basis automatically tracks dependencies based on the attributes you access within the function.

```python
from basis.shared.dag import computed

class MyComponent(Component):
    count = 1
    
    @computed
    def doubled(self):
        return self.count * 2
```

In the template:
```html
<p>Count: {count}</p>
<p>Doubled: {doubled}</p>
```
When `count` changes, `doubled` is recalculated, and only the relevant parts of the DOM are updated.

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
