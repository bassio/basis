# Defining Components

A Basis component is a Python class that combines an HTML template, CSS styling, and reactive state. Basis supports both single-file and multi-file component layouts.

---

## Single-file components

For small or self-contained UI elements, everything lives in a single `.py` file. The HTML template is defined in the class docstring (or in a `template` method docstring); CSS styling is specified in a `style` class variable.

```python
from basis.shared.component import Component
from basis.shared.reactive import computed

class Counter(Component):
    """
    <div class="counter-card">
        <h3>Simple Counter</h3>
        <p>Current value: <strong>{count}</strong></p>
        <p>Double value: <strong>{double_count}</strong></p>
        <button onclick="{increment}">+ Increment</button>
    </div>
    """

    count = 0

    style = """
    .counter-card {
        padding: 16px;
        background: #f8fafc;
        border-radius: 8px;
        border: 1px solid #e2e8f0;
        text-align: center;
    }
    button {
        background: #6366f1;
        color: white;
        border: none;
        padding: 8px 16px;
        border-radius: 4px;
        cursor: pointer;
    }
    """

    @computed
    def double_count(self):
        return self.count * 2

    def increment(self):
        self.count += 1
```

### Class Attributes & State Nodes
Class-level variables like `count = 0` are automatically converted into reactive state nodes during component setup. Assigning to `self.count` inside event handlers updates the state and triggers the reactive graph to update bound DOM nodes.

### `@computed` Properties
Decorating a method with `@computed` creates a derived state node. Dependencies are discovered by **execution tracking**: Basis records whatever reactive attributes the body actually reads when it runs (including reads through helper methods or other objects) and recalculates `double_count` only when one of those changes. Values are **lazy** and **memoized**. For the full contract — manual `dependencies=[...]`, cross-store/cross-component edges, the in-place-mutation rule, and the per-loop-item `@derived` decorator — see [The DAG Reactivity Engine](../05_reactivity/dag.md).

---

## Multi-file components

For larger components, keeping HTML markup and CSS styling inside Python strings can become unwieldy. Basis supports organizing components into folders where `.html` and `.css` files are placed alongside the `.py` file:

```text
components/
└── todo_list/
    ├── todo_list.py    ← Python class logic
    ├── todo_list.html  ← HTML template
    └── todo_list.css   ← Stylesheet
```

> [!IMPORTANT]
> The `.html` and `.css` files must be named after the **parent folder** (e.g. `todo_list.html` inside a folder named `todo_list`). Basis automatically detects these matching files at import time and attaches them to `__templatestr__` and `style`.

### `todo_list.py`

```python
from basis.shared.component import Component

class TodoList(Component):
    items = ["Buy groceries", "Write Basis docs"]

    def add_todo(self, event):
        pass
```

### `todo_list.html`

```html
<div class="todo-wrapper">
    <h2>My Tasks</h2>
    <ul>
        <li for="task" in="{items}">{task}</li>
    </ul>
</div>
```

### `todo_list.css`

```css
.todo-wrapper {
    background-color: white;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
    border-radius: 12px;
    padding: 24px;
}
```

> [!TIP]
> Once you can define a component, learn how to customize and extend it — including the built-in `basis.plugins.ui` suite — in [Styling Components](styling-components.md) (look & feel) and [Extending & Customizing Components](extending-components.md) (structure & behavior).
