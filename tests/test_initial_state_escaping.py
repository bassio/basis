"""
``#basis-initial-state`` script-safe embedding.

The page template interpolates the serialized store JSON inside a
``<script type="application/json">`` tag. Text interpolation HTML-escapes the
value (``&`` → ``&amp;``), but script content is NOT entity-decoded by the
browser — so the client's ``json.loads(textContent)`` would hydrate the
escaped string (e.g. ``&amp;`` instead of ``&``). The fix escapes ``<``,
``>`` and ``&`` in the JSON as ``\\u003c`` / ``\\u003e`` / ``\\u0026``
sequences: they survive the template escaping unchanged, ``</script>`` can't
break out of the tag, and ``json.loads`` decodes them back to the original
characters.
"""
import json
import re

import pytest
from fastapi import Request
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import Page
from basis.shared.store import Store


def _initial_state_script(html: str) -> str:
    m = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>', html, re.DOTALL
    )
    assert m, "basis-initial-state script not found"
    return m.group(1)


def test_initial_state_round_trips_ampersands_and_angles():
    class S(Store):
        def __init__(self, name):
            super().__init__(name)
            self.title = "Reactivity & State"
            self.markup = "a < b > c"
            self.danger = "</script>"

    S("init_state_escaping")

    class Root(Component):
        """<div>hi</div>"""

    class MyPage(Page):
        root_component = Root
        stores = ["init_state_escaping"]

    app = Basis()
    app.bootstrap()

    @app.get("/")
    async def index(request: Request):
        from basis.server.responses import PageResponse

        return await PageResponse.from_page(MyPage, request, render_mode="ssr")

    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    raw = _initial_state_script(resp.text)

    # The raw script must be safe: no literal `<` (could close the script
    # tag) and no HTML entity `&amp;` (script content is not entity-decoded).
    assert "<" not in raw
    assert "&amp;" not in raw

    # The client round-trips: json.loads(textContent) recovers the originals.
    state = json.loads(raw)
    store = state["init_state_escaping"]
    assert store["title"] == "Reactivity & State"
    assert store["markup"] == "a < b > c"
    assert store["danger"] == "</script>"
