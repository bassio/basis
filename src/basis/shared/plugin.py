import sys

IS_CLIENT = "pyscript" in sys.modules

if IS_CLIENT:
    from basis.client.plugin import BasisPlugin as ClientPlugin
    BasisPlugin = ClientPlugin
else:
    from basis.server.plugin import BasisPlugin as ServerPlugin
    BasisPlugin = ServerPlugin

__all__ = ["BasisPlugin"]
