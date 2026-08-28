# Codebase Structure

Below is an overview of the core directories and modules within the Basis framework repository:

```text
src/basis/
├── cli/                  # Developer CLI commands (dev, init, plugin)
│   └── commands/         # dev.py, init.py, plugin.py
├── client/               # Browser-side (PyScript) runtime
│   ├── component.py      # Client Component: hydration, mount_app / mount_app_ssr
│   ├── entrypoint.py     # single PyScript entry (SSR-hydrated or CSR mount)
│   ├── actions.py        # RPC client — call_action by canonical path
│   ├── plugin.py         # Client-side BasisPlugin shim
│   └── plugins.py        # Client-side plugin helpers
├── plugins/              # Official in-tree plugins (registered via basis.plugins entry points)
│   ├── regions/          # The regions / spatial primitive: <ui-region>, $regions store,
│   │                     #   add_to_region / @plugin.region, RegionStore, registry primitives
│   ├── ui/               # Built-in component suite (~22 components), one package per family
│   ├── shell/            # App-frame primitives + default chrome (Stack, Splitter, titlebar, …)
│   ├── theme/            # The theming mechanism: $theme control plane (ThemeStore), $themes catalog
│   │                     #   (ThemeRegistryStore), token schema, <ui-theme-provider>, Theme base,
│   │                     #   basis default theme
│   └── ambient/          # The in-tree `ambient` theme (a Theme plugin — the package dogfood)
├── server/               # FastAPI-side runtime
│   ├── app.py            # Basis (FastAPI subclass): composition root, init, include_components_dir, page/serve/include_page
│   ├── bootstrap.py      # BootstrapMixin: boot orchestration + boot mounts (offline PyScript, /pyscript.json, framework) + conventional-dir/store auto-discovery (components/, stores/, plugins/)
│   ├── responses.py      # PageResponse (HTMLResponse subclass): renders a Page recipe — SSR or CSR
│   ├── rpc.py            # RPC pipeline: canonical-path dispatch, store binding, response/error handling
│   ├── render.py         # page rendering (render_page: SSR + CSR engines, hydration IDs)
│   ├── tree_builder.py   # HTML → Element tree builder (r:0:1 path IDs)
│   ├── ast_utils.py      # @server_action AST body stripper
│   ├── static.py         # BasisStaticFiles / BasisStaticFilesPyc
│   ├── plugin.py         # Server-side BasisPlugin
│   ├── plugins.py        # Plugin subsystem: discovery, topo-sort, PluginMixin lifecycle
│   ├── db.py             # DBAppMixin, ModelRegistryMixin, REST expose generation
│   ├── vfs.py            # Mount→VFS helpers + VFSRegistry (pyscript.json manifest builder)
│   └── hmr.py            # HMRMixin + HMRManager: file-watcher, /ws/hmr WebSocket, uvicorn runners
├── static/
│   └── pyscript/         # Offline PyScript bundle mounted at /pyscript
└── shared/               # Isomorphic code (server + PyScript client)
    ├── reactive.py       # DependencyGraph (DAG), State/Computed/EffectNode, @computed, refrain()
    ├── bindings.py       # Binding classes (the DOM sync layer)
    ├── expr.py           # Safe expression language (desugar, safe_eval, safe_format)
    ├── loop.py           # Loop engine (Reconciler, LoopBodyBuilder, LoopItem, LIS)
    ├── hydration.py      # Canonical hydration paths + SSR re-pointing
    ├── base_component.py # Component lifecycle, blueprint analysis, slots, subscriptions
    ├── store.py          # Store, ModelStore, WebSocketStore, ReactiveCollection
    ├── store_provider.py # StoreProvider / ModelStoreProvider (SSR hydration guards)
    ├── router.py         # RouterStore, Route (<basis-route>), Link (<basis-link>)
    ├── page.py           # Page shell component
    ├── validation.py     # Field coercion + model validation for FormModelBinding
    ├── db.py             # Isomorphic SQLModel (server) / dataclass (client)
    ├── element.py        # Element, ElementString, Comment, ServerFragment
    ├── context.py        # ContextVarProxyDict + base_url / db_session context vars
    ├── hmr.py            # Client HMR (WebSocket + hot-swap)
    ├── basis_await.py    # <basis-await> loading / error / content wrapper
    ├── component.py      # Public Component / Basis entry point + py_event / scoped decorators
    ├── actions.py        # @server_action decorator + _action_registry
    └── plugin.py         # Isomorphic BasisPlugin selection (client vs server)
```

