"""
``$head`` document-head store — unit tests for the store itself (the head loops
that render it and their consumers land with their own wiring).

Covers:

* the meta API — ``add_meta`` / ``upsert_meta`` / ``remove_meta`` / ``dispose``
  with name-keyed dedup (one ``theme-color`` node guaranteed, upsert replaces in
  place, no spurious reorder);
* the link API — ``add_link`` / ``remove_link`` with ``(rel, href)`` dedup, the
  fixed attribute set (every key always present, ``None`` for "not applicable"),
  and a loud refusal of an attribute the head loop cannot render;
* the item shape — plain dicts so ``Store.serialize`` round-trips without
  special-casing (the ModelStore lesson: same shape on server, in
  ``#basis-initial-state``, and after client hydration);
* post-constructor hydration — ``#basis-initial-state`` wins over constructor
    defaults;
* the per-request reconstruction contract — ``Store._registry`` is cleared per
  request, so a HeadStore subclass that seeds items in ``__init__`` (the
  constructor-state path) is rebuilt with its items intact on ``reinstantiate``.
"""
import json

import pytest

from basis.shared.head import HeadStore
from basis.shared.store import Store, install_initial_state


@pytest.fixture(autouse=True)
def _clean_registries():
    install_initial_state({})
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()


def test_fresh_store_starts_empty():
    head = HeadStore("head")
    assert head.metas_for() == []
    assert head.links_for() == []
    assert head.get_store_name() == "head"


def test_add_meta_appends_and_returns_disposer():
    head = HeadStore("head")
    disposer = head.add_meta("theme-color", "#1e1e2e")

    assert head.metas_for() == [
        {"key": "name:theme-color", "name": "theme-color", "content": "#1e1e2e"}
    ]

    disposer()
    assert head.metas_for() == []


def test_add_meta_is_idempotent_by_identity():
    head = HeadStore("head")
    head.add_meta("theme-color", "#1e1e2e")
    head.add_meta("theme-color", "#1e1e2e")  # same identity → no duplicate
    head.add_meta("color-scheme", "dark")

    metas = head.metas_for()
    assert len(metas) == 2
    # theme-color appears exactly once, first (no reorder on the no-op add).
    assert [it["name"] for it in metas] == ["theme-color", "color-scheme"]


def test_upsert_meta_replaces_in_place_and_keeps_single_node():
    head = HeadStore("head")
    head.add_meta("theme-color", "#1e1e2e")
    head.add_meta("color-scheme", "dark")

    d = head.upsert_meta("theme-color", "#f5f5f7")  # dark → light flip

    metas = head.metas_for()
    assert [it["name"] for it in metas] == ["theme-color", "color-scheme"]
    assert metas[0]["content"] == "#f5f5f7"

    d()
    assert [it["name"] for it in head.metas_for()] == ["color-scheme"]


def test_upsert_meta_appends_when_absent():
    head = HeadStore("head")
    head.upsert_meta("theme-color", "#1e1e2e")
    assert head.metas_for()[0]["key"] == "name:theme-color"


def test_remove_meta_is_noop_when_absent():
    head = HeadStore("head")
    head.remove_meta("theme-color")  # must not raise / must not mutate
    assert head.metas_for() == []


def test_metas_and_links_are_independent_lists():
    head = HeadStore("head")
    head.add_meta("theme-color", "#1e1e2e")
    head.add_link("manifest", "/manifest.webmanifest")

    assert [it["name"] for it in head.metas_for()] == ["theme-color"]
    assert [it["rel"] for it in head.links_for()] == ["manifest"]


def test_dispose_runs_disposer():
    head = HeadStore("head")
    d = head.add_meta("theme-color", "#1e1e2e")
    head.dispose(d)
    assert head.metas_for() == []
    head.dispose(None)  # tolerant of None


