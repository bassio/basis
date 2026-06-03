# SSR & Client Hydration

Basis splits the page lifecycle into two distinct phases: a server render that produces complete static HTML, followed by a client hydration step that attaches reactive bindings to the existing DOM without rebuilding it.

---

## The two phases

```text
1. SERVER-SIDE RENDERING (FastAPI)
   ├── Executes server_load() coroutines on all components
   ├── Renders complete HTML layout in Python
   ├── Stamps reactive elements with hydration IDs
   └── Delivers a fully-formed HTML page to the browser

2. CLIENT-SIDE HYDRATION (PyScript / Pyodide)
   ├── Boots the Pyodide WebAssembly runtime
   ├── Reads the initial store state from the embedded JSON block
   ├── Scans the pre-rendered DOM for hydration ID markers
   ├── Attaches Binding instances to matched DOM nodes
   └── Activates the DAG — the page is now fully reactive
```

---

## Hydration markers

During the server render, Basis walks the component tree and stamps two kinds of attributes onto reactive elements:

### `data-hydration-id`

Written on elements that contain reactive bindings — anything referencing a `{expression}`. The value is a path string encoding the node's position in the element tree (e.g. `r:0:1:2`).

```html
<!-- Server-rendered output -->
<span data-hydration-id="r:0:1">Score: 0</span>
```

### `data-component-hydration-id`

Written on the root element of each component instance, marking the boundary between nested component trees.

```html
<!-- Server-rendered output -->
<user-card data-component-hydration-id="r:0:2"></user-card>
```

These attributes are the bridge between the static server output and the client's reactive binding instances.

---

## The hydration process

Once the page lands in the browser and PyScript has initialized:

**Step 1: Read initial state** — The client-side `Store` constructors read the `<script id="basis-initial-state">` JSON block and pre-populate their values from the server's serialized state. By the time bindings are activated, stores already hold the correct data.

**Step 2: Node matching** — The client component initializer walks the pre-rendered DOM in sync with the compiled `BindingBlueprint` index. For each blueprint, it looks up the matching `data-hydration-id` in the live DOM and attaches the corresponding `Binding` instance to that node. No new elements are created.

**Step 3: DAG activation** — Once all bindings are attached to live DOM nodes, the `DependencyGraph` is activated. From this point on, any state mutation propagates through the graph and updates only the affected nodes.

The result is that the page's DOM is never rebuilt during hydration. The browser's existing text nodes, input elements, and attribute values are reused in place, preserving scroll position, focus state, and any CSS transitions that were already running.

> [!NOTE]
> Because hydration reuses existing DOM nodes rather than creating new ones, there is no flash of blank content and no layout shift — the page looks identical before and after PyScript finishes loading.
