"""The loop-child fixture's store: a collection, and the key the row highlight reads.

``items`` is the loop's collection and ``active`` is what a row's ``selected`` prop
compares against — the two inputs a loop child's value can follow, and the reason the
fixture can tell a store-driven prop (which moves only if the child's own bindings are
live) apart from a loop re-run (which pushes every prop again).

Plain class-level defaults, so the client hydrates both from ``#basis-initial-state``:
the server and the client agree on the first paint.
"""

from basis.shared.store import Store
from basis.shared.reactive import state


class LoopsStore(Store):
    items: list = state(default_factory=lambda: [
        {"id": "a", "title": "Alpha"},
        {"id": "b", "title": "Beta"},
        {"id": "c", "title": "Gamma"},
    ])
    active = "a"


loops = LoopsStore("loops")
