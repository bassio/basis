# Tutorial: The Counter

The smallest possible reactive app — and where the whole Basis mental model
starts. You can try it live on the site's Showcase page (under **Mini-Apps →
Counter**).

By the end of this tutorial you'll understand the three pieces every Basis
component is built from: **reactive state**, a **binding**, and an **event
handler**.

---

## The whole app

```python
from basis.shared.component import Component


class Counter(Component):
    count = 0

    def increment(self):
        self.count += 1

    def template(self):
        """
        <button onclick="{increment}">Count: {count}</button>
        """
```

That is the entire app. Click the button, and the label updates — nothing else
on the page is touched.

---

## 1. `count = 0` is reactive state

A plain class attribute on a `Component` becomes a **state node** in Basis's
dependency graph (the DAG). It's just Python — you read and write it with
`self.count += 1` — but the framework is watching it, and any binding that
reads it is recorded as a dependent.

You can think of the component's attributes as the "reactive surface" of your
UI: changing one re-renders *only the parts of the DOM that read it*.

> [!TIP]
> State is **isomorphic** — the same `Counter` class runs on the server (to
> pre-render the HTML at first load, SSR) and in the browser (PyScript) to
> handle updates. You write it once.

## 2. `{count}` is a binding

Inside the template, `{count}` is a **binding**: a little expression that reads
component state. At first render it becomes the current value (`0`); afterwards
it is connected to the DAG so that whenever `count` changes, exactly this text
node is updated.

Bindings aren't limited to plain names — `{count + 1}`, `{len(items)}`, or any
expression over state works. See [The Braces Syntax](../05_reactivity/braces-syntax.md)
for the full expression language.

## 3. `onclick="{increment}"` is an event handler

Any method on the component can be wired to a DOM event with an `on*`
attribute. `onclick="{increment}"` calls `increment()` when the button is
clicked — no `addEventListener`, no boilerplate.

The handler mutates state (`self.count += 1`), the DAG marks `count` stale,
and the bound text node re-renders. That's the whole loop:

```text
event → handler → state change → DAG → only the affected node re-renders
```

> [!NOTE]
> There is no virtual DOM and no diffing. The framework knows *exactly* which
> node depends on `count`, so it updates that one node and nothing else. See
> [DAG Reactivity Engine](../05_reactivity/dag.md) for how this works under the
> hood.

---

## What you learned

- Component **state** is just attributes; they power the reactive DAG.
- `{...}` **bindings** connect state to the DOM.
- `on*` **event handlers** are plain methods that mutate state.

## Where to go next

- The full component model: [Defining Components](../04_components/defining-components.md)
- The binding engine: [The Binding Engine](../05_reactivity/bindings.md)
- Two-way input binding with `bind` and forms: [Forms & Validation](../04_components/forms-and-validation.md)
- The next mini-app, which adds a list and a loop: [The Todo List](todo-app.md)
