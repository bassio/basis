# Plugin System & Extensibility

Basis includes a self-discoverable plugin architecture (`BasisPlugin`) that enables developers to build modular, self-contained features containing backend routes, server actions, client components, static assets, and lifecycle hooks.

---

## 1. What is a Basis Plugin?

A `BasisPlugin` is a modular extension for a Basis application. It encapsulates:

- **FastAPI APIRouter**: Scoped backend GET, POST, PUT, DELETE endpoints with an optional URL prefix.
- **Component & Asset Directories**: Mounted UI components and static assets served to both server SSR and client PyScript runtimes.
- **Plugin Server Actions**: RPC actions dispatched by canonical path through the single `/basis/api/action` endpoint.
- **Lifecycle Hooks**: `on_register`, `on_startup`, and `on_shutdown` callbacks.

---

## 2. Defining a Plugin

Create a plugin file (e.g. `plugins/chat_plugin.py` or `plugins/chat/__init__.py`):

```python
from basis import BasisPlugin

plugin = BasisPlugin(
    name="chat",
    prefix="/chat",
    static_dir="./components",   # component .py/.html/.css files served to PyScript
    static_mount="/chat",        # URL path they are served at (defaults to prefix)
)

@plugin.get("/messages")
async def get_messages():
    return [{"id": 1, "text": "Hello from Chat Plugin!"}]
```

If you need lifecycle behaviour (e.g. database connections), subclass `BasisPlugin` and override the hooks — see [Lifecycle Hooks](#4-lifecycle-hooks) below.

---

## 3. Plugin Discovery Mechanisms

Basis supports two discovery patterns out-of-the-box:

### 1. Local Directory Scanning (`plugins/`)
By default, when `app.bootstrap()` runs, Basis scans the `plugins/` directory relative to your application root. Any `.py` file or package containing a top-level `plugin` variable (an instance of `BasisPlugin`) is registered automatically.

```text
my-app/
├── app.py
└── plugins/
    ├── analytics.py     ← Contains `plugin = BasisPlugin("analytics")`
    └── auth/
        └── __init__.py  ← Contains `plugin = BasisPlugin("auth")`
```

### 2. Installed Python Packages (`entry_points`)
Third-party packages can expose Basis plugins by adding a `basis.plugins` entry point in their `pyproject.toml` or `setup.py`:

#### `pyproject.toml`
```toml
[project.entry-points."basis.plugins"]
my_feature = "my_package.plugin_module:plugin"
```

Installed packages with this entry point are auto-discovered when Basis boots.

---

## 4. Lifecycle Hooks

`BasisPlugin` provides three lifecycle hooks to manage resources and startup routines. These are **instance methods you override by subclassing `BasisPlugin`** — they are *not* decorators.

| Hook | Execution Timing | Use Case |
| :--- | :--- | :--- |
| `on_register(app)` | Synchronously during `app.include_plugin()` | Route configuration and static asset mounting. |
| `on_startup(app)` | Async during app startup (`lifespan`) | Opening database connections, initializing caches, or spawning background tasks. |
| `on_shutdown(app)` | Async during app shutdown (`lifespan`) | Closing connections and cleaning up temporary files. |

```python
from basis import BasisPlugin

class AuthPlugin(BasisPlugin):
    def on_register(self, app):
        print("Plugin registered with Basis app")

    async def on_startup(self, app):
        await db.connect()

    async def on_shutdown(self, app):
        await db.disconnect()

plugin = AuthPlugin(prefix="/auth", ...)
```

> [!NOTE]
> The base `BasisPlugin` defines each hook as a no-op. Because plugins are declared as instances (e.g. `plugin = BasisPlugin(prefix="/chat")`), the way to add hook behaviour is to subclass and override, as shown above. The `plugins/` directory and `entry_points` discovery both look for a module-level `plugin` variable, so you would still write `plugin = AuthPlugin(prefix="/auth", ...)` at the bottom of your plugin module.

---

## 5. Plugin Server Actions

Plugins can register scoped RPC actions using `@plugin.action`:

```python
@plugin.action
async def send_message(sender: str, content: str):
    # Runs on backend server via /basis/api/action (dispatched by canonical path)
    return {"status": "sent", "sender": sender, "content": content}
```

These actions are accessible from client PyScript components and execute on the server with full access to plugin state and database sessions.

#### Calling a plugin action from a component

Import the plugin module and call its action — the client shim wraps each
`@plugin.action` into an RPC stub, so there is no proxy object or store lookup:

```python
from my_pkg.plugins.chat import plugin

# inside a component event handler
result = await plugin.send_message("you", "hello")
```

For a store-bound action, pass the store as the first argument — its
`store_name` is sent so the returned `new_state` is applied back to that store:

```python
from jotter.plugins.heroes import plugin
result = await plugin.generate_random_hero()
```

> [!NOTE]
> Call plugin actions from a component **method** (referenced as
> `onclick="{my_handler}"`), never from a template expression like
> `{$plugins.heroes.generate_random_hero}` — templates bind state; RPC calls
> live in handlers so the result can be handled and errors surfaced.

---

## 6. Inspecting Plugins with CLI

To list all registered local and package plugins:

```bash
basis plugin list
```

Console Output:
```text
┌────────────────────────────────────────────────────────┐
│ Discovered Plugins                                     │
├──────────────┬─────────────┬───────────────────────────┤
│ Name         │ Source      │ Status                    │
├──────────────┼─────────────┼───────────────────────────┤
│ chat         │ Local       │ Registered (/chat)        │
│ analytics    │ Package     │ Registered (/analytics)   │
└──────────────┴─────────────┴───────────────────────────┘
```