---

## Directory & Module Details

- **`src/basis/cli/`**: Implements the `basis` command-line utility (`basis dev`, `basis init`, `basis plugin list`) using Typer and Rich.
- **`src/basis/plugins/ui/`**: The official `ui` plugin — the pre-built accessible UI primitives, one package per family directly under the plugin — `Button`, `Badge`, `Toggle`, `Toast`, `Breadcrumbs`, `CommandPalette`, `AudioRecorder`, `Accordion`, `Calendar`, `Card`, `Checkbox`, `ContextMenu`, `FileUpload`, `TextInput`, `Modal`, `Schedule`, `ScrollArea`, `Select`, `Sidebar`, `SplitPane`, `Tabs`, `TreeView`. See [Built-in UI Suite](../04_components/ui-components.md).
- **`src/basis/client/`**: Browser-side PyScript mount logic, SSR/CSR entrypoints, action invocation, and DOM hydration.
- **`src/basis/server/`**: FastAPI application class (`Basis`), server-side rendering pipeline, element tree builder, `.pyc` bytecode compiler, and `@server_action` RPC endpoints.
- **`src/basis/shared/reactive.py`**: The central `DependencyGraph` (DAG), `StateNode`, `ComputedNode`, `EffectNode`, `@computed`, and `ReactiveObject` implementation.
- **`src/basis/shared/bindings.py`**: The binding classes — the DOM sync layer mapping template nodes to DAG-driven `update()` calls (value, event, structural, form, and loop bindings).
- **`src/basis/shared/expr.py`**: The sandboxed expression engine (`desugar_expression`, `safe_eval`, `safe_format`, `extract_dependencies`, `LoopScope`).
- **`src/basis/shared/loop.py`**: The loop engine — `Reconciler` (pure keyed diff), `LoopBodyBuilder`, `LoopItem`, and the LIS helper.
- **`src/basis/shared/hydration.py`**: The canonical hydration-path algorithm shared by SSR and client, plus loop re-pointing (`repoint_loop_to_ssr`).
- **`src/basis/shared/base_component.py`**: Component initialization, AST template analysis, blueprint compilation, slot filling, and state node creation.
- **`src/basis/shared/store.py`**: `Store`, `ModelStore` (reactive CRUD), `WebSocketStore`, and `ReactiveCollection`.
- **`src/basis/plugins/`**: Official in-tree plugins, registered through the `basis.plugins` entry point like third-party plugins. `regions/` ships the spatial primitive — `<ui-region>`, the `$regions` `RegionStore`, `add_to_region` / `@plugin.region`, and the registry primitives (`RegionContribution`, `RegionHandle`, `resolve_component` / `mount_component`). `ui/` ships the built-in component suite (one package per family). `shell/` ships the app-frame primitives + default chrome. `theme/` ships the theming mechanism — `ThemeStore` (`$theme`), the token schema, `<ui-theme-provider>`, and the built-in `basis` default theme (the `ui`/`shell` plugins depend on it). See [Regions — the Spatial API](../07_plugins/spatial-api.md), [Built-in UI Suite](../04_components/ui-components.md), and the [Theming Roadmap](../../ROADMAP-THEMING.md).
- **`src/basis/static/pyscript/`**: The offline PyScript/Pyodide bundle served from `/pyscript`.
