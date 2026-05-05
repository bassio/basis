# Basis: Full-Stack Reactive Python Framework

Basis is a modern, high-performance web framework that allows you to build interactive, stateful web applications entirely in Python. By leveraging **FastAPI** on the backend and **PyScript** on the frontend, Basis enables a "0% JavaScript" developer experience while maintaining the reactive, component-based architecture familiar to React or Vue developers.

## Core Philosophy

- **Python Everywhere**: UI logic, state management, and backend services are all written in Python.
- **Native Custom Elements**: Components are compiled into standard Web Components (Custom Elements), ensuring native browser performance.
- **Fine-Grained Reactivity**: No Virtual DOM. Basis uses a Dependency Graph to surgically update only the parts of the DOM that changed.
- **SSR + CSR Hybrid**: Seamless transition from Server-Side Rendering to Client-Side Hydration.

---

## Key Features

### 1. DAG-Based Reactivity
Basis employs a **Directed Acyclic Graph (DAG)** to manage state propagation. Instead of flat re-rendering, the framework tracks:
- **StateNodes**: Raw source-of-truth attributes.
- **ComputedNodes**: Derived values that automatically update when their dependencies change.
- **EffectNodes**: Side-effects like DOM updates that react to state or computed changes.

### 2. Computed Properties
Use the `@computed` decorator to define derived state. Basis automatically analyzes the AST of your function to detect dependencies, ensuring memoized and efficient updates.

```python
@computed
def full_name(self):
    return f"{self.first_name} {self.last_name}"
```

### 3. Smart Keyed Reconciliation
The `SmartKeyedLoopBinding` uses the **Longest Increasing Subsequence (LIS)** algorithm to perform granular DOM updates on lists.
- **Focus Preservation**: Moving items in a list won't cause them to lose input focus or local state.
- **Minimal Mutation**: Only moved, added, or removed nodes are touched in the DOM.
- **Performance**: Drastically reduces the overhead of large list updates compared to standard `replaceChildren` approaches.

### 4. Cross-Boundary State (DSL)
Basis introduces a simple DSL to link reactivity across component boundaries:
- **`$store.field`**: Bind directly to a shared `Store` instance.
- **`#component_id.field`**: Bind to an attribute of another component instance in the DOM.

```html
<p>Store Value: {$my_store.count}</p>
<child-comp id="child" message="Hello"></child-comp>
<p>Child said: {#child.reply}</p>
```

### 5. Hot Module Replacement (HMR)
Experience lightning-fast development with built-in HMR. Basis can hot-swap component logic, templates, and styles in the browser without a full page reload, preserving the current application state.

---

## Project Structure

The framework is structured into distinct tiers to support its full-stack nature:

- **`basis/shared/dag.py`**: The reactive engine power by a Dependency Graph.
- **`basis/shared/bindings.py`**: High-performance DOM binding classes (`Text`, `Attribute`, `Loop`, `SmartKeyedLoop`).
- **`basis/shared/base_component.py`**: The foundational class for both SSR and CSR components, managing hydration and state.
- **`basis/components/`**: Browser-side modules for Custom Element registration and PyScript integration.
- **`basis/server/`**: FastAPI-based server that handles SSR and dynamic asset delivery.
- **`basis/shared/hmr.py`**: Client-side HMR logic for WebSocket-based updates.

---

## How it Works

1.  **Template Analysis**: At class definition time (using `__init_subclass__`), Basis parses your HTML template, extracts Python expressions, and builds **Blueprints** for every binding.
2.  **SSR**: The server renders the initial HTML using these Blueprints, ensuring fast first-contentful paint.
3.  **Hydration**: In the browser, PyScript takes over. The component "hydrates" by connecting the pre-rendered DOM to a live Python instance.
4.  **Reactivity**: When a Python attribute is modified (via overridden `__setattr__`), the DAG triggers only the relevant `EffectNodes`, which surgically mutate the DOM.

## Getting Started

Check out the `test_smart_loop.py` or `test_hmr.py` for live examples of the latest reactive features.
