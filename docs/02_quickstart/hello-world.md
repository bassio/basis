# Quickstart: Hello World

This guide walks through setting up a minimal Basis app. By the end you'll have a live reactive page — an input field that updates a heading in real time — running with a single Python file and no JavaScript.

---

## 1. Installation

Basis requires Python 3.10 or higher. Install it alongside FastAPI and Uvicorn:

```bash
pip install fastapi uvicorn basis-framework
```

> [!NOTE]
> If you're using `uv` for environment management, `uv add fastapi uvicorn basis-framework` works the same way.

---

## 2. Write the app

Create `app.py`:

```python
from basis.shared.component import Basis, Component

app = Basis()

@app.entrypoint
class HelloBasis(Component):
    """
    <div style="font-family: sans-serif; max-width: 400px; margin: 40px auto; padding: 24px; border-radius: 12px; border: 1px solid #e2e8f0;">
        <h2 style="margin-top: 0;">Interactive Hello</h2>
        <input bind="{name}" placeholder="Type your name..." style="width: 100%; padding: 8px 12px; border-radius: 6px; border: 1px solid #cbd5e1; font-size: 16px; box-sizing: border-box; margin-bottom: 16px;" />
        <h1 style="color: #6366f1; margin: 0;">Hello, {name}!</h1>
    </div>
    """
    name = "World"
```

Three things are happening here:

- `app = Basis()` creates the application, which is a FastAPI subclass.
- `@app.entrypoint` registers `HelloBasis` as the root component, sets up the SSR route at `/`, and configures PyScript to load the component in the browser.
- `name = "World"` is a reactive state variable. The `bind="{name}"` attribute on the input creates a two-way binding: typing updates `self.name`, and the `{name}` in the heading reflects the change immediately.

---

## 3. Run it

You can run your app using the **Basis CLI**:

```bash
basis dev
```

Or directly via Uvicorn:

```bash
uvicorn app:app --reload
```

Open [http://localhost:8000](http://localhost:8000) and type in the input box — the heading updates as you type.

---

## 4. What's happening

### Server-side render

When the browser first requests `/`:

1. FastAPI calls the Basis SSR handler registered by `@app.entrypoint`.
2. Basis parses the component's HTML template and renders it with the initial state (`name = "World"`).
3. The response is a complete HTML document including rendered markup, PyScript configuration, and a JSON block containing initial state.

Because the page is fully rendered server-side, search engines see complete content — no blank screen waiting for client scripts.

### Client hydration

Once the HTML is loaded in the browser:

1. PyScript boots the Pyodide WebAssembly runtime in the background.
2. Basis runs the `HelloBasis` class in the browser and scans the pre-rendered HTML for hydration markers.
3. Rather than re-creating DOM nodes, it attaches reactive bindings to existing ones.
4. The `bind="{name}"` attribute becomes a two-way `ModelBinding`: input events update `self.name`, and the DAG engine updates the `{name}` text node in the heading.

All DOM updates happen in-place without layout shifts or content flashes.
