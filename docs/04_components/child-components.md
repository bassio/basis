# Parent & Child Components

Components can be composed. Any `Component` subclass is available as a child inside another component's template, and parents can pass reactive state down to children.

---

## Referencing child components in templates

Basis uses *hyphenated* custom element tags to embed child components, following the Web Components convention:

- `UserProfile` → `<user-profile></user-profile>`
- `TodoItem` → `<todo-item></todo-item>`

> [!WARNING]
> Web standards require custom element tags to contain at least one hyphen, which distinguishes them from built-in HTML elements. If your class name doesn't naturally produce a hyphenated tag (e.g. a single-word class like `Sidebar`), set the `__tag__` attribute explicitly:
> ```python
> class Sidebar(Component):
>     __tag__ = "app-sidebar"
> ```

---

## Passing attributes to children

Parent components pass data to children via HTML attributes on the child's tag. Static values are passed as plain strings; reactive parent state is passed using braces syntax.

**Parent template:**
```html
<div>
    <h1>Management Console</h1>
    <user-card username="{current_username}" status="Active"></user-card>
</div>
```

**Child component (`user_card.py`):**
```python
class UserCard(Component):
    """
    <div class="card">
        <h3>User: {username}</h3>
        <p>Status: {status}</p>
    </div>
    """
    username = "Guest"
    status = "Offline"
```

When the parent's `current_username` changes, Basis propagates the new value into the child's `username` state and the child's template updates accordingly.

---

## Content projection with slots

Sometimes you need to pass entire blocks of markup into a child component, not just simple values. Basis implements the standard HTML `<slot>` element for this.

**Child layout component (`child_card.html`):**
```html
<div class="card-container">
    <header class="card-header">
        <slot name="header">Default Header</slot>
    </header>
    <main class="card-body">
        <slot></slot>
    </main>
</div>
```

**Parent template:**
```html
<div class="dashboard">
    <child-card>
        <h2 slot="header">System Alerts</h2>
        <p>Server CPU utilization is at 89%. Please monitor.</p>
        <button onclick="{clear_alert}">Acknowledge</button>
    </child-card>
</div>
```

Children with a `slot="..."` attribute are inserted into the matching named slot. Children without a `slot` attribute go into the unnamed default slot.

During server-side rendering, Basis reads the parent's inner children (the "light DOM") and inserts them into the child's template at the slot positions. During client hydration, `SlotBinding` identifies these zones and ensures they aren't overwritten when the child component re-renders.
