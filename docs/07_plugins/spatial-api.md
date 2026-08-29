# Regions — the Spatial API (`basis.plugins.regions`)

Regions are the *spatial primitive* of Basis: named, ordered mount points that
UI shells host and plugins contribute to. They are fully data-driven — a plugin
**declares** a contribution into the `$regions` store, and every `<ui-region>`
tag that hosts the same name renders it, live, on both SSR and the client.

This is the flagship example of an **official in-tree plugin** (see
[Plugin System](./plugin-system.md)): the whole feature ships as a normal
`BasisPlugin` registered through the `basis.plugins` entry point, dogfooding the
plugin system it extends.

---

## 1. The two sides of a region

A region only exists when two things meet:

| Side | Mechanism | Example |
| :--- | :--- | :--- |
| **Host** | a `<ui-region name="...">` tag in a shell component | `<ui-region name="workspace-center">` |
| **Contribute** | `@plugin.region(...)` on a component in a plugin module | `@plugin.region("workspace-center") class TeamExplorer(Component)` |

The region renders whatever `$regions` holds for its `name`. Contributions
register at **boot** (import time) — render only reads. Runtime add/remove
(disable/enable a plugin) re-runs a *scoped re-sync* of that region only.

```html
<!-- host side — a shell component -->
<div class="workspace">
    <ui-region name="workspace-center"></ui-region>
</div>
```

```python
# contribution side — inside a plugin module
from basis.shared.component import Component
from basis.shared.plugin import BasisPlugin

plugin = BasisPlugin(name="my_plugin", prefix="/my")

@plugin.region("workspace-center", order=10)
class MyBanner(Component):
    __tag__ = "my-banner"

    def template(self):
        """
        <div class="my-banner">Contributed by my_plugin</div>
        """
```

---

## 2. Contributing: `@plugin.region` and `add_to_region`

### Decorator form

```python
@plugin.region("workspace-center")
class MyPanel(Component):
    ...
```

The component class is the **identity** of the contribution: re-adding the same
class to the same region **replaces** the existing entry (HMR-safe) instead of
duplicating it.

### Method form (imperative)

```python
handle = plugin.add_to_region(
    "statusbar-right",
    MyPill,
    props={"text": "synced"},
    order=1,            # explicit int sort key (optional)
    position="start",   # or "end" (default) — prepend vs append
)
handle.dispose()        # remove just this contribution
```

- `order=` is an explicit integer sort key; contributions with an explicit
  `order` sort before natural (append) ones.
- `position="start"` prepends (sorts before any positive `order`).
- `owner=` tags the contribution with a plugin name so
  `disable_plugin` / `remove_plugin` can unwind it.

### `remove_from_region`

```python
plugin.remove_from_region("statusbar-right", MyPill)
```

Removes every contribution of the given class from the region.

---

## 3. The `$regions` store

`$regions` is a reactive, app-global projection of the durable region registry
(`app._regions`):

- **Server**: `_requires_app` projection of `app._regions`, refreshed at
  app-attach and on every registration.
- **Client**: hydrated from `#basis-initial-state`, plus `add_local` /
  `remove_local` for ephemeral runtime adds (never written back to the server).

The region's `_sync` reads `store.items_for(name)` — a list of
`{cls_path, props, order}` — and mounts each contribution's component class in
declaration order. That means **order is data**: disable a plugin and its
contributions vanish from the list; re-enable and they come back in their
declared position.

---

## 4. Disabling a contributing plugin

Because contributions are data (not code stitched into a shell), the plugin
lifecycle can unwind them cleanly:

```python
await app.disable_plugin("my_plugin")   # unwinds MyBanner from every region
await app.enable_plugin("my_plugin")    # re-registers it
```

The `$plugins` store drives the `<ui-plugin-manager>` in the UI, so this is
live in the browser.

> [!IMPORTANT]
> The **regions plugin itself** is a framework-essential plugin — disabling it
> would strand every `<ui-region>` on the page. Like `$plugins`, it is
> **non-disableable**: `disable_plugin("regions")` / `remove_plugin("regions")`
> are refused (unless `force=True`, which will break any page that uses
> `<ui-region>`).

---

## 5. SSR and client hydration

Regions are SSR-first: the first paint already includes the contribution, and
the client hydrates it. Two details worth knowing:

- The SSR tree renders each contribution's **inner template root** directly
  (region items are dynamic mounts, not `<slot>`s), stamped with
  `data-region-item="<module.path.ClassName>"` for reconciliation.
- Because contribution roots are dynamically mounted, they carry **no canonical
  `data-hydration-id`** — canonical-path hydration does not descend into them.
  Instead, on the client the `<ui-region>` component **re-mounts contributions
  into the live SSR node after hydration** (via the `on_hydrated` lifecycle
  hook), so their bindings act on the DOM the user sees. This is what keeps
  region-hosted content reactive (e.g. selecting a team in the sidebar updates
  a region-hosted explorer) with a clean hydration report.

### The conventional `plugins/` directory

Since local plugin files live in your app's `plugins/` package, that directory
is **auto-mounted once** at its package path (exactly like `components/` and
`stores/`) so every plugin file — flat module or package — is served to the
client at its isomorphic import path.

> [!NOTE]
> A **local** plugin must **not** self-mount its `serving_dir`. A flat-file
> plugin (e.g. `plugins/heroes.py`) that sets `serving_dir=Path(__file__).parent`
> would mount its whole parent `plugins/` dir and re-serve every sibling to the
> same VFS destination — PyScript rejects duplicate destinations and the page
> fails to load client-side. Files in the conventional `plugins/` dir are
> already served; drop `serving_dir`/`serving_mount` on local plugins. Installed
> plugins (packages) keep their own package-dir mounts.

---

## 6. `Page.stores` and a strict subset

`$regions` is a plugin-provided store, **not** a framework control plane
(`FRAMEWORK_STORE_NAMES` is just `("plugins",)`). A page that uses the default
"all stores" serialization includes `$regions` automatically. But if your
`Page` declares a **strict** `stores` list, you must list `"regions"` explicitly
or the store won't be serialized into `#basis-initial-state`:

```python
class WorkspacePage(Page):
    root_component = WorkspaceCentral
    stores = ["app_state", "regions", ...]   # include "regions"!
```

---

## 7. Reference

Public API from `basis.plugins.regions`:

| Symbol | Purpose |
| :--- | :--- |
| `RegionsPlugin` / `regions_plugin` (`plugin`) | the official plugin instance |
| `add_to_region` / `remove_from_region` | contribution API (on the plugin) |
| `RegionContribution` / `RegionHandle` | registration record / disposer |
| `Region` | the `<ui-region>` component |
| `RegionStore` | the `$regions` reactive store |
| `resolve_component` / `mount_component` | dynamic-mount primitives |
| `cls_path_of` | class → `module.path.ClassName` |
| `MIN_ORDER` | sentinel for `position="start"` |
