# Core Philosophy

Basis is organized around six design principles. They're not aspirational — each one is a concrete trade-off that shaped the API and the runtime.

---

## 1. Embrace Web Standards

Basis doesn't compile Python into JavaScript, and it doesn't invent its own HTML-like DSL. The web's native primitives — HTML, CSS, and the DOM — have been refined over decades and work extremely well.

- Components use standard HTML templates.
- State binds directly to native DOM elements, attributes, and text nodes.
- Custom component tags follow the Web Components hyphenation convention (`<my-card>`, not `<MyCard>`).

This means your existing HTML/CSS knowledge carries over, and the output is always inspectable, debuggable standard markup.

---

## 2. Python-First

With Basis, your backend APIs, database models, business logic, and client-side component state all live in Python. There's no second language to context-switch into and no API layer to maintain just for UI updates.

In practice this means:
- You can import any Python library directly inside a component.
- Type hints, IDE autocomplete, and linting work across the entire stack.
- A single file can contain both server-side data fetching and the reactive template that renders it.

---

## 3. Intuitive by Design

Many modern frontend frameworks impose a significant cognitive overhead: hook dependency arrays, stale closure bugs, immutable state patterns, effect scheduling. These are real problems worth solving, but they shouldn't be problems you encounter just trying to build a form.

Basis takes a different approach. Mutating state looks like normal Python assignment:

```python
self.count += 1
```

The underlying Directed Acyclic Graph (DAG) reactivity engine intercepts that assignment, traces which DOM nodes depend on `count`, and updates only those nodes. You don't manage dependency lists or call special setter functions.

---

## 4. Buildless

Basis requires no Node.js, no npm, and no compilation step. PyScript loads your `.py` source files, HTML templates, and CSS stylesheets directly in the browser. There is no intermediate build artifact.

---

## 5. Component-Driven

Basis supports two component layouts:

- **Single-file**: Template, styles, and logic all live in one Python class. Good for small, self-contained UI elements.
- **Multi-file**: The `.py`, `.html`, and `.css` files live in the same folder with matching names. Good for complex components where mixing languages inside a Python string becomes unwieldy.

Both are first-class. The framework detects which layout you're using automatically.

---

## 6. Isomorphic

The same Python component class runs on the server (to pre-render SEO-complete HTML via FastAPI) and in the browser (to hydrate that HTML and handle all subsequent reactive updates via PyScript). You write it once.

The server render is fast and produces fully-formed HTML — search engines and link previews see the complete content immediately, with no flash of blank content. The browser then attaches reactive bindings to the existing DOM nodes without rebuilding anything, giving you the interactivity of a SPA from that point on.

> [!TIP]
> This is similar in spirit to HTMX's philosophy of keeping server and client aligned — but where HTMX requires a network round-trip for every dynamic update, Basis runs updates directly in the browser. Server calls are only needed when you're writing to a database or performing a task that genuinely belongs on the server.
