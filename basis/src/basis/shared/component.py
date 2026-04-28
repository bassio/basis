import sys

# Framework check
IS_CLIENT = "pyscript" in sys.modules

print("IS_CLIENT", IS_CLIENT)

if IS_CLIENT:
    from basis.components.component import Component as ClientComponent
    Component = ClientComponent
else:
    from basis.server.server_component import ServerComponent as ServerComponent
    Component = ServerComponent


from basis.components.component import client

__all__ = ['Component', 'IS_CLIENT', 'client']
