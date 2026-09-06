# Advanced Guide

Deep dives into how Basis works under the hood, and how to get the most out of the server side. These assume you have completed the [Tutorial](tutorial.md) track.

---

## Server-Side Rendering

- **[Server-Side Rendering (SSR)](03_server/ssr.md)** — The SSR lifecycle, `server_load` hooks, HTML generation, and handling isomorphic imports.
- **[SSR & Client Hydration](05_reactivity/ssr-hydration.md)** — The single canonical hydration model, the canonical tree, hydration markers and text ordinals, the matching pipeline, diagnostics, and the fallback re-render.
- **[Importing Components & the Isomorphism Principle](04_components/importing-components.md)** — Why every import name is identical on the server, in the client VFS, and in your IDE, and how conventional directories are auto-discovered without breaking that invariant.

## The Component Lifecycle

- **[The Component Lifecycle](04_components/component-lifecycle.md)** — The three hooks (`on_mounted` / `on_hydrated` / `on_unmounted`), the one unmount verb (`destroy()`), hide vs unmount, the `basis:connected` / `basis:disconnected` DOM signals, JS-component boot mapping, and plugin ↔ component parity.

## Templates & Scoping

- **[Scoping in Loops](04_components/loop-scope.md)** — Who owns the loop body? The parent-scope-plus-loop-variable mental model, the verified behaviour for plain-element vs custom-element loop children, event ownership, and the silent-staleness footgun.
- **[Loop Bindings](05_reactivity/loop-bindings.md)** — How `for`/`in` loops reconcile lists in place: keyed vs unkeyed keys, the resolve → reconcile → apply pipeline, nested loops, and SSR re-pointing.

## Developer Experience

- **[Hot Module Replacement (HMR)](03_server/hmr.md)** — Live hot-swap of `.py` / `.html` / `.css` component files during development, the `/ws/hmr` WebSocket, module re-import, and instance hot-swap internals.

## Performance

- **[PYC Bytecode Delivery Mode](03_server/pyc-mode.md)** — On-the-fly `.pyc` compilation for the PyScript VFS, AST `@server_action` stripping, and performance optimization.

## Extensibility

- **[Plugin System & Architecture](07_plugins/plugin-system.md)** — The `BasisPlugin` contract, local `plugins/` directory auto-discovery, package entry points, route prefixing, and plugin-scoped server actions.

## JavaScript Interop

- **[Wrapping JS Libraries with `@js_component`](04_components/js-components.md)** — The escape hatch: wrap any JS library (CodeMirror, charts, maps) as a reactive Basis component with a Python API — vendored JS, SSR-safe placeholders, and per-page module preloading.

---

*Part of the **Advanced Guide** track. See also [Tutorial](tutorial.md), [Concepts](concepts.md), and [API Reference](reference.md).*
