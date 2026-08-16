import importlib
import json
import sys

from pyscript import document

from basis.client.component import Component
from basis.client.errors import install_error_sink
from basis.shared.hmr import start_hmr

# Structured binding-error capture: guarantees DOM safety (no "[Error: ...]"
# in rendered output), replays SSR errors, and creates the dev overlay.
# Installed BEFORE any component module is imported or mounted.
install_error_sink()

# Print client side python version details
print("[Basis] Running Python version:", sys.version)

print("[Basis] Zero-Config CSR Entrypoint started.")

# 0. Import auto-discovered store modules (stores/). Their module-scope
# instances self-hydrate from #basis-initial-state, so Page.stores name-lists
# and default-to-all resolution find them in Store._registry.
store_imports_element = document.getElementById("basis-store-imports")
if store_imports_element:
    try:
        store_modules = json.loads(store_imports_element.innerText)
        print(f"[Basis] Importing store modules: {store_modules}")
        for store_module in store_modules:
            try:
                importlib.import_module(store_module)
                print(f"[Basis] Loaded store module: {store_module}")
            except Exception as e:
                print(f"[Basis] Error importing store module {store_module}: {e}")
    except Exception as e:
        print(f"[Basis] Error parsing store imports: {e}")

# 1. Parse and import specifically registered entrypoint / page components
imports_element = document.getElementById("basis-entrypoint-imports")
if imports_element:
    try:
        modules_dict = json.loads(imports_element.innerText)

        print(f"[Basis] Importing component modules: {modules_dict}")

        for component_name, module_path in modules_dict.items():
            try:
                module = importlib.import_module(module_path)
                print(f"[Basis] Loaded: {module_path}")
                page_cls_from_module = getattr(module, component_name)

                # Load and register page-level stores on the client side
                if hasattr(page_cls_from_module, "stores"):
                    for store in page_cls_from_module.stores:
                        try:
                            if isinstance(store, str):
                                # Name-list: ensure the store exists (blueprint
                                # → proper subclass; otherwise plain Store).
                                from basis.shared.store import Store
                                if store not in Store._registry:
                                    Store.resolve(store)
                                print(f"[Basis] Loaded page store: {store}")
                            else:
                                print(f"[Basis] Loaded page store: {store.get_store_name()}")
                        except Exception as store_err:
                            print(f"[Basis] Error registering store {store}: {store_err}")

                root_component = getattr(page_cls_from_module, "root_component", None)
                if root_component is not None:
                    root_component.mount_app(document.body)

            except Exception as e:
                print(f"[Basis] Error loading {module_path}: {e}")

    except Exception as e:
        print(f"[Basis] Error parsing entrypoint imports: {e}")


# Start HMR — live hot-swap of component files (.py/.html/.css) during development.
try:
    start_hmr()
except Exception as e:
    print(f"[Basis] HMR service could not be started: {e}")
