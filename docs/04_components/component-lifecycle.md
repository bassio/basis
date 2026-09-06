# The Component Lifecycle

Basis components have a small, deliberate lifecycle: **three user hooks** (`on_mounted`, `on_hydrated`, `on_unmounted`), **one unmount verb** (`destroy()`), and a pair of **DOM signals** (`basis:connected` / `basis:disconnected`) that are *not* lifecycle hooks. This page is the mental model.

The short version:

- A component is **mounted** once (template bound, effects live) → `on_mounted`.
- On an SSR page the client **hydrates** it (bindings re-pointed at the live tree) → `on_hydrated`.
- A component is **unmounted** only when someone calls `destroy()` → `on_unmounted`.
- Hiding something is **not** unmounting it. Removing it from the DOM is not unmounting it either. Only `destroy()` unmounts.

```python
class Player(Component):
    """<div class="player">…</div>"""

    def on_mounted(self):
        # Template bound + initial effects have run. Boot imperative things —
        # e.g. start polling, a socket, or a JS widget you created yourself.
        self._poll = start_polling(self)   # an app helper you wrote

    def on_unmounted(self):
        # destroy() ran and the framework state is clean. Release what you own.
        stop_polling(self._poll)           # your app helper
```

---

## The three lifecycle hooks

| Hook | When it runs | Notes |
| :--- | :--- | :--- |
| `on_mounted()` | Once, at the **end of mount** — after the template is bound, bindings are live and the initial DAG effects have run. | Runs on **both** server and client. Server: the SSR render of a page. Client: a CSR mount, *and* the staging mount inside the detached shadow during SSR hydration (see the hydration caveat below). |
| `on_hydrated()` | **Client only** — at the end of the hydration pass, after every binding has been re-pointed at the **live SSR tree**. | Never runs on the server, and never on a plain CSR page (there is no SSR tree to adopt). |
| `on_unmounted()` | Once, at the end of `destroy()` — after bindings are detached, the reactive scope is destroyed, identities are deregistered and the DOM element is removed. | The place to close sockets, stop timers, release `ffi` proxies, persist state. Never fires on an `if`-hide. |

The three hooks are *disjoint entry points*: mounting never calls `on_hydrated`, and hydration never calls `on_mounted` again.

> [!IMPORTANT]
> **Hydration staging caveat.** During client SSR hydration the whole app is first mounted into a *detached* shadow before bindings are re-pointed at the live page. So `on_mounted` can fire while the component's element is **not yet in the document**. Dynamic mounters that must act on the visible DOM (the `<ui-region>` primitive, `@js_component`) detect this and defer — see [JS component boot mapping](#js-components-when-do-i-boot) below. If your `on_mounted` must touch the live DOM, prefer `on_hydrated` on SSR pages, or guard on whether the element is connected.

---

## `destroy()` — the one unmount verb

Unmounting is explicit and framework-driven. You call `instance.destroy()` (or it is called for you by a container — a region removing a contribution, an owner tearing down its subtree). `destroy()` is **idempotent** and runs in a fixed order:

1. mark the instance destroyed (the idempotency guard);
2. tear down JS subresources (`_teardown_js` — a no-op for plain components);
3. detach every binding and destroy the root reactive scope (`_teardown_bindings`) — which **recurses**: mounted children are unmounted through their `ChildBinding`s, custom-element loop children through their loop bindings, and contributions through a region's `on_unmounted`;
4. deregister `#id` / `__component_id__` identities from the instance registry;
5. drain pending-subscription queues that reference this instance;
6. remove the root element from the DOM;
7. clear subscriptions and drop the instance from the live set;
8. call `on_unmounted()` (after the framework state is clean).

```python
player.destroy()          # unmount player and its whole subtree
player.destroy()          # safe — a no-op
```

Because `destroy()` walks the *binding tree*, it unmounts the whole subtree it owns — including descendants that are currently **hidden by an `if`** (they are part of its subtree) — but never a sibling that merely shares an ancestor.

