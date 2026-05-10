import sys
from functools import wraps

# Framework check
IS_CLIENT = "pyscript" in sys.modules
IS_SERVER = not IS_CLIENT

if IS_CLIENT:
    from basis.components.component import Component as ClientComponent

    Component = ClientComponent

    class Basis(object):
        def entrypoint(self, component):
            component.mount_app_ssr()
            return component

    Basis = Basis

else:
    from basis.server.server_component import ServerComponent as ServerComponent

    from basis.server.app import Basis

    Component = ServerComponent

    Basis = Basis


def client(func):

    @wraps(func)
    def wrapper(*args, **kwargs):
        if IS_CLIENT:
            return func(*args, **kwargs)

    return wrapper

__all__ = ['Component', 'IS_CLIENT', 'IS_SERVER', 'Basis', 'client']
