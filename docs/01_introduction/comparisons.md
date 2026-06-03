# Comparison with Other Solutions

Basis occupies a specific niche in the web development landscape. This page places it in context against the tools Python developers most commonly reach for.

---

## Quick Reference

| | React | SolidJS | HTMX | Django Templates | Basis |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Language** | JavaScript / TS | JavaScript / TS | HTML + any backend | Python / HTML | Python (server & client) |
| **Build pipeline** | Required | Required | None | None | None |
| **Reactivity** | Virtual DOM diff | Fine-grained signals | Server-driven HTML swaps | None | Fine-grained DAG |
| **Client scripting** | JavaScript / TS | JavaScript / TS | None / Alpine / vanilla JS | Alpine / vanilla JS | Python via PyScript |
| **Isomorphism** | Via Next.js (complex) | Via SolidStart (complex) | No | No | Built-in |
| **State duplication** | High | High | Low (server-only) | Low (server-only) | None (shared state) |
| **Cognitive load** | High (hooks, closures) | Medium (signal lifecycle) | Low | Low | Low (plain attribute assignment) |

---

## Basis vs. React

React is the dominant frontend framework, and with good reason — it has a massive ecosystem and handles complex application UI well. The cost is real:

- **Build step** — React requires JSX, which means Babel or a similar transpiler, which means Vite or Webpack. Setting up, configuring, and upgrading this pipeline is overhead that never fully goes away.
- **Mental model** — Immutable state, virtual DOM diffing, hook dependency arrays, and the stale closure problem are real hazards that bite developers regularly, even experienced ones.

Basis requires no build step and uses standard HTML. Because the DAG engine updates only the exact DOM node that changed, there's no virtual DOM overhead and no hook lifecycle to reason about.

---

## Basis vs. SolidJS

SolidJS is the closest architectural relative to Basis in the JavaScript world. Both use fine-grained reactivity that binds directly to DOM nodes rather than diffing a virtual tree.

The difference: SolidJS still requires JavaScript/TypeScript and its own compiler tooling, and you still need a separate backend layer for anything involving a database. If you're a Python developer, none of your existing backend code crosses over.

Basis brings the same reactivity model to the Python ecosystem, running isomorphically on both server and client with no build step.

---

## Basis vs. HTMX

HTMX is a compelling option. It lets you add dynamic behavior to server-rendered HTML through attributes alone, with no JavaScript framework required. The philosophy aligns well with Basis — keep the server in control, avoid complex client-side state.

The limitation is that HTMX requires a server round-trip for every dynamic update. If a user types in a search field and you want to filter a list, that filter request goes to the server, the server renders the new HTML, and the response comes back over the network. For micro-interactions, this introduces perceptible latency.

Basis runs those updates directly in the browser, using the same Python code that ran on the server. The network is only involved when you explicitly call a `@server_action` — which is the right boundary for things like database writes.

---

## Basis vs. Django Templates / Jinja2

Server-side templates are simple, reliable, and fast to work with initially. The limitation appears as soon as the page needs to respond to user input without a full reload — at that point you're writing vanilla JavaScript or reaching for a second framework.

Basis provides the same initial server render, but then the page becomes fully reactive in the browser without any additional JavaScript. The same Python class that rendered the initial HTML handles all subsequent updates.
