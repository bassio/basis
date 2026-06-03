# Basis: Full-Stack Reactive Python Framework

Basis is an experimental full-stack web framework for building interactive, stateful web applications entirely in Python. It runs FastAPI on the server for initial Server-Side Rendering (SSR) and PyScript in the browser for Client-Side Hydration (CSH), providing a reactive, component-based developer experience with no JavaScript.

---

## Quickstart

### 1. Installation
Install the framework alongside FastAPI and Uvicorn:
```bash
pip install fastapi uvicorn basis-framework
```

### 2. Create a minimal Basis App (`app.py`)
```python
from basis.shared.component import Basis, Component

app = Basis()

@app.entrypoint
class HelloBasis(Component):
    """
    <div><input bind="{name}" placeholder="Type your name..." />Hello {name}!</div>
    """

    name = "World"

```

### 3. Run the Development Server
```bash
uvicorn app:app --reload
```
Navigate to `http://localhost:8000` to interact with the application.

---

## Core Philosophy

- **Python Everywhere** — Write backend services, business logic, component templates, and client-side reactive state in pure Python.
- **Native Custom Elements** — Components map to standard hyphenated HTML custom tags, keeping styling and markup aligned with web standards.
- **Fine-Grained Reactivity** — No Virtual DOM. Basis uses a Directed Acyclic Graph (DAG) to track dependencies and update only the targeted DOM nodes when state changes.
- **Isomorphic Hydration** — Server renders fully-formed, SEO-friendly HTML, which the client hydrates in-place without flashes of unstyled content or layout shifts.

---

## Key Features

### 1. DAG-Based Reactivity
Basis manages state propagation using a Directed Acyclic Graph (DAG) with three node types:
- **`StateNode`**: The root state sources (raw component attributes).
- **`ComputedNode`**: Derived values that cache results and recalculate only when their upstream dependencies change.
- **`EffectNode`**: Leaves of the graph representing DOM updates (bindings) that react to state or computed mutations.

### 2. Computed Properties
Use the `@computed` decorator to define derived state. Basis parses the function's Abstract Syntax Tree (AST) to automatically detect dependency attributes:

```python
@computed
def full_name(self):
    return f"{self.first_name} {self.last_name}"
```

### 3. Smart Keyed Reconciliation
The `SmartKeyedLoopBinding` uses a Longest Increasing Subsequence (LIS) algorithm to dynamically reorder and update DOM list items in-place. This preserves browser input focus, scroll position, and CSS animations during list sorting or updates.

### 4. Cross-Boundary References
The template braces syntax supports special prefixes to bind reactive state across boundaries:
- **`$store_name.field`**: Subscribes directly to a shared, global `Store` instance.
- **`#component_id.field`**: Subscribes to the attribute of another component in the DOM by its HTML `id`.

```html
<p>Store Value: {$session.count}</p>
<child-comp id="child"></child-comp>
<p>Child status: {#child.status}</p>
```

---

## Codebase Structure

The framework codebase is structured as follows:

- `basis/src/basis/shared/dag.py` — The reactive dependency graph engine.
- `basis/src/basis/shared/bindings.py` — DOM bindings (Text, Attribute, Loops, Slots).
- `basis/src/basis/shared/base_component.py` — Base component lifecycle, state mapping, and setup.
- `basis/src/basis/client/` — Browser-side component mounting and PyScript entrypoint.
- `basis/src/basis/server/` — FastAPI application wrapper, static file servers, and RPC router.

---

## Documentation

For a comprehensive guide, architecture diagrams, and detailed API breakdowns of stores, bindings, and hydration, browse the files in the **`docs/`** directory starting with **[docs/index.md](docs/index.md)**.
