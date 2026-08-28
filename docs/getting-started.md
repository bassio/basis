# Getting Started with Basis

This guide will walk you through creating your first reactive application with Basis.

## Installation

Basis requires **Python 3.14+** and FastAPI.

```bash
pip install fastapi uvicorn basis-framework
```

*(Note: During beta, you can clone the repository and add it to your `PYTHONPATH`)*

## Scaffold a project with `basis init`

The fastest way to a running app shell is the interactive wizard:

```bash
basis init my-app
```

It asks a few questions (project name → workbench `app` or website `site` →
top-level chrome parts → extras), then generates a loadable project with an SSR
page at `/` and a small reactive demo. Run it non-interactively with `--yes`:

```bash
basis init my-app --yes
cd my-app && uv sync && basis dev    # live HMR, open http://127.0.0.1:8000
```

See [CLI Tooling](08_appendix/cli.md) for all flags (`--shell`, `--config`,
`--list`, per-part toggles, …).

## Your First App

Let's break down the minimalist "Hello World" example.

```python
from basis.shared.component import Basis, Component

# 1. Initialize the Basis application
app = Basis()

# 2. Define the page (root component)
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

### 1. The `Basis` App
The `Basis` class extends FastAPI. It handles serving your components, managing PyScript assets, and enabling Hot Module Replacement (HMR) during development.

### 2. The `@app.page` Decorator
This single decorator handles the entire application lifecycle:
- **On the Server**: It registers the component for Server-Side Rendering (SSR) and sets up a page route (default `/`).
- **In the Browser**: It automatically triggers the hydration process (`mount_app_ssr()`), waking up the static HTML without any extra code.

## Running the App

You can run your app using `uvicorn`:

```bash
uvicorn hello:app --reload
```

Open your browser to `http://localhost:8000` and start typing!
