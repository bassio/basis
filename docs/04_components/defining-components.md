# Defining Components

A Basis component is a Python class that combines an HTML template, optional CSS, and reactive state. There are two ways to organize the files, and the framework supports both.

---

## Single-file components

For small or self-contained UI elements, everything lives in one `.py` file. The HTML template goes in the class docstring (or in a `template` method's docstring); CSS goes in a `style` class variable.

```python
from basis.shared.component import Component
from basis.shared.dag import computed

class Counter(Component):
    """
    <div class="counter-card">
        <h3>Simple Counter</h3>
        <p>Current value: <strong>{count}</strong></p>
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

    def increment(self):
        self.count += 1
```

Class-level variables like `count = 0` become reactive state nodes. Assigning to `self.count` anywhere triggers the DAG to update the DOM nodes that reference it.

---

## Multi-file components

For larger components, keeping HTML and CSS inside Python strings gets unwieldy. Basis supports splitting into separate files as long as they share the same name as the parent folder:

```text
components/
└── todo_list/
    ├── todo_list.py    ← Python class
    ├── todo_list.html  ← HTML template
    └── todo_list.css   ← Stylesheet
```

> [!IMPORTANT]
> The `.html` and `.css` files must be named after the **parent folder**, not the `.py` file. The framework looks for `<parent_folder_name>.html` and `<parent_folder_name>.css` relative to the Python file's location.

### `todo_list.py`

No HTML or CSS needed here — just define the class and its logic:

```python
from basis.shared.component import Component

class TodoList(Component):
    items = ["Buy groceries", "Write Basis docs"]

    def add_todo(self, event):
        # ...
        pass
```

### `todo_list.html`

Standard HTML with braces interpolation:

```html
<div class="todo-wrapper">
    <h2>My Tasks</h2>
    <ul>
        <li for="task" in="{items}">{task}</li>
    </ul>
</div>
```

### `todo_list.css`

Plain CSS — no pre-processing, no utility class framework required:

```css
.todo-wrapper {
    background-color: white;
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.05);
    border-radius: 12px;
    padding: 24px;
}
```

Basis detects matching `.html` and `.css` files at class definition time and loads their contents into `__templatestr__` and `style` on the class. Your editor can syntax-highlight each file correctly since they're proper HTML and CSS files rather than strings inside Python.
