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

## Documentation

### Chapter 1: Introduction

Background on why Basis exists and the design decisions that shaped it.

- **[Why Basis?](01_introduction/why-basis.md)** — The frontend problem for Python developers, and what Basis does differently.
- **[Core Philosophy](01_introduction/philosophy.md)** — The six design principles: web standards, Python-first, intuitive state, buildless, component-driven, isomorphic.
- **[Non-Goals](01_introduction/non-goals.md)** — Deliberate trade-offs and the boundaries of the framework.
- **[Comparison with Other Solutions](01_introduction/comparisons.md)** — How Basis compares to React, SolidJS, HTMX, and server-side Django templates.

---

### Chapter 2: Quickstart

- **[Hello World](02_quickstart/hello-world.md)** — Install Basis, write a reactive app in one file, and understand what happens on the server and in the browser.

---

### Chapter 3: Server

- **[The Basis App](03_server/basis-app.md)** — The `Basis` FastAPI subclass, its core APIs (`entrypoint`, `bootstrap`, `include_components_dir`, `include_ssr_page`), and the HMR development server.

---

### Chapter 4: Components

- **[Defining Components](04_components/defining-components.md)** — Single-file and multi-file component layouts, reactive state variables, and the file naming conventions.
- **[Parent & Child Composition](04_components/child-components.md)** — Custom element tags, passing reactive attributes down the tree, and content projection with `<slot>`.
- **[Component Directories](04_components/components-directory.md)** — Mounting a directory of components and how it integrates with the PyScript module manifest and HMR watcher.
- **[The Page Component](04_components/page-component.md)** — Customizing the HTML shell, the default template structure, and how initial store state is injected and read during hydration.

---

### Chapter 5: Reactivity

- **[Braces Syntax](05_reactivity/braces-syntax.md)** — The `{expression}` engine, allowed built-ins, sandboxed AST evaluation, and the `$store` and `#id` reference prefixes.
- **[The Binding Engine](05_reactivity/bindings.md)** — All twelve binding classes (Text, Attribute, If, Model, Loop, Slot, and more) and the binding lifecycle from SSR to hydration.
- **[DAG Reactivity Engine](05_reactivity/dag.md)** — StateNodes, ComputedNodes, EffectNodes, automatic and explicit dependency tracking, and batching mutations with `refrain()`.
- **[State Stores & Server Actions](05_reactivity/stores.md)** — Global pub/sub stores, template subscription syntax, and the `@server_action` RPC mechanism that synchronizes client and server state.
- **[SSR & Client Hydration](05_reactivity/ssr-hydration.md)** — How hydration IDs are stamped during server render and matched to live DOM nodes during client hydration.
