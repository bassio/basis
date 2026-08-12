# Basis Framework Documentation

**Basis** is a reactive, full-stack Python framework for building interactive web applications without JavaScript. It uses server-side rendering for the initial page load and PyScript for client-side reactivity, driven by a fine-grained dependency graph that updates only the DOM nodes that actually changed.

```text
  Isomorphic Python Component
 ┌───────────────────────────┐
 │  class Counter(Component) │
 └─────────────┬─────────────┘
               │
      ┌────────┴────────┐
      ▼                 ▼
  [ SERVER ]        [ CLIENT ]
  FastAPI SSR       PyScript hydration
  (Fast, SEO)       (Instant UI updates)
```

---

## Table of Contents

### Chapter 1: Introduction
Background on why Basis exists and the design decisions that shaped it.

- **[Why Basis?](01_introduction/why-basis.md)** — The frontend problem for Python developers, and what Basis does differently.
- **[Core Philosophy](01_introduction/philosophy.md)** — The design principles: web standards, Python-first, buildless, component-driven, isomorphic.
- **[Non-Goals](01_introduction/non-goals.md)** — Deliberate trade-offs and boundaries of the framework.
- **[Comparison with Other Solutions](01_introduction/comparisons.md)** — How Basis compares to React, SolidJS, HTMX, and Django templates.

---

### Chapter 2: Quickstart
Get up and running with Basis using single-file apps.

- **[Hello World](02_quickstart/hello-world.md)** — Install Basis, write a reactive app in one file, and run it.

---

### Chapter 3: Server Architecture & Performance
Core server infrastructure, FastAPI application subclassing, and bytecode performance.

- **[The Basis App](03_server/basis-app.md)** — The `Basis` FastAPI subclass, application bootstrapping, component directory serving, and lifecycle.
- **[Server-Side Rendering (SSR)](03_server/ssr.md)** — The SSR lifecycle, `server_load` hooks, HTML generation, and handling isomorphic imports.
- **[PYC Bytecode Delivery Mode](03_server/pyc-mode.md)** — On-the-fly `.pyc` compilation for PyScript VFS, AST `@server_action` stripping, and performance optimization.

---

### Chapter 4: Components, UI Suite & Routing
Building UI components, using standard UI primitives, and handling client-side SPA routing.

- **[Defining Components](04_components/defining-components.md)** — Single-file and multi-file component layouts, reactive state, and file naming conventions.
- **[Parent & Child Composition](04_components/child-components.md)** — Custom element tags, passing attributes down the tree, and content projection with `<slot>`.
- **[Component Directories](04_components/components-directory.md)** — Mounting component directories and registering with PyScript module manifests.
- **[The Page Component](04_components/page-component.md)** — Customizing the HTML shell and initial store state injection.
- **[Built-in UI Suite](04_components/ui-components.md)** — Out-of-the-box accessible primitives (`Button`, `Badge`, `Toggle`, `Toast`, `Breadcrumbs`, `CommandPalette`, `AudioRecorder`).
- **[Forms & Validation](04_components/forms-and-validation.md)** — Automatic two-way bindings for `SQLModel` or dataclasses using `FormModelBinding`, event interception, and the `{model}_errors` dictionary.
- **[Client SPA Router](04_components/client-router.md)** — Client-side SPA routing with `Router` and `Route`.

---

### Chapter 5: Reactivity Engine & Stores
Deep dive into the template syntax, binding lifecycle, reactive DAG engine, and state stores.

- **[Braces Syntax](05_reactivity/braces-syntax.md)** — The `{expression}` engine, allowed built-ins, and `$store` and `#id` cross-boundary references.
- **[The Binding Engine](05_reactivity/bindings.md)** — Twelve binding classes and the binding lifecycle from SSR to hydration.
- **[DAG Reactivity Engine](05_reactivity/dag.md)** — Unified `ReactiveObject` graph, StateNodes, ComputedNodes, EffectNodes, and batching with `refrain()`.
- **[State Stores & Store Providers](05_reactivity/stores.md)** — Global pub/sub stores, `@computed` store properties, `StoreProvider`, and template subscriptions.
- **[SSR & Client Hydration](05_reactivity/ssr-hydration.md)** — Hydration IDs, server rendering, and matching DOM nodes during client hydration.

---

### Chapter 6: Server Actions & Database Integration
Executing server-side RPC functions and integrating database models.

- **[Server Actions](06_server_actions_and_db/server-actions.md)** — `@server_action` RPC execution, `/basis/api/action` handling, async client proxies, and state synchronization.
- **[Database & SQLModel Integration](06_server_actions_and_db/database.md)** — SQLite helper mixins (`basis.shared.db`, `DBAppMixin`) and reactive database updates.

---

### Chapter 7: Plugin System & Extensibility
Creating and consuming self-discoverable Basis plugins.

- **[Plugin System & Architecture](07_plugins/plugin-system.md)** — `BasisPlugin` contract, local `plugins/` directory auto-discovery, package entry points, route prefixing, and plugin-scoped server actions.

---

### Chapter 8: Appendix
Reference material for developer CLI commands and secondary features.

- **[CLI Tooling](08_appendix/cli.md)** — Scaffold projects with `basis init`, run dev servers with `basis dev`, and inspect plugins with `basis plugin list`.
