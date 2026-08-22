"""Client-side HMR (Hot Module Replacement).

Connects to the dev server's ``/ws/hmr`` WebSocket and live-swaps component
files pushed by the file watcher:

* ``.css``  -> update the owning component's ``<style>`` element (keeps scoping)
* ``.html`` -> rebuild the component's blueprint + binding blueprints, re-render
               all live instances (state preserved via :meth:`hot_swap`)
* ``.py``   -> write the new source to the Pyodide VFS, evict + re-import the
               module, then hot-swap every live instance to the new class

``start_hmr()`` is idempotent and should be called once from the client
entrypoint (``entrypoint.py``).
"""

import importlib
import json
import sys
from pathlib import Path

from basis.shared.base_component import BaseComponent

try:
    from pyscript import window, document, ffi

    PYSCRIPT = True
except ImportError:
    PYSCRIPT = False


def _js(target, name, fallback=None):
    """Safe attribute access on a JS proxy (avoids raising on missing props)."""
    try:
        return getattr(target, name)
    except Exception:
        return fallback


class HMRClient:
    def __init__(self, host=None, port=None):
        if not PYSCRIPT:
            return

        if host is None:
            host = _js(window.location, "hostname", "localhost")
        if port is None:
            port = _js(window.location, "port", "") or ""

        scheme = "wss" if str(_js(window.location, "protocol", "http:")).startswith("https") else "ws"
        self.url = f"{scheme}://{host}:{port}/ws/hmr"
        self.ws = window.WebSocket.new(self.url)

        # Keep the proxies alive for the lifetime of the client.
        self._on_message_proxy = ffi.create_proxy(self._on_message)
        self._on_close_proxy = ffi.create_proxy(self._on_close)
        self._on_error_proxy = ffi.create_proxy(self._on_error)
        self.ws.onmessage = self._on_message_proxy
        self.ws.onclose = self._on_close_proxy
        self.ws.onerror = self._on_error_proxy

        self._badge = self._create_badge()
        self._log = None
        # module -> {subclass_cls: base_name}: subclass classes defined in OTHER
        # modules that we template-refreshed from a reloaded base. Re-applied on
        # every subsequent reload of the base module so repeated hot-swaps work.
        self._refreshed_subclasses = {}
        self._set_badge("connecting", "HMR connecting…")
        print(f"[HMR] Connecting to {self.url}")

    # ── lifecycle ──────────────────────────────────────────────────────────
    def _on_close(self, event):
        self._set_badge("offline", "HMR disconnected")

    def _on_error(self, event):
        self._set_badge("error", "HMR connection error")

    def _on_message(self, event):
        try:
            data = json.loads(event.data)
        except Exception as e:
            print(f"[HMR] Could not parse message: {e}")
            return
        if data.get("type") == "hmr":
            try:
                self._handle_update(data)
            except Exception as e:
                self._notify(f"Update failed: {e}", error=True)

    def _handle_update(self, data):
        ext = data.get("ext")
        file = data.get("file") or ""
        content = data.get("content") or ""
        module = data.get("module")
        component_class = data.get("component_class")

        if ext == "css":
            self._update_css(file, content, component_class, module)
        elif ext == "py":
            self._update_python(file, content, module)
        elif ext == "html":
            self._update_html(file, content, component_class, module)

    # ── CSS ────────────────────────────────────────────────────────────────
    def _update_css(self, file, content, component_class=None, module=None):
        cls = self._find_component_class(file, component_class, module)
        if cls is None:
            self._update_global_css(file, content)
            self._notify(f"No component matched {file}; applied as global CSS")
            return

        try:
            setattr(cls, "style", content)
        except Exception:
            cls.style = content

        style_content = cls._get_style_string() or content
        updated = 0
        # Update styles recorded by mount_app (works inside shadow roots) AND any
        # matching light-DOM style element — a mount's staging shadow can hold a
        # copy that must not mask the visible one.
        for se in getattr(BaseComponent, "_style_elements", {}).get(cls.__name__, []):
            se.textContent = style_content
            updated += 1
        for se in document.querySelectorAll(f'style[data-component-class="{cls.__name__}"]'):
            se.textContent = style_content
            updated += 1

        if updated:
            self._notify(f"CSS updated for {cls.__name__}")
        else:
            self._update_global_css(file, content)
            self._notify(f"CSS for {cls.__name__}: no mounted <style> found; applied globally")

    def _update_global_css(self, file, content):
        # Append to <body> (after the component styles) rather than <head>, so a
        # same-specificity global rule actually wins the cascade when it has to.
        style_el = document.getElementById("basis-hmr-global-css")
        if style_el is None:
            style_el = document.createElement("style")
            style_el.id = "basis-hmr-global-css"
            document.body.appendChild(style_el)
        style_el.textContent = content

    # ── HTML ───────────────────────────────────────────────────────────────
    def _update_html(self, file, content, component_class=None, module=None):
        cls = self._find_component_class(file, component_class, module)
        if cls is None:
            self._notify(f"No component matched {file}; HTML not applied", error=True)
            return

        # Rebuild blueprint + binding blueprints from scratch (never accumulate).
        cls.__templatestr__ = content
        cls.__binding_blueprints__ = []
        try:
            cls._initialize_blueprint()
            cls._analyze_creation_args()
            cls._analyze_template()
        except Exception as e:
            self._notify(f"Template analysis failed for {cls.__name__}: {e}", error=True)
            return

        count = self._hot_swap_class(cls, cls)
        self._notify(f"HTML updated for {cls.__name__} ({count} instance(s) re-rendered)")

    # ── Python ─────────────────────────────────────────────────────────────
    def _update_python(self, file, content, module=None):
        if not module:
            # Fallback heuristic (best effort): "sub/dir/file.py" -> "sub.dir.file"
            module = file.replace("/", ".").replace("\\", ".").replace(".py", "").lstrip(".")

        mod = sys.modules.get(module)
        if mod is None:
            self._notify(f"Module {module} not loaded in this page; skipping (will apply on next reload)")
            return

        src_path = getattr(mod, "__file__", None)
        if not src_path or src_path.endswith((".pyc", ".pyo")):
            self._notify(
                f"Cannot hot-swap {module}: loaded from {src_path} "
                "(compiled mode). Use --no-pyc or a full reload for .py changes",
                error=True,
            )
            return

        # 1. Persist the new source onto the VFS where the module was loaded from.
        try:
            Path(src_path).write_text(content, encoding="utf-8")
        except Exception as e:
            self._notify(f"Could not write {src_path}: {e}", error=True)
            return

        # Tell the import machinery that files on disk may have changed; otherwise
        # a cached directory listing / finder cache can serve the stale file.
        try:
            importlib.invalidate_caches()
        except Exception:
            pass

        # 2. Capture old component classes before evicting.
        old_classes = {
            name: obj
            for name, obj in vars(mod).items()
            if isinstance(obj, type)
            and issubclass(obj, BaseComponent)
            and obj is not BaseComponent
        }

        # 3. Evict the module (and any of its submodules) so the next import
        #    re-reads the updated source from the VFS instead of the stale code.
        for key in [k for k in list(sys.modules) if k == module or k.startswith(module + ".")]:
            del sys.modules[key]

        # 4. Fresh import.
        try:
            new_mod = importlib.import_module(module)
        except Exception as e:
            self._notify(f"Re-import of {module} failed: {e}", error=True)
            # Restore the old module reference so the app keeps working.
            sys.modules[module] = mod
            return

        # 5. Hot-swap every old class -> new class, preserving instance state.
        new_classes = {
            name: obj
            for name, obj in vars(new_mod).items()
            if isinstance(obj, type)
            and issubclass(obj, BaseComponent)
            and obj is not BaseComponent
        }

        # 5a. Re-apply template refreshes to subclass classes (from other modules)
        # that were previously hot-refreshed from this module.
        refreshed = 0
        for sub, base_name in list(self._refreshed_subclasses.get(module, {}).items()):
            new_base = new_classes.get(base_name)
            if new_base is None:
                continue
            try:
                refreshed += self._refresh_subclass_instances(sub, new_base)
            except Exception as e:
                self._notify(f"Re-refresh of subclass {sub.__name__} failed: {e}", error=True)

        total = refreshed
        for name, old_cls in old_classes.items():
            new_cls = new_classes.get(name)
            if new_cls is not None and new_cls is not old_cls:
                total += self._hot_swap_class(old_cls, new_cls, module=module)

        self._notify(f"{module} reloaded; hot-swapped {total} instance(s)")

    # ── hot-swap helpers ───────────────────────────────────────────────────
    def _hot_swap_class(self, old_cls, new_cls, module=None):
        """Find all live instances of old_cls and re-render them with new_cls."""
        count = 0
        for instance in list(BaseComponent._live_instances):
            if isinstance(instance, old_cls):
                try:
                    if type(instance) is old_cls:
                        instance.hot_swap(new_cls)
                    else:
                        # Subclass defined in a different (not reloaded) module:
                        # keep its identity, just refresh the inherited template.
                        # Remember the subclass so FUTURE reloads of this module
                        # also re-refresh it (its MRO still points at an old base).
                        if module:
                            self._refreshed_subclasses.setdefault(module, {})[
                                type(instance)
                            ] = old_cls.__name__
                        instance.hot_swap_template(new_cls)
                    count += 1
                except Exception as e:
                    self._notify(f"Hot-swap failed for {old_cls.__name__}: {e}", error=True)
        return count

    def _refresh_subclass_instances(self, sub, new_base):
        """Re-point ``sub``'s inherited template to ``new_base`` and re-render all live instances."""
        count = 0
        for instance in list(BaseComponent._live_instances):
            if type(instance) is sub:
                try:
                    instance.hot_swap_template(new_base)
                    count += 1
                except Exception as e:
                    self._notify(f"Subclass refresh failed for {sub.__name__}: {e}", error=True)
        return count

    def _find_component_class(self, file, component_class=None, module=None):
        """
        Resolve the component class an HMR file belongs to.

        Precedence:
        1. ``module`` — the authoritative import name sent by the server; match a
           registered class by ``__module__`` (handles names like ``titlebar.css``
           -> class ``TitleBar``, whose filename heuristic would produce ``Titlebar``).
        2. ``component_class`` — explicit class name from the server.
        3. Filename heuristic — PascalCase / flat / kebab forms of the stem.
        """
        if module:
            for c in BaseComponent._registry.values():
                if getattr(c, "__module__", "") == module:
                    return c

        if component_class:
            for c in BaseComponent._registry.values():
                if c.__name__ == component_class:
                    return c

        stem = Path(file).stem
        potential = "".join(part.capitalize() for part in stem.split("_"))
        flat = stem.replace("_", "")
        kebab = stem.replace("_", "-")
        for c in BaseComponent._registry.values():
            tag = getattr(c, "__tag__", "") or ""
            if c.__name__ == potential or c.__name__ == flat:
                return c
            if tag and (tag.lower() == kebab.lower() or tag.lower() == stem.lower()):
                return c
        return None

    # ── dev status badge ───────────────────────────────────────────────────
    def _create_badge(self):
        try:
            badge = document.createElement("div")
            badge.id = "basis-hmr-badge"
            badge.style.position = "fixed"
            badge.style.bottom = "12px"
            badge.style.right = "12px"
            badge.style.zIndex = "2147483647"
            badge.style.padding = "4px 10px"
            badge.style.borderRadius = "999px"
            badge.style.font = "11px/1.4 system-ui, sans-serif"
            badge.style.color = "#fff"
            badge.style.background = "rgba(30,30,30,0.85)"
            badge.style.pointerEvents = "none"
            document.body.appendChild(badge)
            return badge
        except Exception:
            return None

    def _set_badge(self, state, text):
        if self._badge is None:
            return
        try:
            self._badge.textContent = text
            colors = {
                "connecting": "#f59e0b",
                "connected": "#22c55e",
                "offline": "#ef4444",
                "error": "#ef4444",
            }
            self._badge.style.background = colors.get(state, "rgba(30,30,30,0.85)")
        except Exception:
            pass

    def _notify(self, message, error=False):
        print(f"[HMR] {message}")
        try:
            if self._log is None:
                self._log = document.createElement("pre")
                self._log.id = "basis-hmr-log"
                self._log.style.cssText = (
                    "position:fixed;bottom:36px;right:12px;z-index:2147483647;"
                    "max-width:60vw;max-height:40vh;overflow:auto;margin:0;padding:6px 10px;"
                    "border-radius:6px;background:rgba(20,20,20,0.92);color:#8be9fd;"
                    "font:10px/1.4 monospace;pointer-events:none;white-space:pre-wrap"
                )
                document.body.appendChild(self._log)
            self._log.textContent += f"{'✗' if error else '✓'} {message}\n"
        except Exception:
            pass
        if self._badge is not None:
            try:
                state = "error" if error else "connected"
                self._set_badge(state, f"HMR {'✗' if error else '✓'} {message[:200]}")
            except Exception:
                pass

    def mark_connected(self):
        self._set_badge("connected", "HMR connected")


_hmr_client = None


def start_hmr():
    """Create the singleton HMR client (idempotent)."""
    global _hmr_client
    if not PYSCRIPT:
        return None
    if _hmr_client is None:
        try:
            _hmr_client = HMRClient()
            _hmr_client.mark_connected()
        except Exception as e:
            print(f"[HMR] Could not start HMR service: {e}")
            _hmr_client = None
    return _hmr_client
