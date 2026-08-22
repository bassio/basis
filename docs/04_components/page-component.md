# The Page Component

`Page` is a specialized `Component` subclass that generates the outer HTML shell for your application. It produces the `<!DOCTYPE html>` declaration, the `<head>` with PyScript assets, and the `<body>` with the SSR root container.

You don't normally interact with `Page` directly — Basis uses it automatically when rendering SSR routes. You only need to subclass it when you want to customize the document shell (fonts, meta tags, additional stylesheets).

---

## The default template

Here is the template `Page` renders, showing the actual structure from `page.py`:

```html
<html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{title}</title>

        <!-- PyScript offline bundle -->
        <link rel="stylesheet" href="{pyscript_src}/core.css" />
        <script type="module" src="{pyscript_src}/core.js" onload="window.pyscript = this.module;"></script>

        <script src="./basis/client/component.js"></script>

        <!-- PyScript entry point: mounts/hydrates the application -->
        <script type="py" src="{entry_module}" config="{pyscript_json_url}"></script>

        <!-- Initial store state for client hydration -->
        <script id="basis-initial-state" type="application/json">
            {initial_state_json}
        </script>
    </head>
    <body>
        <div id="basis-ssr-root"></div>
    </body>
</html>
```

Your reactive components mount inside `<div id="basis-ssr-root">` during both server rendering and client hydration.

---

## Page attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `title` | `str` | `"Basis App"` | Browser tab title. |
| `root_component` | `Component` | `None` | The root component mounted inside the page (the single reactive tree). `None` = abstract/static shell (no reactive root). |
| `stores` | `list[str]` | `[]` | Page-level stores registered on the client at boot and serialized into initial state. A list of store *names* (`["app_state", ...]`), or **empty** (`[]` = all auto-discovered stores from `stores/`). Stores are instantiated at module scope in `stores/` and referenced by name. |
| `entry_module` | `str` | `"/basis/client/entrypoint.py"` | URL path to the Python file PyScript executes on load. |
| `pyscript_src` | `str` | `"/pyscript"` | Base path for the (offline) PyScript bundle. |
| `pyscript_json_url` | `str` | `"/pyscript.json"` | URL of the manifest PyScript uses to resolve imports. |
| `initial_state_json` | `str` | `"{}"` | Serialized store state injected during SSR; read by the client at boot. |

`initial_state_json` is populated automatically during server-side rendering — you should not set it manually.

> [!NOTE]
> **Online vs. offline PyScript.** `Page` and `include_page()` default `pyscript_src` to `/pyscript`, which `app.bootstrap()` mounts with the offline PyScript bundle shipped inside `basis/static/pyscript`. However, the `@app.page` decorator overrides this default and points `pyscript_src` at the **online** PyScript CDN release (`https://pyscript.net/releases/2026.3.1`) unless you pass `pyscript_src` explicitly. If you want offline serving with `@app.page`, pass `pyscript_src="/pyscript"`.

---

## Customizing the page shell

To add custom fonts, meta tags, or stylesheets, subclass `Page` and register it. The `@app.include_page(path)` decorator is the cleanest way — it co-locates the URL with the Page class:

```python
from basis.shared.page import Page
from basis.shared.component import Basis, Component

app = Basis()

class Dashboard(Component):
    """<div>Dashboard</div>"""

@app.include_page("/dashboard")
class MyPage(Page):
    title = "My App"
    root_component = Dashboard
```

This is equivalent to the explicit form `app.include_page("/dashboard", page_cls=MyPage)` — both register a GET route that server-renders the page.

Unlike `@app.page` (which synthesizes a shell from a root `Component` and cannot carry page-level `stores`), a `Page` subclass like `MyPage` is a complete recipe: it can declare `root_component`, `stores`, `title`, and its own `entry_module` / PyScript config, all of which are read from the class at render time. `stores` may be a name-list or empty (all auto-discovered) — see [Importing Components & the Isomorphism Principle](importing-components.md).

If you need to inject additional `<head>` elements, subclass `Page` and add them by appending to the document tree inside an overridden method. The `head()` method exists on `Page` as a placeholder but is not currently consumed by the renderer — direct DOM manipulation on the page instance is the reliable approach for now.

---

## State injection and hydration

Before generating the final HTML string, the SSR renderer:

1. Runs any `server_load()` coroutines on your components, allowing them to fetch data and populate stores.
2. Collects all registered `Store` instances and serializes their state to JSON.
3. Writes that JSON into the `<script id="basis-initial-state">` block.

When the page loads in the browser, the client-side Store constructor reads this element and pre-populates itself from the serialized data. This means your stores on the client already hold the server's data before any reactive bindings fire — no flash of stale content, no duplicate fetch requests.
