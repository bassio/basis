# Scoping in Loops: who owns the loop body?

When you write a `for` loop in a Basis template, the loop body is authored in
*your* component's template — but it is rendered once per item by a
synthesized child component. That raises a question that is easy to get wrong:
**whose scope do the `{...}` expressions inside the loop body resolve in?**

This page defines the mental model, shows the (verified) behaviour for every
case, and documents the footguns so they never bite silently.

---

## The mental model: the loop body is parent-scope + loop variable

The loop body is **not** a private island. It is written in the parent's
template, so it sees:

1. **the loop variable** — `d` in `for="d" in="{days}"` is bound to the current
   item, and
2. **the parent's live scope** — every reactive field, `@computed`, method and
   store reference the parent can see.

This matches the mainstream component mental model (Vue `v-for`, Svelte
`{#each}`, React `.map()`): inside a loop you get the item **and** the enclosing
component's state. It is *not* "everything must be item-scoped" — a parent
computed like `{month_name}` inside a loop is perfectly valid and should resolve
to the **parent's** current value.

```html
<div for="d" in="{days}" key="date_str" class="{d['classes']}"
     data-date="{d['date_str']}" onclick="{on_select}">
    {d['day_num']} / {month_name}   <!-- item AND parent computed — both valid -->
</div>
```

> **Rule of thumb:** if you could write the expression *outside* the loop in
> this component's template, you can write it *inside* the loop too — and it
> means the same thing, live. The loop variable is the only name that is
> *added* by the loop.

---

## What is actually implemented today

The mechanism is: the loop body is analysed at
class time into per-item binding blueprints. At runtime each item is a thin
`LoopItem` holder — its own wrapper node plus a per-item `LoopScope` overlay
that binds the loop variable — and the body's bindings are **bound to the
owner**, the component that wrote the template, not to a synthesized child
component. A `{...}` expression resolves through the per-item scope chain
first, then the owner's live scope; body bindings register their
owner-dependencies on the owner's DAG, so parent fields in a loop body stay
live with no prop copying.

### The three cases, verified

| Case | What the loop body is | `{item[...]}` | `{parent_computed}` | events |
|---|---|---|---|---|
| **A — plain element** (`<div for="d" in="{days}">…</div>`) | owner's live scope + per-item loop-var overlay (thin `LoopItem`) | ✅ item | ✅ live (owner-bound DAG edge) | ✅ run on the parent (owner-bound handler) |
| **B — custom element** (`<ui-text for="it" in="{items}">…</ui-text>`) | **slot content** (light DOM) | ❌ **not bound** — renders literal `{it['n']}` | ❌ not bound | ✅ per-child events (child's own template) |
| **C — custom element, not in a loop** (`<ui-text>…</ui-text>`) | slot content | n/a | ✅ resolved in the **parent's** scope | n/a |

Verified against the framework (server model):

- **Case A** — `{d['day_num']}` renders the item. `{month_name}` resolves
  against the owner's live `@computed` and tracks it (the body binding is
  owner-bound with a DAG edge on the owner — no copied props).
- **Case B** — the walker skips loop subtrees in the parent, and the registered
  child class only analyses its *own* template. The light-DOM content of the
  looped element therefore gets **no binding at all** and renders literally.
- **Case C** — the walker *does* descend, so the slot content is bound in the
  **parent's** scope (classic web-component light-DOM semantics).

### Events: the parent owns the handler, the item travels in the DOM

Event handlers inside a loop (`onclick="{on_select}"`) run on the **parent**
(the template owner — owner-bound natively), so `self` is the parent and can
mutate parent state directly.
The handler still needs to know *which item* was clicked — it reads the
per-item `data-*` attributes already rendered onto the node:

```python
def on_select(self, event):
    curr = event.target
    while curr:
        if hasattr(curr, "getAttribute") and curr.getAttribute("data-date"):
            self.selected_date = curr.getAttribute("data-date")
            break
        curr = curr.parentNode
```

This is the canonical idiom: **render the item's identity into `data-*` attrs
in the loop, then read it back from `event.target` in the handler.** (See
`basis/ui/calendar`, `basis/ui/context_menu`, `basis/ui/file_upload`.)

---

## Footguns

### 1. Parent fields in the loop body stay live

Loop-body bindings are **bound to the owner** and register owner-dependencies
on the owner's DAG, so a parent field read in a loop body updates live even
when the loop's `in=` collection does not change (regression-tested by
`tests/test_loop_scope_contract.py::test_loop_body_parent_field_stays_live`).

### 2. Custom-element loop children ignore their slot content

`<ui-text for="it" in="{items}">{it['n']}</ui-text>` looks like it should render
`{it['n']}` per item. It doesn't — the slot content is **not bound** and renders
literally (or is dropped). Per-item data must flow to a custom-element loop
child through **attributes**, not slot content:

```html
<ui-text for="it" in="{items}" key="n" label="{it['n']}"></ui-text>
```

The child renders `{label}` in its *own* template. This is the supported idiom
for every custom-element loop child (`<team-entry>`, `<ui-tree-node>`,
`<ui-tab>`, `<status-item>`, …).

### 3. Don't rely on `self.<item>` inside a handler

Loop event handlers run on the **owner** (`self` is the parent component, and
the handler is owner-bound natively), so the loop variable is *not* a property
of `self`. If a handler needs the item, read it from the event
target's `data-*` attributes (the canonical idiom above), not from `self`.

---

## Summary

- **Mental model:** loop body = parent's live scope **plus** the loop variable.
- **Events** in loops run on the parent; identify the item via `data-*` on the
  event target.
- **Custom-element loop children**: pass per-item data via attributes; slot
  content inside a loop is unsupported today.
- **Known gap:** custom-element loop children pass per-item data via
  attributes only; slot content inside a loop remains unbound (footgun #2).
  Parent fields in a plain-element loop body stay live (owner-bound).

*See also [Components](tutorial.md#2-components), [Importing Components &
the Isomorphism Principle](importing-components.md), and [SSR & Client
Hydration](../05_reactivity/ssr-hydration.md).*
