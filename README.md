# ⚡ Basis

**Full-stack isomorphic reactive web apps in Python.**

## Pitch

Basis is a component-based web framework that runs the *same* Python on your server and in your browser. Your server-side FastAPI app **is** also your frontend: your components render to complete HTML on the server using SSR (Server-Side Rendering), then hydrate into a fully interactive, reactive app in the browser — all driven by Python, backed by the power of Pyodide and Pyscript.

No JavaScript for you to write, no build step, no `package.json`!

If you've ever wanted the React or Svelte developer experience without having to deal with complicated build steps, and without leaving Python, then Basis is for you.


### Show me the code: a simple Basis Web Component

A Basis component is a Python class that compiles to a **real web component** — a native HTML custom element, styled with standard CSS you can override. Template, state, and logic live in one file, one class (similar to Vue/Svelte single-file compoments):

```python
from basis.shared.component import Component
from basis.shared.reactive import computed

class Counter(Component):
    """
    <button onclick="{increment}">Count: {count} (double: {double_count})</button>
    """

    __tag__ = "my-counter"      # custom element tag including "-" — drop this into your html

    count = 0                   # reactive state

    @computed                   # derived state, recomputed when `count` changes
    def double_count(self):
        return self.count * 2

    def increment(self):        # event handler wired by onclick in the template
        self.count += 1
```

Drop it into any template like a built-in element:

```html
<my-counter></my-counter>
```

Click the button: `count` updates, `double_count` recomputes, and only that node re-renders — no virtual DOM, no JavaScript, no build step. The **same Python class** renders this HTML on the server (SSR) and hydrates it in the browser.

Mimic the React/Svelte component model (components, props, state, slots), but in Python. For the full mental model, see [Extending & Customizing Components](docs/04_components/extending-components.md) and [Styling Components](docs/04_components/styling-components.md).


### Why Basis?

- **Python everywhere.** Backend logic, business rules, component markup, and client-side reactivity are all Python. One language, one mental model, one type-checked codebase — no context-switching.
- **Buildless.** No Node.js, no npm, no compilation step, no `package.json`. PyScript loads your `.py` files, templates, and stylesheets directly in the browser.
- **Web standards.** Components are native Custom Elements; templates are plain HTML; styles are plain CSS that participates in the normal cascade; state binds to the native DOM.
- **No new DSL to learn** Component syntax is just html and css. Python is used to define reactive code, only as a substitute for writing javascript.
- **Isomorphic.** The same component class server-renders complete HTML (fast, SEO-friendly, no blank screen) and then hydrates in-place in the browser — no flash of unstyled content, no layout shift.
- **Fine-grained reactivity, no virtual DOM.** A dependency graph (DAG) tracks exactly which DOM nodes depend on which state and updates *only* those nodes.
- **FastAPI under the hood.** `Basis` *is* a FastAPI application, so routes, middleware, and your existing FastAPI knowledge all carry over.

---

## Quickstart

### 1. Install

```bash
pip install fastapi uvicorn basis-framework
```

*Requires Python 3.14+.*

### 2. Write an app

```python
from basis.shared.component import Basis, Component

app = Basis()

@app.page
class HelloBasis(Component):
    """
    <div>
        <input bind="{name}" placeholder="Type your name..." />
        <h1>Hello {name}!</h1>
    </div>
    """

    name = "World"
```

Save this as `app.py`.

That's the whole app: two-way binding, reactive state, and server-side rendering included. Type into the box and the `<h1>` updates live.

### 3. Run it

```bash
basis dev          # dev server with live hot-module reload (default)
```

or directly via Uvicorn (similar to any FastAPI application):

```bash
uvicorn app:app --reload
```

Open `http://localhost:8000` and start typing. Edit a component's `.py`, `.html`, or `.css` and watch the open tab update live with no page refresh and no lost state.

---

## Batteries included

Beyond the core, Basis ships with what you need to build real products:

- **Built-in UI suite** — accessible components (buttons, modals, tabs, sidebars, forms, file uploads, toasts, tree views, and more) that you can [theme and restyle](docs/04_components/styling-components.md) with CSS variables.
- **Server actions** — call server-side Python functions from the client without writing an API layer.
- **Reactive stores & databases** — global state stores and `SQLModel` model CRUD, reactive end-to-end.
- **Plugins** — package routes, components, and server actions into reusable `BasisPlugin`s.
- **CLI & HMR** — `basis init` to scaffold a project, `basis dev` for live component hot-swapping.

---

## Documentation

- **[Getting Started](docs/getting-started.md)** — install, your first app, and running it.
- **[Tutorial](docs/tutorial.md)** — a progressive path from hello world to full-stack apps.
- **[Concepts](docs/concepts.md)** — why Basis exists, the design philosophy, and comparisons.
- **[API Reference](docs/reference.md)** — the app, the reactivity engine, the UI catalogue, and tooling.
- **[Advanced Guide](docs/advanced.md)** — SSR, hydration, HMR, PYC mode, and plugins.
- **Start here:** [docs/index.md](docs/index.md)

---

## License

[MIT](LICENSE)
