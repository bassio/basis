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
            # A real Page subclass never reaches this shim on the client (it
            # boots through the manifest's basis.bootstrap.entrypoint); if one
            # does, leave it alone rather than annotate it.
            from basis.shared.page import Page as _PageBase

            if isinstance(component, type) and issubclass(component, _PageBase):
                return component
            # Annotate the decorated root component with its synthesized-shell
            # recipe (the same decoration inputs the server used). This follows
            # the framework's decorator idiom (``__scoped__`` /
            # ``__extra_style__``): metadata travels with the object, never in a
            # module global. Mounting is NOT a side effect — the client driver
            # (client/entrypoint.py) reads the annotation off the class and
            # calls Page.mount_document. Writing into the class's OWN __dict__
            # (vars) keeps the annotation from leaking down to subclasses.
            component.__dict__["_synthesized_page_args"] = {
                k: kwargs[k]
                for k in ("page_cls", "title", "stores", "pyscript_src")
                if k in kwargs
            }
            # Decorator form: return the DECORATED component class.
            return component

        def serve(self, *args, **kwargs):
            # Client-side: ``@app.serve`` on a root Component (the single-file
            # quickstart) behaves exactly like ``@app.page`` — annotate the
            # class; the driver mounts. Page subclasses never reach this shim.
            component = args[0] if args else kwargs.get("page_cls")
            return self.page(component, **kwargs)

    Basis = Basis

else:
    from basis.server.server_component import ServerComponent as ServerComponent

    from basis.server.app import Basis

    Component = ServerComponent

    Basis = Basis


from basis.shared.base_component import include_store, include_model


# While the client stages a Page for whole-document SSR hydration
# (``Page.mount_document`` → ``_hydrate_page_document_ssr``) components live in a
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


__all__ = ['Component', 'IS_CLIENT', 'IS_SERVER', 'Basis', 'client', 'include_store', 'include_model', 'scoped', 'extra_style']

