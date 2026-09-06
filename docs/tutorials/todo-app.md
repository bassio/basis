# Tutorial: The Todo List

A list you can add to and remove from — the mini-app that shows off list
state, the **loop binding**, and **two-way binding**. Try it live on the site's
Showcase page (under **Mini-Apps → Todo**).

By the end you'll understand how Basis turns a Python list into a live, always
in-sync DOM list — and what "keyed reconciliation" means.

---

## The whole app

```python
from basis.shared.component import Component


class Todo(Component):
    items = [{"text": "Learn bindings"}, {"text": "Add a server action"}]
    new_item = ""

    def add(self, event):
        value = self.new_item.strip()
        if value:
            self.items = [*self.items, {"text": value}]
            self.new_item = ""

    def remove(self, event):
        index = int(event.currentTarget.getAttribute("data-index"))
        self.items = [t for i, t in enumerate(self.items) if i != index]

    def template(self):
        """
        <input bind="{new_item}" placeholder="What needs doing?" />
        <button onclick="{add}">Add</button>
        <ul>
            <li for="item" in="{items}" index="_index">
                <span>{item['text']}</span>
                <button data-index="{item['_index']}" onclick="{remove}">✕</button>
            </li>
        </ul>
        """
```

---

## 1. `items` is list state

`items` is a plain Python list — and it is reactive. When you assign a new list
to `self.items`, every binding that reads it is notified. That includes the
`for` loop in the template.

Each item is a small dict `{"text": ...}` rather than a bare string. That
gives every row a place to carry extra per-item data — here just its text,
but it's also what lets the loop stamp a per-item **index** (see section 4).

## 2. The loop binding: `for="item" in="{items}"`

The `for` / `in` pair on the `<li>` is a **loop binding**. It's not a string of
HTML — it's a template that Basis reconciles against the list:

- **create** an `<li>` for each new item,
- **update** items whose value changed,
- **remove** items that disappeared,
- **move** existing nodes when items reorder.

Because the loop is keyed, a single change (add one item, delete one) only
touches the nodes that actually changed — the rest stay untouched. See
[Loop Bindings](../05_reactivity/loop-bindings.md) for the reconciliation
pipeline, and [Scoping in Loops](../04_components/loop-scope.md) for who owns
what inside a loop body.

> [!NOTE]
> Inside the loop body, `item` is the loop variable: `{item['text']}` renders
> the row's text. The `index="_index"` attribute makes the framework stamp each
> item with its positional position on every reconcile, so `{item['_index']}`
> is that row's index (`0`, `1`, `2`, …) — read back from `data-index` so the
> event handler knows which row was clicked.

## 3. Two-way binding with `bind`

`<input bind="{new_item}" />` is a **two-way binding** (a `ModelBinding`):

- typing in the input writes to `self.new_item` as you type,
- assigning to `self.new_item` writes back to the input.

That's why `add()` can read `self.new_item` and then clear the field with
`self.new_item = ""` — the input empties automatically. This is the same
mechanism that powers forms with validation, on plain elements and whole
`<form>`s alike. See [Forms & Validation](../04_components/forms-and-validation.md).

## 4. Handling the ✕ button

Each remove button carries its row's **index** in `data-index`. The index comes
from the loop's `index="_index"` attribute: on every reconcile the framework
stamps each item with its positional position, so `{item['_index']}` is `0`,
`1`, `2`, …. The handler is a plain method on the component:

```python
def remove(self, event):
    index = int(event.currentTarget.getAttribute("data-index"))
    self.items = [t for i, t in enumerate(self.items) if i != index]
```

`event.currentTarget` is the button that was clicked; the handler filters the
list by index and assigns it back. Removing by index is precise — two rows
holding the *same* text each keep their own index, so deleting one leaves the
other untouched (the older approach of filtering by the item's *value* would
delete every matching row).

The loop reconciles, the row disappears, and nothing else re-renders.

---

## What you learned

- A Python **list** is reactive list state.
- `for` / `in` is a **loop binding** with keyed reconciliation.
- `bind` gives **two-way binding** between an input and state.
- `index="_index"` stamps each row with its index, and the handler reads it off
  `data-index` to remove the exact row that was clicked.

## Where to go next

- The loop engine in depth: [Loop Bindings](../05_reactivity/loop-bindings.md)
- Storing state where any component can reach it: [State Stores](../05_reactivity/stores.md)
- Making the list *persist*: [Server Actions](server-actions.md) and
  [Database & SQLModel](../06_server_actions_and_db/database.md)
