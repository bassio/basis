import sys
from functools import partial, wraps

# Framework check
IS_CLIENT = "pyscript" in sys.modules
IS_SERVER = not IS_CLIENT

if IS_CLIENT:
    from basis.client.component import Component as ClientComponent

    Component = ClientComponent
    ONLINE_PYSCRIPT = "https://pyscript.net/releases/2026.3.1"

    class Basis(object):
        def page(
            self,
            component_cls=None,
            *,
            path="/",
            page_cls=None,
            title=None,
            pyscript_src=ONLINE_PYSCRIPT,
            render_mode=None,
            name=None,
        ):
            from basis.shared.page import _synthesized_page_base

            if component_cls is None:
                return partial(
                    self.page,
                    path=path,
                    page_cls=page_cls,
                    title=title,
                    pyscript_src=pyscript_src,
                    render_mode=render_mode,
                    name=name,
                )

            _synthesized_page_base(component_cls, page_cls)
            setattr(
                component_cls,
                "_synthesized_page_args",
                {
                    "page_cls": page_cls,
                    "title": title,
                    "pyscript_src": pyscript_src,
                },
            )
            return component_cls

        def serve(self, path="/", *, render_mode=None, name=None):
            def decorate(page_cls):
                from basis.shared.page import StaticPage

                if isinstance(page_cls, type) and issubclass(page_cls, StaticPage):
                    return page_cls
                return self.page(
                    page_cls,
                    path=path,
                    render_mode=render_mode,
                    name=name,
                )

            return decorate

        def include_page(
            self,
            path,
            *,
            page_cls=None,
            render_mode=None,
            name=None,
        ):
            from basis.shared.page import StaticPage, refuse_static_render_mode

            if page_cls is None:
                def register_page(cls):
                    return self.include_page(
                        path,
                        page_cls=cls,
                        render_mode=render_mode,
                        name=name,
                    )

                return register_page
            if not (isinstance(page_cls, type) and issubclass(page_cls, StaticPage)):
                raise TypeError(
                    f"include_page(path={path!r}) requires a Page subclass, got "
                    f"{page_cls!r}."
                )
            refuse_static_render_mode(page_cls, render_mode)
            return page_cls

    Basis = Basis

else:
    from basis.server.server_component import ServerComponent as ServerComponent

    from basis.server.app import Basis

    Component = ServerComponent

    Basis = Basis


from basis.shared.base_component import include_store, include_model
from basis.shared.styling import scoped, extra_style


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


__all__ = ['Component', 'IS_CLIENT', 'IS_SERVER', 'Basis', 'client', 'include_store', 'include_model', 'scoped', 'extra_style']

