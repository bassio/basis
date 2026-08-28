import importlib
import sys

from pyscript import document

from basis.client.errors import install_error_sink
from basis.shared.hmr import start_hmr
from basis.shared.store import Store

# The per-page manifest (/pyscript.json?url=<route>) carries the pre-mount plan
# (stores / headless / page stores / entrypoint) under ``basis.bootstrap``. PyScript
# parses the manifest config before evaluating this script and exposes it here.
try:
    from pyscript import config
except Exception as e:
    print(f"[Basis] pyscript.config unavailable; client bootstrap disabled: {e}")
    config = {}

bootstrap = (config.get("basis") or {}).get("bootstrap") or {}

# Structured binding-error capture: guarantees DOM safety (no "[Error: ...]"
# in rendered output), replays SSR errors, and creates the dev overlay.
# Installed BEFORE any component module is imported or mounted.
install_error_sink()

print("[Basis] Running Python version:", sys.version)

# The page shell carries <meta name="basis-render-mode" content="ssr"> on
# server-rendered pages (a reactive template binding); "csr" (the default)
# selects the plain client mount.
render_meta = document.querySelector('meta[name="basis-render-mode"]')
is_ssr = (
    render_meta is not None
    and getattr(render_meta, "getAttribute", lambda _: "")("content") == "ssr"
)
print(f"[Basis] Zero-Config Entrypoint started (mode: {'SSR' if is_ssr else 'CSR'}).")

# ── Data plane: every store exists before any component module is imported ──

# 1. Framework control-plane store ($plugins). Framework infrastructure boots
#    before app/userland stores so components can bind to it reactively from
#    the first render (hydrated from #basis-initial-state). The $regions store
#    is provided by the official regions plugin and is ensured lazily by the
#    <ui-region> component.
try:
    from basis.shared.plugin_registry import ensure_plugin_registry

    ensure_plugin_registry()
except Exception as e:
    print(f"[Basis] Error initializing framework stores: {e}")

# 2. App-level stores (stores/). Their module-scope instances self-hydrate from
# #basis-initial-state, so Page.stores name-lists and default-to-all resolution
# find them in Store._registry.
store_modules = bootstrap.get("store_modules", [])
print(f"[Basis] Importing store modules: {store_modules}")
for store_module in store_modules:
    try:
        importlib.import_module(store_module)
        print(f"[Basis] Loaded store module: {store_module}")
    except Exception as e:
        print(f"[Basis] Error importing store module {store_module}: {e}")

# 3. Page-level stores (the page's explicit subset, from the manifest).
#    Resolve them by name before importing components. Stores declared in the
#    page module itself have no blueprint yet and are created when that module
#    imports (still before mount), so skip pre-resolution for them.
page_store_names = bootstrap.get("page_stores", [])
print(f"[Basis] Resolving page stores: {page_store_names}")
for name in page_store_names:
    try:
        if name not in Store._registry and name in Store.all_names():
            Store.resolve(name)
            print(f"[Basis] Loaded page store: {name}")
    except Exception as e:
        print(f"[Basis] Error loading page store {name}: {e}")

# 4. Headless component modules — promoted at mount from a bare .html/.css with
#    no .py yet. Imported now so their tags register (custom element + registry)
#    before the root component mounts and resolves <tag> children.
headless_modules = bootstrap.get("headless_modules", [])
print(f"[Basis] Importing headless component modules: {headless_modules}")
for module_name in headless_modules:
    try:
        importlib.import_module(module_name)
        print(f"[Basis] Loaded headless component module: {module_name}")
    except Exception as e:
        print(f"[Basis] Error importing headless component module {module_name}: {e}")

# ── View plane: import the page component and mount it ──
modules_dict = bootstrap.get("entrypoint", {})
print(f"[Basis] Importing component modules: {modules_dict}")
for component_name, module_path in modules_dict.items():
    try:
        module = importlib.import_module(module_path)
        print(f"[Basis] Loaded: {module_path}")
        page_cls = getattr(module, component_name)
        root_component = getattr(page_cls, "root_component", None)
        if root_component is not None:
            if is_ssr:
                root_component.mount_app_ssr(
                    document.body.querySelector("#basis-ssr-root")
                )
            else:
                root_component.mount_app(document.body)
    except Exception as e:
        print(f"[Basis] Error loading {module_path}: {e}")

# Start HMR — live hot-swap of component files (.py/.html/.css) during development.
try:
    start_hmr()
except Exception as e:
    print(f"[Basis] HMR service could not be started: {e}")
