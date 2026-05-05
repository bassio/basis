import sys
import importlib
import json
from pathlib import Path
from basis.shared.base_component import BaseComponent

try:
    from pyscript import window, document, ffi
    PYSCRIPT = True
except ImportError:
    PYSCRIPT = False

class HMRClient:
    def __init__(self, host=None, port=None):
        if not PYSCRIPT:
            return
            
        if host is None:
            host = window.location.hostname
        if port is None:
            port = window.location.port
            
        self.url = f"ws://{host}:{port}/ws/hmr"
        self.ws = window.WebSocket.new(self.url)
        
        # Use ffi.create_proxy for callbacks
        self._on_message_proxy = ffi.create_proxy(self._on_message)
        self.ws.onmessage = self._on_message_proxy
        
        print(f"HMR: Connected to {self.url}")

    def _on_message(self, event):
        print(event)
        data = json.loads(event.data)
        if data.get("type") == "hmr":
            self._handle_update(data)

    def _handle_update(self, data):

        print("In _handle_update")

        ext = data.get("ext")
        file = data.get("file")
        content = data.get("content")

        if ext == "css":
            self._update_css(file, content)
        elif ext == "py":
            self._update_python(file, content)
        elif ext == "html":
            self._update_html(file, content)

    def _update_css(self, file, content):
        # Try to map file name to class name
        # e.g. "my_component.css" -> "MyComponent"
        stem = Path(file).stem
        potential_class_name = "".join([part.capitalize() for part in stem.split("_")])
        
        styles = document.querySelectorAll("style[data-component-class]")
        found = False
        for style in styles:
            if style.getAttribute("data-component-class").lower() == potential_class_name.lower():
                style.textContent = content
                print(f"HMR: Updated CSS for {potential_class_name}")
                found = True
        
        if not found:
            # Fallback: if no tag matches, maybe it's a new style or global
            print(f"HMR: No specific style tag found for {file}, could be global.")

    def _update_python(self, file, content):
        # 1. Update the local file in PyScript VFS
        # We need to find where this file is mounted.
        # For now, let's assume it's relative to the current working directory or predictable.
        # Basis usually mounts components under /basis/components/ or similar.
        
        try:
            # Attempt to write to VFS
            # We might need to handle absolute vs relative paths carefully
            with open(file, "w") as f:
                f.write(content)
            
            # 2. Identify the module
            # This is tricky because the path in 'file' might not match the import path.
            # But let's try a simple mapping: components/my_comp.py -> components.my_comp
            module_name = file.replace("/", ".").replace(".py", "").lstrip(".")

            print("module_name", module_name)
            print("sys.modules", [m for m in sys.modules.keys()])

            if module_name in sys.modules:
                print(f"HMR: Reloading module {module_name}")
                old_module = sys.modules[module_name]
                
                # Capture old classes to find their instances
                old_classes = {name: obj for name, obj in vars(old_module).items() 
                               if isinstance(obj, type) and issubclass(obj, BaseComponent) and obj is not BaseComponent}
                
                importlib.reload(old_module)
                new_module = sys.modules[module_name]
                
                # 3. Hot swap instances
                for name, old_cls in old_classes.items():
                    new_cls = getattr(new_module, name, None)
                    if new_cls:
                        self._hot_swap_class(old_cls, new_cls)
            else:
                print(f"HMR: Module {module_name} not yet loaded, ignoring.")
                
        except Exception as e:
            print(f"HMR: Error updating Python file {file}: {e}")

    def _hot_swap_class(self, old_cls, new_cls):
        """Find all live instances of old_cls and trigger their hot_swap."""
        # Note: _live_instances is a WeakSet on BaseComponent, but each subclass might have its own?
        # Actually it's defined on BaseComponent, so it tracks ALL instances.
        
        count = 0
        for instance in list(BaseComponent._live_instances):
            if isinstance(instance, old_cls):
                instance.hot_swap(new_cls)
                count += 1
        
        print(f"HMR: Hot-swapped {count} instances of {old_cls.__name__}")

    def _update_html(self, file, content):
        # Update the template on the class and re-render instances
        stem = Path(file).stem
        potential_class_name = "".join([part.capitalize() for part in stem.split("_")])
        
        # Find the class in the registry
        for tag, cls in BaseComponent._registry.items():
            if cls.__name__.lower() == potential_class_name.lower():
                print(f"HMR: Updating template for {cls.__name__}")
                setattr(cls, "__templatestr__", content)
                # Re-analyze template to update blueprints
                cls._initialize_blueprint()
                cls._analyze_template()
                
                # Hot swap all instances to reflect template change
                self._hot_swap_class(cls, cls)
                break

def start_hmr():
    if PYSCRIPT:
        window.hmr_client = HMRClient()
