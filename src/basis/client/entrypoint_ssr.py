import json
import importlib
from pyscript import document
from basis.client.component import Component
from basis.shared.hmr import start_hmr

print("[Basis] Zero-Config SSR Entrypoint started.")


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
                if hasattr(page_cls_from_module, "entrypoint_stores"):
                    for store in page_cls_from_module.entrypoint_stores:
                        try:
                            print(f"[Basis] Loaded page store: {store.get_store_name()}")
                        except Exception as store_err:
                            print(f"[Basis] Error registering store {store}: {store_err}")

                for entrypoint_component in page_cls_from_module.entrypoint_components:
                    entrypoint_component.mount_app_ssr(document.body.querySelector("#basis-ssr-root"))

            except Exception as e:
                print(f"[Basis] Error loading {module_path}: {e}")

    except Exception as e:
        print(f"[Basis] Error parsing entrypoint imports: {e}")


# Start HMR
'''
try:
    print("[Basis] Starting HMR service...")
    start_hmr()
except Exception as e:
    print(f"[Basis] HMR service could not be started: {e}")
'''
