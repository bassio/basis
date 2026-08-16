# Managing a Components Directory

As an application grows, a flat collection of component files becomes hard to navigate. Basis lets you group all components into a directory that the server mounts and serves to both the SSR renderer and the browser's PyScript runtime.

> **Convention over configuration.** In the common case you need none of the manual calls below: a `components/` *package* inside your app package is **auto-discovered** at bootstrap and mounted at its package path (so the client VFS namespace equals the filesystem import namespace). See [Importing Components & the Isomorphism Principle](importing-components.md). The manual `include_components_dir()` API below exists for custom directories.

---

## Directory layout

A typical project structure looks like this:

```text
my_project/
├── app.py
├── components/
│   ├── nav_bar/
│   │   ├── nav_bar.py
│   │   ├── nav_bar.html
│   │   └── nav_bar.css
│   └── user_list/
│       ├── user_list.py
│       ├── user_list.html
│       └── user_list.css
└── static/
```

---

## Registering the directory

> **Auto-discovery.** If your components live in `<app>/components/` (a package with an `__init__.py`), `app.bootstrap()` mounts it for you at `/your_package/components/` — no call needed. The manual API below is for directories that don't follow the convention.

Call `include_components_dir()` on your `Basis` app before registering routes:

```python
from basis.shared.component import Basis, Component

app = Basis()

app.include_components_dir(
    mount_path="/components",   # URL prefix PyScript will fetch from
    dir_path="./components",    # Local filesystem path
    name="my_components",       # Unique identifier for FastAPI's router
)

@app.page
class MainApp(Component):
    """
    <div>
        <nav-bar></nav-bar>
        <main>
            <h1>Dashboard</h1>
            <user-list></user-list>
        </main>
    </div>
    """
    pass
```

---

## What happens under the hood

**Static file serving** — FastAPI mounts a `StaticFiles` handler at `/components`. PyScript can fetch any `.py`, `.html`, or `.css` file from this path on demand.

**`/pyscript.json` manifest** — PyScript needs to know which files exist before it can import them. When the browser requests `/pyscript.json`, Basis crawls all registered component directories, collects every `.py` file along with any matching `.html` and `.css` companions, and returns the full list as a virtual filesystem manifest. PyScript reads this manifest and pre-fetches the modules it needs.

**HMR file watching** — When running `basis dev` (default, HMR on), a file watcher monitors every registered component directory. Any change to a `.py`, `.html`, or `.css` file inside a directory triggers an HMR broadcast over the `/ws/hmr` WebSocket:

- **`.css`** → the owning component's `<style>` element is updated live (scoped styles stay scoped).
- **`.html`** → the component's template + binding blueprints are rebuilt and all live instances re-render.
- **`.py`** → the module is written to the client VFS, re-imported, and every live instance is hot-swapped — state is preserved, no manual refresh.

A small HMR status badge appears in the bottom-right corner of the page during development, showing connection state and the last applied update (green ✓ / red ✗).

> **Notes**
> - HMR hot-swaps component files only. Framework-internal files (`basis/shared/*`, `basis/client/*`) and server-only code are not hot-swapped — use `basis dev --reload` (full process restart) while editing those.
> - `basis dev --no-hmr` disables the live watcher; `basis dev --reload` switches to full-process reloads.
> - PYC mode (`--pyc`) skips `.py` hot-swap (compiled bytecode can't be live-reloaded) and falls back to a full reload with a console notice.
