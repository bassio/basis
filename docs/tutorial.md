# Tutorial — User Guide

Learn Basis by building. This track walks you from an empty directory to a reactive, full-stack Python application — one concept at a time, in the order you should read them.

> **How to read this track:** each guide builds on the previous one. When you finish, hop over to the [Advanced Guide](advanced.md) for server-side deep dives, or use the [API Reference](reference.md) for lookups.

---

## 1. Get Started

- **[Getting Started](getting-started.md)** — Install Basis and write your first reactive application.
- **[Hello World](02_quickstart/hello-world.md)** — A complete walkthrough of the minimal hello-world app, from server render to client hydration.
- **Runnable example**: [`hello.py`](hello.py) — the hello-world app as a standalone file you can run with `uvicorn`.

## 2. Components

- **[Defining Components](04_components/defining-components.md)** — Single-file and multi-file component layouts, reactive state, and file naming conventions.
- **[Extending & Customizing Components](04_components/extending-components.md)** — The web-component mental model, and the code-side ways to extend a component: attributes (props), Python subclassing, and building your own.
- **[Styling Components](04_components/styling-components.md)** — Theme and restyle any component's look: CSS design tokens, plain CSS overrides, and inline host styling — no Python required.
- **[Parent & Child Composition](04_components/child-components.md)** — Custom element tags, passing attributes down the tree, and content projection with `<slot>`.
- **[Component Directories](04_components/components-directory.md)** — Mounting component directories and registering them with the PyScript module manifest.
- **[The Page Component](04_components/page-component.md)** — Customizing the HTML shell and initial store-state injection.
- **[Forms & Validation](04_components/forms-and-validation.md)** — Automatic two-way bindings for `SQLModel` or dataclasses using `FormModelBinding`, event interception, and the `{model}_errors` dictionary.
- **[Client SPA Router](04_components/client-router.md)** — Client-side SPA routing with `Router` and `Route`.

## 3. Reactivity & State

- **[Reactivity in Basis](reactivity.md)** — The mental model: state nodes, computed properties, and two-way binding.
- **[The Braces Syntax](05_reactivity/braces-syntax.md)** — The `{expression}` engine, allowed built-ins, and `$store` / `#id` cross-boundary references.
- **[State Stores & Store Providers](05_reactivity/stores.md)** — Global pub/sub stores, `@computed` store properties, `StoreProvider`, and template subscriptions.

## 4. Server & Data

- **[Server Actions](06_server_actions_and_db/server-actions.md)** — Calling server-side RPC functions with `@server_action`.
- **[Database & SQLModel Integration](06_server_actions_and_db/database.md)** — Isomorphic models, `DBAppMixin`, and reactive model CRUD.

---

*Part of the **Tutorial** track. See also [Concepts](concepts.md), [API Reference](reference.md), and [Advanced Guide](advanced.md).*