> [!NOTE]
> **Server side.** `destroy()` is valid on the server too, where it cleans registries/state; SSR render trees are per-request and garbage-collected anyway, so server-side `destroy()` is mostly for tests and for symmetric semantics. Nothing on a normal server render path calls it.

### Who calls `destroy()` today

- **Regions** — when a `<ui-region>` contribution is removed (e.g. a plugin is disabled and its contribution vanishes from `$regions`), the region destroys it; destroying the region itself destroys its remaining contributions (see [Regions & dynamic UI](#regions-and-live-plugin-ui)).
- **Subtree teardown** — destroying a root component cascades through `ChildBinding`s, `LoopBinding`s and nested components automatically.
- **You** — imperative code that mounts a component and later wants it gone.
- The client `mount_app_ssr()` now returns the mounted root, so a future page/SPA teardown has a handle to `destroy()`.

### The internal seams (not user API)

- `_teardown_bindings()` — the shared "detach all bindings + destroy the scope" path used by both `destroy()` and HMR's hot-swap re-render (which tears down and rebuilds on the same instance).
- `_teardown_js()` — an internal hook: a no-op on `BaseComponent`, overridden by `JsComponent` to tear down its JS widget and release the module ref. `destroy()` calls it automatically *before* `on_unmounted()`, which is why a `@js_component` subclass can override `on_unmounted()` without ever leaking its JS widget.

---

## What `destroy()` does NOT do

### Hide ≠ unmount

An `if`-binding **hides** a subtree by detaching it from the DOM. The child stays mounted: its instance, bindings, scope effects and store edges stay alive so re-showing it re-attaches the **same** instance — no remount, no teardown. Never derive "unmounted" from "not in the DOM".

```
<detail open>…</detail>          <!-- rendered, in the DOM -->
<div if="{show}">…</div>         <!-- when {show} is False: detached, NOT destroyed -->
```

### DOM disconnect ≠ unmount

A custom element leaving the document (its parent was removed, a subtree was moved, an `if` hid an ancestor) does **not** destroy it. Basis owns the DOM and re-inserts hidden subtrees, so auto-destroying on disconnect would break hide/re-show and the hydration fallback's re-pointing moves.

### Hydration fallback ≠ destroy

When client hydration fails and the fallback re-renders, live instances are *moved* (their bindings re-pointed at the new nodes) — that is a move, never a `destroy()`.

---

## The DOM signals: `basis:connected` / `basis:disconnected`

These are a **second axis** — observable DOM signals, not lifecycle hooks. They can fire many times over a component's life and they never trigger framework actions by themselves.

| Signal | Dispatched | Meaning |
| :--- | :--- | :--- |
| `basis:connected` | Custom element `connectedCallback`, on the element (bubbles) | The element joined the live document (initial mount, an `if`-reveal, a fallback move). |
| `basis:disconnected` | Custom element `disconnectedCallback`, on `document` | The element left the live document (or an ancestor subtree containing it did). Dispatched on `document` because a removed node can no longer bubble. |

Python listens with the push helpers in `basis.client.js_bridge`:

```python
from basis.client.js_bridge import wait_connected, wait_disconnected

wait_connected(element, on_connected)       # one-shot, fires when element.isConnected
wait_disconnected(element, on_disconnected) # one-shot, fires on a real disconnect
```

The mental-model rule: **hooks = "the framework finished a phase, act on it"; signals = "the DOM changed, observe it".** `wait_connected` exists because a component hidden at SSR time has no SSR node, so `on_hydrated` can never fire — the connect signal is the only way it learns it is live (see below).

---

## JS components: when do I boot?

A `@js_component` widget must be created once its bindings are live **and** its element is in the visible DOM. The framework maps the three situations to three different moments:

| Situation | Boot moment |
| :--- | :--- |
| CSR page | `on_mounted` (element already live) |
| SSR page, component was visible at render | `on_hydrated` (bindings re-pointed at the live SSR node) |
| SSR page, component was **hidden** at render (e.g. a deselected tab — no SSR node, so no `on_hydrated`) | deferred: `wait_connected` → boots when an `if` reveals it (`basis:connected`) |

An in-flight boot is also safe: if the instance is destroyed while its ES module is still loading, `destroy()` clears the boot flags and the loader cancels itself before calling `boot_js`. See [Wrapping JS libraries with `@js_component`](js-components.md).

---

## Regions and live plugin UI

The `<ui-region>` primitive is the framework's live, data-driven mount point. Its lifecycle uses the same hooks:

- `on_mounted` mounts the region's current contributions and subscribes to `$regions` (deferred during SSR-hydration staging);
- `on_hydrated` (SSR pages) takes over the pre-rendered subtree and re-mounts contributions into the live node;
- **removing a contribution** (its plugin is disabled, or code removes it from `$regions`) makes the region `destroy()` it — full cascade, `on_unmounted` and all;
- **destroying the region itself** destroys whatever contributions are still mounted (`Region.on_unmounted`).

Disabling a plugin whose UI is **region-hosted** therefore unmounts it live on the page: the server unwinds the contribution from `$regions`, the client re-pulls, each region diffs and destroys the removed item. UI the app *baked into its own template* (a plugin tag in an app component) is a different, hard-coupled case — Basis refuses to disable such a plugin (it applies on the next page load). The regions story lives in [Regions & the spatial API](../07_plugins/spatial-api.md).

### Plugin ↔ component lifecycle parity

| Plugin lifecycle (server) | Component lifecycle (client + server) |
| :--- | :--- |
| `on_register(app)` | `on_mounted()` |
| `on_startup(app)` | `on_hydrated()` (SSR adoption) |
| `on_shutdown(app)` | `on_unmounted()` |
| `remove_plugin` / `disable_plugin` (revertible registration) | `destroy()` (idempotent teardown) |

Both are **explicit, revertible, and cascade** — the plugin manager unwinds routes/mounts/contributions; `destroy()` unwinds bindings/scopes/children. See the [plugin system](../07_plugins/plugin-system.md).

---

## The mental model in one picture

```text
                ┌────────────────────────────────────────────────┐
                │  FRAMEWORK LIFECYCLE HOOKS (once each)         │
                │                                                │
   mount ──────► on_mounted    (bound, any environment)          │
   SSR page ───► on_hydrated   (bindings adopted to live tree)   │
   destroy() ──► on_unmounted  (framework state clean)           │
                │                                                │
                │  1 verb: destroy()   (idempotent, recursive)   │
                │  internal: _teardown_bindings / _teardown_js   │
                └────────────────────────────────────────────────┘

                ┌────────────────────────────────────────────────┐
                │  DOM SIGNALS (repeatable, never auto-actions)  │
                │   basis:connected      basis:disconnected      │
                └────────────────────────────────────────────────┘
```

- **Hooks** answer "the framework finished a phase" — act once.
- **Signals** answer "the DOM changed" — observe; never destroy.
- **`destroy()`** is the only unmount; hide and disconnect are not unmount.
- Everything you *own* (sockets, timers, JS widgets, proxies) is released in `on_unmounted`; the framework releases what *it* owns in `destroy()`.

## See also

- [Defining components](defining-components.md) and [Extending & customizing components](extending-components.md) — authoring hooks & props.
- [SSR & client hydration](../05_reactivity/ssr-hydration.md) — the hydration pass that fires `on_hydrated`.
- [Child components](child-components.md) and [Scoping in loops](loop-scope.md) — how subtree teardown recurses.
- [Wrapping JS libraries with `@js_component`](js-components.md) — the JS widget boot/teardown mapping.
- [Regions & the spatial API](../07_plugins/spatial-api.md) and the [plugin system](../07_plugins/plugin-system.md) — live region-hosted UI and plugin parity.
