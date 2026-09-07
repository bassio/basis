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

# Page.mount_document reads the served <meta name="basis-render-mode"> and
# dispatches SSR (hydrate the whole document in place) vs CSR (keep the served
# head static and render the body region).
print("[Basis] Zero-Config Entrypoint started.")

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

# The $meta document-meta store (a Page-level default like $plugins). Guarantee
# it exists before any component mounts so the page head loop binds it; empty by
# default (empty items → nothing renders).
try:
    from basis.shared.meta import ensure_meta_store

    ensure_meta_store()
except Exception as e:
    print(f"[Basis] Error initializing $meta store: {e}")

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

# ── View plane: import the page and mount it (the ONE boot driver) ──
# Every page — real Page subclasses AND synthesized @app.page shells — is
# listed in the manifest entrypoint and boots through here (P0). Each entry
# names a module attribute: a real Page subclass for a Page module, or a root
# COMPONENT decorated with @app.page (which carries its synthesized-shell recipe
# on the class itself — _synthesized_page_args, in its OWN __dict__ — set by the
# client decoration when the module was imported). Page.mount_document reads the
# served render-mode meta and dispatches; there is no legacy body-only mount
# path left.
from basis.shared.page import _synthesize_page

modules_dict = bootstrap.get("entrypoint", {})
print(f"[Basis] Importing component modules: {modules_dict}")
for component_name, module_path in modules_dict.items():
    try:
        module = importlib.import_module(module_path)
        print(f"[Basis] Loaded: {module_path}")
        page_cls = getattr(module, component_name)
        # A synthesized @app.page shell carries its shell recipe on the class
        # (own __dict__ only — never inherited). Rebuild the same Page the
        # server built from those decoration inputs, then mount it through the
        # identical whole-document path real Pages take. Real Page subclasses
        # carry no annotation and mount directly.
        recipe = vars(page_cls).get("_synthesized_page_args")
        if recipe is not None:
            page_cls = _synthesize_page(page_cls, **recipe)
        page_cls.mount_document(document)
    except Exception as e:
        print(f"[Basis] Error loading {module_path}: {e}")

# Start HMR — live hot-swap of component files (.py/.html/.css) during development.
try:
    start_hmr()
except Exception as e:
    print(f"[Basis] HMR service could not be started: {e}")
