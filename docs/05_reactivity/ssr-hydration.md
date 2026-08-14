# SSR & Client Hydration

Basis splits the page lifecycle into two phases: a server render that produces complete static HTML, and a client hydration step that attaches reactive bindings to that existing DOM **without rebuilding it**. This chapter explains how the two halves agree on *which* nodes are reactive and *where* they live.

---

## The two phases

```text
1. SERVER-SIDE RENDERING (FastAPI)
   ├── Executes server_load() coroutines on all components
   ├── Renders a complete HTML layout in Python
   ├── Stamps reactive elements with hydration markers
   └── Delivers a fully-formed HTML page to the browser

2. CLIENT-SIDE HYDRATION (PyScript / Pyodide)
   ├── Boots the Pyodide WebAssembly runtime
   ├── Reads the initial store state from the embedded JSON block
   ├── Mounts the app into a detached staging shadow root
   ├── Assigns client-side IDs with the same path algorithm
   ├── Matches every binding to its server-rendered node
   └── Activates the DAG — the page is now fully reactive
```

---

## One canonical world

Basis has a single hydration model — **canonical** — used for both rendering and hydration. There is no alternate "legacy" mode anymore:

- The server tree **preserves text/comments exactly** like the browser DOM (no whitespace stripping).
- IDs are derived by **one single-source algorithm** shared between server and client.
- Text bindings are matched by deterministic **text ordinals** (`data-basis-text`).

The former `BASIS_HYDRATION` switch (and the legacy stripped-text tree with positional matching) has been removed from the codebase. The client needs no configuration: canonical pages carry a `data-basis-text` marker and match by ordinal.

---

## The canonical tree — structural parity

For hydration to be deterministic, the server's model of the DOM and the browser's DOM must be *structurally identical*. The canonical server tree-builder guarantees this:

- **Text is preserved exactly** as authored — no whitespace stripping.
- **Contiguous text is merged into one node per text run**, matching how the browser coalesces text nodes.
- **Whitespace-only text nodes are kept** in the tree (they are excluded from ID numbering by policy, not by deletion).
- **Comments are kept** as real nodes, so they split text runs exactly like the browser.

Because both trees are built from the same template with the same rules, a node in the server tree and the same node parsed by the browser get the same path — that is the root of determinism.

---

## The node policy (what counts toward an ID)

Hydration paths are computed over **normalized children**:

- **Element nodes always count.**
- **Text nodes count** unless they are whitespace-only — except *reactive* text nodes, which count even when their current value is empty (a cleared form-error binding still has non-empty template text).
- **Comment nodes never count.**

Whitespace and comments are preserved in the DOM but ignored for numbering, so indentation or a comment around a binding can never shift a sibling's ID.

This policy is the single source of truth in `basis/shared/hydration.py`. The module is duck-typed so the exact same functions run over the server's `Element` model *and* the browser DOM (Pyodide) — there is one algorithm, not two.

---

## Hydration markers

The server walks the component tree and stamps attributes that act as the bridge to the client:

### `data-hydration-id`

Written on every element that participates in a binding (a `{expression}` text node, an attribute, an event, an `if`, a child component, a loop). The value is the node's path in the element tree, e.g. `r:0:1:2`.

```html
<span data-hydration-id="r:0:1">Score: 0</span>
```

### `data-component-hydration-id`

Written on the root element of each component instance, marking component boundaries.

```html
<user-card data-component-hydration-id="r:0:2">...</user-card>
```

### `data-basis-text`

