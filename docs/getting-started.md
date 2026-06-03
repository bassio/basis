# Getting Started with Basis

This guide will walk you through creating your first reactive application with Basis.

## Installation

Basis requires Python 3.10+ and FastAPI.

```bash
pip install fastapi uvicorn basis-framework
```

*(Note: During beta, you can clone the repository and add it to your `PYTHONPATH`)*

## Your First App

Let's break down the minimalist "Hello World" example.

```python
from basis.shared.component import Basis, Component

# 1. Initialize the Basis application
app = Basis()

# 2. Define the application entrypoint
@app.entrypoint
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

### 2. The `@app.entrypoint` Decorator
This single decorator handles the entire application lifecycle:
- **On the Server**: It registers the component for Server-Side Rendering (SSR) and sets up the root route.
- **In the Browser**: It automatically triggers the hydration process (`mount_app_ssr()`), waking up the static HTML without any extra code.

## Running the App

You can run your app using `uvicorn`:

```bash
uvicorn hello:app --reload
```

Open your browser to `http://localhost:8000` and start typing!
