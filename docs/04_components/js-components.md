# Wrapping a JS Library with `@js_component`

Basis runs real Python in the browser — but sometimes you need a JavaScript library
(CodeMirror, a charting lib, a map). The `@js_component` decorator is the escape hatch:
wrap any JS library as a reactive Basis component with a **Python API**. You write Python;
the JS is vendored, wrapped, and hidden behind that API.

A `@js_component` class is still a normal `Component` — SSR, hydration, bindings and loops
all work unchanged. The decorator adds the load → boot → sync → teardown machinery around a
proxied bridge.

---

## The three steps

1. **Decorate** — declare the ES module URL and the exports you need.
2. **Boot** — create the JS widget from the module namespace in `boot_js(module)`.
3. **Sync + emit** — push props into JS with `sync_js()`; flow JS state back out through
   DOM events.

Here is a minimal CodeMirror wrapper (an illustrative example — a full `CodeEditor`
ships as an app-level `@js_component` plugin: vendor the bundle in your app and point
`module=` at it):

```python
from basis.shared.component import Component, py_event
from basis.shared.js_component import js_component

@js_component(
    module="/app/js/codemirror/index.js",
    name="codemirror",
    exports=["EditorView", "basicSetup"],
)
class CodeEditor(Component):
    """
    A reactive CodeMirror 6 editor.

    Attributes:
        value    : The editor document (bound text).
        language : CodeMirror language mode — 'python' (default) | 'markdown'.
        readonly : "" | "true" — disables editing.
    """
    __tag__ = "ui-code-editor"

    value = ""
    language = "python"
    readonly = ""

    #: Fields that, when set after boot, trigger sync_js() (the "props in" contract).
    bridge_props = ("value", "readonly")

    def template(self):
        """
        <div class="cm-host" oncm-change="{on_change}"></div>
        """

    def boot_js(self, module):
        from pyscript import ffi

        extensions = [module.basicSetup]
        if str(self.language).lower() in ("python", "py"):
            extensions.append(module.python())

        # Listen for document changes: the proxy calls Python, which emits an event.
        self._cm_update_proxy = ffi.create_proxy(self._on_cm_update)
        extensions.append(module.EditorView.updateListener.of(self._cm_update_proxy))

        self.view = self.js_new(module.EditorView, {
            "parent": self.__element__,
            "doc": self.value,
            "extensions": extensions,
        })

    def sync_js(self):
        # Push value / readonly into the JS view when they change in Python.
        ...

    def _on_cm_update(self, update):
        if update.docChanged:
            new_value = update.state.doc.toString()
            if new_value != self.value:
                self.emit("cm-change", {"value": new_value})

    @py_event
    def on_change(self, event):
        self.value = event.detail["value"]

    def get_value(self):
        return self.js_call(self.view, "getValue") or self.value

    def set_value(self, text):
        self.value = text          # goes through sync_js

    def focus(self):
        self.js_call(self.view, "focus")
```

---

## The bridge

### Python → JS

After the module loads, the declared `exports` are exposed on the instance and you build
the widget in `boot_js(module)` with the framework helpers:

- `self.js_new(ctor, *args)` — construct a JS object (Pyodide's `.new()`; dict/list args
  are converted via `ffi.to_js`).
- `self.js_call(obj, "method", *args)` — call a JS method, converting args for JS.
- `self.to_py(value)` — best-effort `JsProxy → Python` conversion.

Wrap them in explicit Python methods (`set_value`, `get_value`, `focus`, ...) so consumers
get a clean, type-checkable API.

### JS → Python

The idiomatic direction is a DOM `CustomEvent` on the component's host element, caught by
an ordinary `on*` template attribute — the exact same DSL as `onclick`:

```html
<div class="cm-host" oncm-change="{on_change}"></div>
```

```python
@py_event
def on_change(self, event):
    self.value = event.detail["value"]
```

`self.emit("cm-change", {"value": ...})` dispatches the event; `EventBinding` + `py_event`
convert `event.detail` to a Python dict. For callback-heavy libraries you can also pass
`ffi.create_proxy` callbacks into JS — remember to destroy them in `destroy_js()`.

## Reactivity

- **Props in:** `bridge_props` lists the fields that, when assigned after boot, trigger
  `sync_js()` — the single choke point that pushes Python state into JS.
- **State out:** JS events → `emit` → `on*` handler → `setattr(self, field, ...)` → the DAG
  re-renders every binding that reads the field.

## SSR & hydration

A `@js_component` renders a deterministic placeholder server-side (its template); the JS
library boots only on the client:

- **CSR** — boots in `on_mounted`.
- **SSR pages** — boots in `on_hydrated` (after bindings are re-pointed at the live tree),
  so the widget mounts into the *real* node. The hydration report stays clean because the
  placeholder is deterministic and matches.

Keep all JS code off the server: guard with `IS_CLIENT` / the `client()` decorator. The
helpers (`js_new`, `js_call`, `emit`) are no-ops server-side, so a wrapper can call them
unguarded.

## Serving & preloading

- **Vendor** the JS bundle under a static mount — the framework's `/basis/js/...` or a
  plugin's `serving_dir` — and pass its URL to `module=`.
- **Per-page preload:** the page manifest (`/pyscript.json?url=<route>`) preloads, via
  PyScript's `js_modules`, only the modules its component tree actually declares — pages
  that use no `@js_component` pay nothing. Components reached dynamically (regions, slots)
  fall back to a lazy dynamic import.
- **`name=`** is the stable `js_modules` key; it defaults to the URL's directory basename
  (`/app/js/codemirror/index.js` → `codemirror`). A name collision on a different URL is a
  loud error.

## Gotchas

- Pyodide has no `new` keyword — use `self.js_new(...)` (or `JsProxy.new(...)`).
- Never import `pyscript` on the server — the `IS_CLIENT` guard is mandatory.
- On SSR pages the boot is deferred to `on_hydrated()`, or the widget mounts into the
  detached shadow and dies with it. A component hidden at SSR time (e.g. inside a tab the
  server didn't select) has **no SSR node**, so `on_hydrated()` never fires and
  `on_mounted()` won't re-run when the controlling `if` later reveals it — the framework
  handles this by booting on the custom element's native `connectedCallback`: the JS side
  (the dumb part) just dispatches a generic `basis:connected` event on the custom-element
  host, and Python (`basis.client.js_bridge.wait_connected`) listens on `document` for the
  bubbled event and boots the widget when the component's element reports `isConnected`.
  This is push-based (no polling) and needs no code on your side — hidden `@js_component`s
  boot the moment the controlling `if` reveals them. Note the listener cannot attach to the
  component's template root (the event is dispatched on the host and bubbles *up*, never
  through the descendant root, which is also still detached at `on_mounted` time), hence
  the `document`-level listener.
- Destroy `ffi.create_proxy` callbacks and the JS instance in `destroy_js()`.
- A new framework module under `basis/shared/` or `basis/client/` must be added to the
  hardcoded file list in `VFSRegistry.add_framework_files` (`server/vfs.py`) or the client
  can't import it.
