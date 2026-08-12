# Basis: Full-Stack Reactive Python Framework

Basis is a full-stack web framework for building interactive, stateful web applications entirely in Python. It runs FastAPI on the server for initial Server-Side Rendering (SSR) and PyScript in the browser for Client-Side Hydration (CSH), providing a reactive, component-based developer experience with no JavaScript.

---

## Quickstart

### 1. Installation
Install the framework alongside FastAPI and Uvicorn:
```bash
pip install fastapi uvicorn basis-framework
```

### 2. Scaffold or Create an App

#### Using the Basis CLI:
```bash
basis init my-app
cd my-app
basis dev
```

#### Or write a minimal `app.py`:
```python
from basis.shared.component import Basis, Component

app = Basis()

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

### 3. Run the Development Server

Run with the Basis CLI:
```bash
basis dev
```
or directly via Uvicorn:
```bash
uvicorn app:app --reload
```
Navigate to `http://localhost:8000` to interact with the application.

---

## Core Philosophy

- **Python Everywhere** — Write backend services, business logic, component templates, and client-side reactive state in pure Python.
- **Native Custom Elements** — Components map to standard hyphenated HTML custom tags, keeping styling and markup aligned with web standards.
- **Fine-Grained Reactivity** — No Virtual DOM. Basis uses a Directed Acyclic Graph (DAG) to track dependencies and update only targeted DOM nodes when state changes.
- **Isomorphic Hydration** — Server renders fully-formed, SEO-friendly HTML, which the client hydrates in-place without flashes of unstyled content or layout shifts.
- **Extensibility & Modularity** — Drop-in plugins, CLI tooling, and built-in UI components provide professional scaffolding out-of-the-box.

---

## Documentation

For comprehensive guides, architecture diagrams, and detailed API breakdowns, browse the files in the **`docs/`** directory starting with **[docs/index.md](docs/index.md)**.
