"""The fixture store declaring media queries.

``wide`` deliberately defaults to ``True``: it is the neutral the server and the
client agree on, so a narrow first paint is a client-only correction rather than a
hydration divergence.
"""

from basis.shared.media import media
from basis.shared.store import Store


class LayoutStore(Store):
    """Declared queries are ordinary reactive fields, answered by the browser."""

    narrow = media("(width <= 600px)")
    wide = media("(width >= 1000px)", default=True)


layout = LayoutStore("layout")
