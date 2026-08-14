# Advanced Guide

Deep dives into how Basis works under the hood, and how to get the most out of the server side. These assume you have completed the [Tutorial](tutorial.md) track.

---

## Server-Side Rendering

- **[Server-Side Rendering (SSR)](03_server/ssr.md)** — The SSR lifecycle, `server_load` hooks, HTML generation, and handling isomorphic imports.
- **[SSR & Client Hydration](05_reactivity/ssr-hydration.md)** — Hydration IDs, server rendering, and matching DOM nodes during client hydration.

## Developer Experience

- **[Hot Module Replacement (HMR)](03_server/hmr.md)** — Live hot-swap of `.py` / `.html` / `.css` component files during development, the `/ws/hmr` WebSocket, module re-import, and instance hot-swap internals.

## Performance

- **[PYC Bytecode Delivery Mode](03_server/pyc-mode.md)** — On-the-fly `.pyc` compilation for the PyScript VFS, AST `@server_action` stripping, and performance optimization.

## Extensibility

- **[Plugin System & Architecture](07_plugins/plugin-system.md)** — The `BasisPlugin` contract, local `plugins/` directory auto-discovery, package entry points, route prefixing, and plugin-scoped server actions.

---

*Part of the **Advanced Guide** track. See also [Tutorial](tutorial.md), [Concepts](concepts.md), and [API Reference](reference.md).*
