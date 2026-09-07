import asyncio
import inspect
import sys
from functools import wraps

# Framework check
IS_CLIENT = "pyscript" in sys.modules
IS_SERVER = not IS_CLIENT

if IS_CLIENT:
    from basis.client.component import Component as ClientComponent

    Component = ClientComponent

    class Basis(object):
        def page(self, component, **kwargs):
            # §4.1 P5 (HYDRATION-WHOLEPAGE.md): a synthesized ``@app.page``
            # shell is no longer a body-only ``r:`` mount. The server builds the
            # Page shell at import time via ``type()``; the client reconstructs
            # the SAME shell here (same base, title, stores, pyscript_src) from
            # the decoration the module is running, then mounts the WHOLE
            # document through ``Page.mount_document_*`` — the exact path real
            # Page subclasses take via the unified entrypoint. Every boot path
            # is a Page now; the legacy ``mount_app_ssr``/``r:`` shim is gone.
            from basis.shared.page import Page as _PageBase, _synthesize_page

            base = kwargs.get("page_cls") or _PageBase
            if isinstance(component, type) and issubclass(component, _PageBase):
                # A real Page never reaches this shim on the client (it boots
                # through the manifest's basis.bootstrap.entrypoint); if one
                # does, leave it alone rather than double-mount.
                return component
            page_cls = _synthesize_page(
                component,
                page_cls=base,
                title=kwargs.get("title"),
                stores=kwargs.get("stores"),
                pyscript_src=kwargs.get("pyscript_src"),
            )
            try:
                from pyscript import document
            except Exception:
                return component
            try:
                meta = document.querySelector('meta[name="basis-render-mode"]')
                is_ssr = (
                    meta is not None
                    and getattr(meta, "getAttribute", lambda _: "")("content")
                    == "ssr"
                )
                if is_ssr:
                    page_cls.mount_document_ssr(document)
                else:
                    page_cls.mount_document_csr(document)
            except Exception as exc:
                print(f"[Basis] Error mounting synthesized page for {component.__name__}: {exc}")
            # Decorator form: return the DECORATED component class (mounting is a
            # side effect).
            return component

        def serve(self, *args, **kwargs):
            # Client-side: ``@app.serve`` on a root Component (the single-file
            # quickstart) behaves exactly like ``@app.page`` — the component file
            # is the boot module, so mounting it hydrates/renders the whole
            # document through the reconstructed Page shell. Page subclasses
            # never reach this shim (the client boots from the page module via
            # the manifest's basis.bootstrap.entrypoint, not from app.py).
            component = args[0] if args else kwargs.get("page_cls")
            return self.page(component, **kwargs)

        # Deprecated alias (pre-terminology-cleanup name).
        entrypoint = page

    Basis = Basis

else:
    from basis.server.server_component import ServerComponent as ServerComponent

    from basis.server.app import Basis

    Component = ServerComponent

    Basis = Basis


from basis.shared.base_component import include_store, include_model


# While the client stages a Page for whole-document SSR hydration
# (``mount_document_ssr`` → ``_hydrate_page_document_ssr``) components live in a
# detached staged tree that will be re-pointed at the live document. Dynamic
# mounters (e.g. ``<ui-region>``) read this to defer real work to
# ``on_hydrated``. Always ``False`` on the server (SSR render mounts normally).
_SSR_HYDRATION = False


def in_ssr_hydration() -> bool:
    """True while the client is inside whole-document SSR hydration (the staged
    Page mount before re-point). False on the server and during plain CSR
    mounts."""
    return _SSR_HYDRATION


def _set_ssr_hydration(value: bool) -> None:
    global _SSR_HYDRATION
    _SSR_HYDRATION = value


def client(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        if IS_CLIENT:
            return func(*args, **kwargs)
    return wrapper


class PythonEventWrapper:
    def __init__(self, original_event):
        self._original_event = original_event
        detail = getattr(original_event, "detail", None)
        if detail is not None and hasattr(detail, "to_py"):
            self.detail = detail.to_py()
        else:
            self.detail = detail

    def __getattr__(self, name):
        return getattr(self._original_event, name)


def py_event(func):
    """
    Decorator for event handlers that wraps the JS event object
    so that event.detail is automatically converted to a native Python type (dict/list) via to_py().
    """
    @wraps(func)
    def wrapper(*args, **kwargs):
        new_args = list(args)
        
        # Check positional arguments for event (usually args[1] if method, args[0] if function)
        for idx in (1, 0):
            if len(new_args) > idx:
                arg = new_args[idx]
                if arg is not None and hasattr(arg, "detail") and not isinstance(arg, PythonEventWrapper):
                    new_args[idx] = PythonEventWrapper(arg)
                    break
        
        # Check keyword arguments
        if "event" in kwargs:
            event = kwargs["event"]
            if event is not None and hasattr(event, "detail") and not isinstance(event, PythonEventWrapper):
                kwargs["event"] = PythonEventWrapper(event)
                
        res = func(*new_args, **kwargs)

        if inspect.iscoroutine(res):
            asyncio.create_task(res)
        return res
        
    wrapper.__is_py_event__ = True

    return wrapper


def scoped(func):
    """
    Decorator to mark a component's style method to be encapsulated
    within a CSS @scope (...) { ... } block.
    """
    func.__scoped__ = True
    return func


def extra_style(func):
    """
    Decorator marking a method as an *additional* (additive) style block.

    Unlike ``style()`` — which a subclass overrides to REPLACE the inherited
    stylesheet — an ``@extra_style`` block is injected as its own ``<style>``
    element *after* the component's main stylesheet, so a subclass can restyle
    a parent component without copying the parent's whole ``style()``::

        class MyTitleBar(TitleBar):
            @extra_style
            def tweaks(self):
                \"\"\"
                shell-title-bar { background: var(--accent-color); }
                \"\"\"

    The same conventions as ``style()`` apply (docstring, classmethod, or a
    plain string), it supports ``{expr}`` dynamic fields (see the styling
    guide), and it may be combined with ``@scoped`` to keep the block
    encapsulated.
    """
    func.__extra_style__ = True
    return func


__all__ = ['Component', 'IS_CLIENT', 'IS_SERVER', 'Basis', 'client', 'include_store', 'include_model', 'py_event', 'scoped', 'extra_style']

