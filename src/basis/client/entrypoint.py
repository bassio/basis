import importlib
import sys

from pyscript import document

from basis.client.errors import install_error_sink
from basis.shared.hmr import start_hmr
from basis.shared.media import install_media_resync
from basis.shared.reactive import batch
from basis.shared.store import Store, mark_client_ready

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

# The framework Page-default stores ($meta / $device / $network). Guaranteed to
# exist before any component mounts: $meta so the page head loop binds it (empty
# by default → nothing renders); $device / $network so components can read the
# context data plane from the first render. The real device/network PROBES are
# installed AFTER mount (basis.client.device_probes) so SSR and CSR first paint
# agree.
try:
    from basis.shared.meta import ensure_meta_store
    from basis.shared.device import ensure_device_store
    from basis.shared.network import ensure_network_store

    ensure_meta_store()
    ensure_device_store()
    ensure_network_store()
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

# ── View plane: import the page and mount it (the ONE boot driver) ──
# Every page — real Page subclasses AND synthesized @app.page shells — is
# listed in the manifest entrypoint and boots through here (P0). Each entry
# names a module attribute: a real Page subclass for a Page module, or a root
# COMPONENT decorated with @app.page (which carries its synthesized-shell recipe
# on the class itself — _synthesized_page_args, in its OWN __dict__ — set by the
# client decoration when the module was imported). Page.mount_document reads the
# served render-mode meta and dispatches.
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

# ── Client store lifecycle ──
# Stores get their client hook only now: the SSR document has been adopted, so a
# listener's first write is an ordinary DAG update rather than a divergence. Batched
# so N stores doing M writes flush once, and marked ready first so a store built
# during the sweep attaches itself.
mark_client_ready()
try:
    with batch():
        for store in list(Store._registry.values()):
            try:
                store.on_client_ready()
            except Exception as e:
                print(f"[Basis] {type(store).__name__}.on_client_ready failed: {e}")
except Exception as e:
    print(f"[Basis] Error running store client hooks: {e}")

try:
    install_media_resync(Store._registry)
except Exception as e:
    print(f"[Basis] Error installing the media resync: {e}")

# ── Context probes ──
# The real viewport / connectivity values, read only now that the document has mounted:
# on a server-rendered page the DOM is adopted from the server, so probing earlier would
# leave SSR showing the neutrals while CSR showed real values. Capability fields need no
# probe — they are declared media queries (already attached by the hook sweep above).
try:
    from basis.client.device_probes import install_device_probes

    install_device_probes()
except Exception as e:
    print(f"[Basis] Error installing the context probes: {e}")

# Start HMR — live hot-swap of component files (.py/.html/.css) during development.
try:
    start_hmr()
except Exception as e:
    print(f"[Basis] HMR service could not be started: {e}")
