# Codebase Structure

Below is an overview of the core directories and modules within the Basis framework repository:

```text
src/basis/
├── cli/                  # Developer CLI commands (dev, init, plugin)
│   └── commands/         # dev.py, init_cmd.py, plugin.py
├── ui/                   # Built-in component suite (~21 components)
│   ├── accordion/ audio_recorder/ badge/ breadcrumbs/ button/ calendar/
│   ├── card/ checkbox/ command_palette/ context_menu/ file_upload/ input/
│   ├── modal/ schedule/ scroll_area/ select/ sidebar/ split_pane/ tabs/
│   ├── toast/ toggle/ tree_view/
│   └── theme.py          # ThemeStore (reactive design tokens)
├── client/               # Browser-side (PyScript) runtime
│   ├── component.py      # Client Component: hydration, mount_app / mount_app_ssr
│   ├── entrypoint_ssr.py # PyScript entry for SSR-hydrated pages
│   ├── entrypoint_csr.py # PyScript entry for CSR-only pages
│   ├── actions.py        # Server-action / plugin-action RPC proxies
│   ├── plugin.py         # Client-side BasisPlugin shim
│   └── plugins.py        # Client-side plugin helpers
├── server/               # FastAPI-side runtime
│   ├── app.py            # Basis (FastAPI subclass): bootstrap, page/include_page, RPC endpoints
│   ├── ssr.py            # SSR pipeline (render_page_ssr, hydration IDs)
│   ├── tree_builder.py   # HTML → Element tree builder (r:0:1 path IDs)
│   ├── ast_utils.py      # @server_action AST body stripper
│   ├── static.py         # BasisStaticFiles / BasisStaticFilesPyc
│   ├── plugin.py         # Server-side BasisPlugin
│   └── db.py             # DBAppMixin, ModelRegistryMixin, REST expose generation
├── static/
│   └── pyscript/         # Offline PyScript bundle mounted at /pyscript
└── shared/               # Isomorphic code (server + PyScript client)
    ├── reactive.py       # DependencyGraph (DAG), State/Computed/EffectNode, @computed, refrain()
    ├── bindings.py       # Binding classes + safe AST evaluation engine
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
- **`src/basis/ui/`**: Pre-built accessible UI primitives — `Button`, `Badge`, `Toggle`, `Toast`, `Breadcrumbs`, `CommandPalette`, `AudioRecorder`, `Accordion`, `Calendar`, `Card`, `Checkbox`, `ContextMenu`, `FileUpload`, `TextInput`, `Modal`, `Schedule`, `ScrollArea`, `Select`, `Sidebar`, `SplitPane`, `Tabs`, `TreeView` — plus `theme.py` (`ThemeStore` design tokens). See [Built-in UI Suite](../04_components/ui-components.md).
- **`src/basis/client/`**: Browser-side PyScript mount logic, SSR/CSR entrypoints, action invocation, and DOM hydration.
- **`src/basis/server/`**: FastAPI application class (`Basis`), server-side rendering pipeline, element tree builder, `.pyc` bytecode compiler, and `@server_action` RPC endpoints.
- **`src/basis/shared/reactive.py`**: The central `DependencyGraph` (DAG), `StateNode`, `ComputedNode`, `EffectNode`, `@computed`, and `ReactiveObject` implementation.
- **`src/basis/shared/bindings.py`**: DOM bindings connecting template nodes to DAG effect updates, plus the sandboxed AST evaluation engine (`safe_eval`, `safe_format`, `extract_dependencies`).
- **`src/basis/shared/base_component.py`**: Component initialization, AST template analysis, blueprint compilation, slot filling, and state node creation.
- **`src/basis/shared/store.py`**: `Store`, `ModelStore` (reactive CRUD), `WebSocketStore`, and `ReactiveCollection`.
- **`src/basis/static/pyscript/`**: The offline PyScript/Pyodide bundle served from `/pyscript`.