Written on the **parent** of reactive text nodes: a comma-separated list of the *ordinals* of its reactive text children (0-based, among the parent's normalized children). Because text nodes cannot carry attributes, this marker is how the client locates them deterministically.

```html
<!-- "Score: 0" is the 0th reactive text child of the span -->
<span data-hydration-id="r:0:1" data-basis-text="0">Score: 0</span>
```

---

## The path algorithm

Each countable node is identified by a path string `r:` + one segment per depth, where the segment is the node's index among the parent's normalized children, in document order. The root is `r:0`.

```html
<div>                     r:0
  <span>Score: 0</span>   r:0:0   (element, index 0)
  <p>{body}</p>           r:0:1   (element, index 1)
</div>
```

Both sides compute this identically from the shared policy, so a client-side `data-client-id` and a server-side `data-hydration-id` are the same value for the same logical node.

---

## The hydration process (client)

1. **Read initial state** — `Store` constructors read `<script id="basis-initial-state">` and pre-populate from the server's serialized state.

2. **Stage a client mount** — `mount_app_ssr()` mounts the whole app into a *detached* shadow root, then `_set_nodes_with_client_ids()` walks it with the same canonical policy and stamps `data-client-id` on every countable node. This staging tree is used only to discover bindings and paths; it is discarded once hydration completes.

3. **Match components** — For each component instance, the client finds the corresponding SSR subtree by matching the component root's `data-client-id` against the SSR `data-hydration-id`s.

4. **Match bindings** (`initialize_ssr`) — Each binding is repointed from its staging node to the matching SSR node:
   - **Element bindings** (events, attributes, `if`, child components, loops) are found by path: `ssr_root.querySelector('[data-hydration-id="<path>"]')`.
   - **Text bindings** are matched by **ordinal**: the client computes the text node's ordinal among its parent's normalized children, reads the SSR parent's `data-basis-text`, and adopts the SSR text node at that ordinal. Whitespace and comments around the binding cannot shift it.
   - Bindings that cannot be matched are recorded in the hydration report (below) rather than silently left stale.

5. **DAG activation** — Once every binding points at a live SSR node, state mutations propagate through the `DependencyGraph` and update only the affected nodes.

The result: the SSR DOM is reused in place — no flash of content, no layout shift — and the existing text nodes, inputs, and attributes become live.

---

## Diagnostics

Hydration is fail-loud. On the client, `mount_app_ssr()` builds a `HydrationReport` that records:

- **Unmatched bindings** — which binding type (e.g. `TextBinding`, `EventBinding`, `IfBinding`) and which client path failed to match.
- **Unhydrated components** — component roots present on the client but absent from the SSR tree (unless they are legitimately hidden by an `if`).

The report is surfaced three ways:

- **`window.__basisHydrationReport`** — the machine-readable report (also mirrored as a `data-__basisHydrationReport` JSON attribute on `<html>`).
- **`basis-hydration-mismatch`** — a `CustomEvent` dispatched on `document` with the report as `detail`, for tools and tests.
- **`console.warn` + `console.table`** — a loud, human-readable summary in the devtools console.

---

## Fallback re-render

When a **genuine component-root mismatch** occurs (a component the client mounted is not present in the SSR tree and is not hidden by an `if`), Basis does not leave a dead, non-reactive subtree. With the fallback enabled (default), it:

1. Replaces the SSR content with the already-mounted **client render**, moved out of the staging shadow root together with its scoped styles.
2. Records `fallback: "whole-app client re-render"` in the report and warns loudly.

The page stays fully reactive even though that load sacrificed SSR. Because the fallback only fires on genuine mismatches, healthy pages are unaffected.

- Disable with `BASIS_HYDRATION_FALLBACK=0` (or `set_hydration_fallback(False)` in code).

---

## Compatibility

- Hydration is always **canonical** (preserved-text tree, text ordinals, `data-basis-text`). There is no legacy mode or rollback switch.
- The client needs no configuration — every SSR page carries the canonical markers.
- The fallback re-render remains available and default-on; disable with `BASIS_HYDRATION_FALLBACK=0` (or `set_hydration_fallback(False)` in code).

---

## Under the hood

The whole contract lives in `basis/shared/hydration.py`:

- node policy (`normalized_children`, `is_whitespace_text`, …),
- the path algorithm (`iter_tree_paths`),
- marker stamping (`apply_hydration_markers`, `stamp_text_ordinals`),
- the diagnostics report shape (`HydrationReport`),
- the fallback toggle (`hydration_fallback_enabled`).

The same functions run server-side (over `basis/shared/element.py`) and client-side (over the browser DOM in Pyodide), which is what lets server and client agree without a second, hand-written algorithm.
