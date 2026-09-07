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

Basis has a single hydration model — **canonical** — used for both rendering and hydration:

- The server tree **preserves text/comments exactly** like the browser DOM (no whitespace stripping).
- IDs are derived by **one single-source algorithm** shared between server and client.
- Text bindings are matched by deterministic **text ordinals** (`data-hydration-text`).

The client needs no configuration: canonical pages carry a `data-hydration-text` marker and match by ordinal.

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

Written on every element that participates in a binding (a `{expression}` text node, an attribute, an event, an `if`, a child component, a loop). The value is the node's path in the element tree, e.g. `b:0:1:2`.

```html
<span data-hydration-id="b:0:1">Score: 0</span>
```

### `data-component-hydration-id`

Written on the root element of each component instance, marking component boundaries.

```html
<user-card data-component-hydration-id="b:0:2">...</user-card>
```

### `data-hydration-text`

Written on the **parent** of reactive text nodes: a comma-separated list of the *ordinals* of its reactive text children (0-based, among the parent's normalized children). Because text nodes cannot carry attributes, this marker is how the client locates them deterministically.

```html
<!-- "Score: 0" is the 0th reactive text child of the span -->
<span data-hydration-id="b:0:1" data-hydration-text="0">Score: 0</span>
```

---

## The path algorithm

Each countable node is identified by a path string `b:` + one segment per depth, where the segment is the node's index among the parent's normalized children, in document order. The root is `b:0`.

```html
<div>                     b:0
  <span>Score: 0</span>   b:0:0   (element, index 0)
  <p>{body}</p>           b:0:1   (element, index 1)
</div>
```

There is exactly **one** address *algorithm*. A page carries **two disjoint regions** (HYDRATION-WHOLEPAGE.md), each a named root so the client and server agree on where every node lives:

- `<head>` content is numbered `h:` (root `h:0` is the `<head>` element).
- `<body>` content is numbered `b:` (root `b:0` is the `<body>` element).

The examples above use `b:` — the default prefix `iter_tree_paths` gives a standalone (non-Page) subtree walk, which is the same namespace the page's `<body>` region uses.

The client runs the *same* `iter_tree_paths` algorithm over its own staged template tree and stamps `data-hydration-id` on it too — so a client node at canonical path `P` hydrates the SSR node at canonical path `P`.

### Two regions: the Page's `<head>` and `<body>` are one owned document

The Page shell — the whole `<html>` document — is itself a component whose template carries bindings in BOTH regions (`<title>{title}</title>`, the viewport / `basis-render-mode` meta, the `<script id="basis-initial-state">` body in `<head>`; the body region holds the root component). Whole-page hydration (HYDRATION-WHOLEPAGE.md No.2 / §4.1 P4) makes both regions reactive surfaces so those bindings are kept alive instead of server-frozen:

- The **`<head>` region** (`h:`) covers the Page's own head bindings — stamped by `shared/hydration.apply_hydration_to_page` inside `Page._render` (SSR only) and full-stamped client-side from the staged template.
- The **`<body>` region** (`b:`) is rooted at the `<body>` element. The root component mounts as a **declarative nested child** of the Page — a `ChildBinding` under a hyphenated host tag (`Page._declarative_root_tag()` + `Page.mount_root_app()`). The host tag is the root's declared `__tag__`, or one kebab-derived from the class name, so **every** page root (real `Page` subclass or a synthesized `@app.page` shell) mounts declaratively — there is no imperative engine mount left (§4.1 P5). The host is the body's first countable child (`b:0:0`); the app's own root sits inside it (`b:0:0:0`…).
- Page chrome is **in-tree** (HYDRATION-WHOLEPAGE.md §4.1 P3): the per-component style loop, the viewport `<style id="basis-viewport">` (a `text-content` node), the dev-mode meta and the user stylesheet `<link>`s (at a body comment anchor) all live as owned nodes/comment anchors of the `Page` template — there are no post-serialization appends.
- On the client a Page subclass hydrates the WHOLE served document in one pass (`Page.mount_document` → `_hydrate_page_document_ssr`): it stages the Page in a detached fragment (a browser `<template>` parse would drop the `<html>/<head>/<body>` wrappers, so the client rebuilds the document structure programmatically via `DOMParser`), mounts the root declaratively into the staged `<body>`, full-stamps the staged `<head>` (`h:`) and `<body>` (`b:`), then re-points the Page's bindings AND every app component at the live document against ONE map (`document.head` under `h:` + `document.body` under `b:`). Nothing is ever inserted into the live document — the SSR tree is adopted in place.
- CSR keeps the served `<head>` static (no FOUC / double head), half-hydrates it (`_hydrate_page_head` — re-point never writes, so title/meta bindings become live), and client-renders the body through the same declarative root mount (`Page.mount_document`).

Every page boots through ONE client driver — `basis.client.entrypoint`: the manifest lists real `Page` subclasses AND synthesized `@app.page` shells (the latter under their root component name); the driver imports each module and calls the single `Page.mount_document` classmethod, which reads the served `basis-render-mode` meta and dispatches SSR (hydrate in place) vs CSR (render the body). Client `@app.page`/`@app.serve` decoration only annotates the decorated root component with its shell recipe (`_synthesized_page_args`, in the class's own `__dict__` so it is never inherited) — mounting is never a decorator side effect. The old body-only `mount_app_ssr`/`r:` path is gone (§4.1 P5).

---

## The hydration process (client)

1. **Read initial state** — `Store` constructors read `<script id="basis-initial-state">` and pre-populate from the server's serialized state.

2. **Stage a client mount** — `Page.mount_document()` (SSR mode) mounts the whole Page (with the root component as a declarative body child) into a *detached* staging tree, then stamps `data-hydration-id` on every countable node of both regions (`h:`/`b:`) using the *same* `iter_tree_paths` algorithm the server uses. This staging tree is used only to discover bindings and paths; it is discarded once hydration completes.

3. **Match components** — For each component instance, the client finds the corresponding SSR subtree by matching the component root's `data-hydration-id` against the SSR tree's `data-hydration-id`s.

4. **Match bindings** (`initialize_ssr`) — Before matching, the client builds **one** SSR lookup map, `{path: node}`, from every `data-hydration-id` in the tree (`build_hydration_map`). Each binding is then repointed from its staging node to the matching SSR node with two O(1) lookups:
   - **Element bindings** (events, attributes, `if`, child components, loops) are found by reading the staging node's `data-hydration-id` — which *is* the canonical path — and looking it up in the SSR map. The path is read from the stamped DOM attribute (not from proxy identity, so it is safe across Pyodide's `JsProxy` wrappers), and it is the same value on both sides by construction. Loops are the one structural special case: item wrappers and loop-body bindings are re-pointed by `data-item-key` + *relative* canonical paths (`shared/hydration.repoint_loop_to_ssr`), which also handles nested loops and custom-element loop children.
   - **Text bindings** are matched by **ordinal**: the client computes the text node's ordinal among its parent's normalized children, reads the SSR parent's `data-hydration-text`, and adopts the SSR text node at that ordinal. Whitespace and comments around the binding cannot shift it.
   - Bindings that cannot be matched are recorded in the hydration report (below) rather than silently left stale.

5. **DAG activation** — Once every binding points at a live SSR node, state mutations propagate through the `DependencyGraph` and update only the affected nodes.

The result: the SSR DOM is reused in place — no flash of content, no layout shift — and the existing text nodes, inputs, and attributes become live.

---

## Diagnostics

Hydration is fail-loud. On the client, the whole-document hydration driver builds a single `HydrationReport` that records:

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

- Hydration is always **canonical** (preserved-text tree, text ordinals, `data-hydration-text`).
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