def test_serialize_shape_is_plain_json():
    head = HeadStore("head")
    head.add_meta("theme-color", "#1e1e2e")

    state = head.serialize()
    # The base Store also serializes its control-plane nodes (loading/error);
    # the contract that matters here is that the lists are plain, JSON-safe JSON.
    assert state["metas"] == [
        {"key": "name:theme-color", "name": "theme-color", "content": "#1e1e2e"}
    ]
    assert json.dumps(state["metas"])  # round-trips without special-casing

    head.add_link("manifest", "/manifest.webmanifest")
    assert json.dumps(head.serialize()["links"])


# ── links ──────────────────────────────────────────────────────────────────


def test_add_link_carries_every_attribute_key():
    head = HeadStore("head")
    d = head.add_link("icon", "/icon-192.png", sizes="192x192", type="image/png")

    assert head.links_for() == [
        {
            "key": "icon:/icon-192.png",
            "rel": "icon",
            "href": "/icon-192.png",
            "type": "image/png",
            "sizes": "192x192",
            "as": None,
            "media": None,
            "crossorigin": None,
        }
    ]

    d()
    assert head.links_for() == []


def test_add_link_accepts_as_under_its_keyword_spelling():
    head = HeadStore("head")
    head.add_link("preload", "/app.js", **{"as": "script"})
    assert head.links_for()[0]["as"] == "script"

    head2 = HeadStore("head2")
    head2.add_link("preload", "/app.js", as_="script")
    assert head2.links_for()[0]["as"] == "script"


def test_add_link_is_idempotent_by_rel_and_href():
    head = HeadStore("head")
    head.add_link("icon", "/a.png")
    head.add_link("icon", "/a.png")  # same identity → no duplicate
    head.add_link("apple-touch-icon", "/a.png")  # same href, different rel → distinct

    assert [it["key"] for it in head.links_for()] == [
        "icon:/a.png",
        "apple-touch-icon:/a.png",
    ]


def test_add_link_refuses_an_attribute_the_head_loop_cannot_render():
    head = HeadStore("head")
    with pytest.raises(ValueError, match="integrity"):
        head.add_link("stylesheet", "/app.css", integrity="sha384-x")


def test_hydration_never_clobbers_head_lists():
    """The boot snapshot applies after constructor defaults."""
    install_initial_state({
        "head": {
            "metas": [
                {"key": "name:theme-color", "name": "theme-color", "content": "#1e1e2e"}
            ]
        }
    })
    head = HeadStore("head")

    assert head.metas_for()[0]["content"] == "#1e1e2e"


def test_subclass_seeds_in_init_survive_reinstantiate():
    """A HeadStore subclass that seeds in __init__ (constructor state) survives
    the per-request registry reset — the pattern consumers use when their items
    are derived from request state via apply_request."""

    class SeededHead(HeadStore):
        def __init__(self, name="head"):
            super().__init__(name)
            self.add_meta("theme-color", "#1e1e2e")

    SeededHead("head")
    assert Store._registry["head"].metas_for()[0]["name"] == "theme-color"

    Store._registry.clear()
    rebuilt = Store.reinstantiate("head")
    assert isinstance(rebuilt, SeededHead)
    assert rebuilt.metas_for()[0] == {
        "key": "name:theme-color",
        "name": "theme-color",
        "content": "#1e1e2e",
    }


def test_a_page_naming_head_in_its_stores_keeps_the_real_store():
    """``$head`` is created by its own ``ensure_*`` factory, not from a blueprint, and
    ``ensure_store`` returns whatever is registered under the name. So a page whose
    ``stores`` names it has to find the real class: a plain ``Store`` placeholder would
    silently lose the whole contributing API (``add_link`` and friends) the head loops
    render."""
    from basis.shared.page import Page

    class HeadNamedPage(Page):
        stores = ["head"]

    page = HeadNamedPage._load()

    head = Store._registry["head"]
    assert isinstance(head, HeadStore)
    # The page's own head loop reads that very instance, contribution included.
    head.add_link("manifest", "/manifest.webmanifest")
    assert 'rel="manifest" href="/manifest.webmanifest"' in page.__element__.outerHTML
