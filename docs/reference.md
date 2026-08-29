# API Reference

Lookup-oriented documentation for the framework's core APIs and catalogues. For the big picture, start with the [Tutorial](tutorial.md) or [Concepts](concepts.md) tracks.

---

## Application

- **[The Basis App](03_server/basis-app.md)** — The `Basis` FastAPI subclass: initialization parameters, `bootstrap()`, `@app.page`, `@app.serve`, and the core framework APIs.
- **[Importing Components & the Isomorphism Principle](04_components/importing-components.md)** — The VFS == filesystem import invariant, and conventional `components/` / `stores/` / `plugins/` auto-discovery.

## Reactivity Engine

- **[The Binding Engine](05_reactivity/bindings.md)** — The specialized binding classes and the binding lifecycle from SSR to hydration.
- **[Loop Bindings](05_reactivity/loop-bindings.md)** — The loop reconciliation pipeline: keyed vs unkeyed keys, thin `LoopItem`s, per-item scope, and nested / custom-element loops.
- **[DAG Reactivity Engine](05_reactivity/dag.md)** — The unified `ReactiveObject` graph, StateNodes, ComputedNodes, EffectNodes, and batching with `refrain()`.

## UI Component Catalogue

- **[Built-in UI Suite](04_components/ui-components.md)** — Out-of-the-box accessible primitives (`Button`, `Badge`, `Toggle`, `Toast`, `Breadcrumbs`, `CommandPalette`, `AudioRecorder`, and more).

## Tooling & Repository

- **[CLI Tooling](08_appendix/cli.md)** — Scaffold projects with `basis init`, run dev servers with `basis dev`, and inspect plugins with `basis plugin list`.
- **[Codebase Structure](08_appendix/codebase-structure.md)** — Core directories, modules, and architecture layout of the Basis repository.

## JavaScript Interop

- **[Wrapping JS Libraries with `@js_component`](04_components/js-components.md)** — The `@js_component` decorator, `JsComponent` base, the lazy/preloaded module loader, and the proxied bridge.

---

*Part of the **API Reference** track. See also [Tutorial](tutorial.md), [Concepts](concepts.md), and [Advanced Guide](advanced.md).*
