"""
SSR store-reconstruction tests.

Covers the "orphan plain ``Store()``" code smell: SSR must reconstruct the
proper store *subclass* (with its constructor state) from the persistent
blueprint registry, instead of creating a plain base-class ``Store(name)``
that silently loses subclass state (e.g. ``CounterStore.__init__`` setting
``count = 0``).
"""
import json
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.page import _synthesize_page
from basis.server.ssr import _get_all_stores, _serialize_initial_state
from basis.shared.store import Store
from basis.shared.component import Component


# ---------------------------------------------------------------------------
# Test stores (unique names per class avoid blueprint collisions)
# ---------------------------------------------------------------------------

class CounterStore(Store):
    def __init__(self, name):
        super().__init__(name)
        self.count = 0

    def increment(self):
        self.count += 1
        return self.count


class ArgStore(Store):
    """Store whose constructor takes extra args (ModelStore-style)."""

    def __init__(self, name, label, flag=True):
        super().__init__(name)
        self.label = label
        self.flag = flag


@pytest.fixture(autouse=True)
def _clean_registries():
    Store._registry.clear()
    Store._store_blueprints.clear()
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()


class _NoStores:
    pass


# ---------------------------------------------------------------------------
# _get_all_stores unit tests
# ---------------------------------------------------------------------------

def test_get_all_stores_reconstructs_subclass_for_basis_stores():
    CounterStore("ssr_counter")

    class PageWithStore:
        __basis_stores__ = [{"name": "ssr_counter"}]

    # Simulate the per-request registry reset
    Store._registry.clear()

    stores = _get_all_stores(PageWithStore, _NoStores)
    store = stores["ssr_counter"]
    assert isinstance(store, CounterStore)
    assert store.get_store_name() == "ssr_counter"
    assert store.count == 0  # subclass constructor state preserved


def test_get_all_stores_reconstructs_subclass_with_args_for_global_stores():
    ArgStore("ssr_arg", "My Label", flag=False)

    Store._registry.clear()

    stores = _get_all_stores(
        _NoStores, _NoStores, global_stores=[{"name": "ssr_arg"}]
    )
    store = stores["ssr_arg"]
    assert isinstance(store, ArgStore)
    assert store.label == "My Label"
    assert store.flag is False


def test_get_all_stores_falls_back_to_plain_store_without_blueprint():
    # No blueprint was ever recorded for this config-only store
    Store._registry.clear()

    stores = _get_all_stores(
        _NoStores, _NoStores, global_stores=[{"name": "config_only"}]
    )
    assert type(stores["config_only"]) is Store


def test_serialize_initial_state_includes_subclass_constructor_state():
    CounterStore("ssr_serialize")

    class PageWithStore:
        __basis_stores__ = [{"name": "ssr_serialize"}]

    Store._registry.clear()
    stores = _get_all_stores(PageWithStore, _NoStores)

    data = json.loads(_serialize_initial_state(stores))
    assert "ssr_serialize" in data
    assert data["ssr_serialize"]["count"] == 0


# ---------------------------------------------------------------------------
# Page.load(ssr=True) page-store reconstruction
# ---------------------------------------------------------------------------

def test_page_load_reconstructs_entrypoint_store_subclass():
    from basis.shared.page import Page

    CounterStore("ssr_entry")

    class EntryPage(Page):
        stores = ["ssr_entry"]

    Store._registry.clear()
    EntryPage.load(ssr=True, request=None)

    store = Store._registry.get("ssr_entry")
    assert isinstance(store, CounterStore)
    assert store.count == 0


def test_page_load_reconstructs_entrypoint_store_with_constructor_args():
    """
    Regression: the old `store.__class__(name)` reconstruction only passed the
    name, which would raise for stores with extra constructor args (e.g. ArgStore
    or ModelStore).  Reconstructing from the blueprint preserves those args.
    """
    from basis.shared.page import Page

    ArgStore("ssr_arg_entry", "Lbl", flag=False)

    class ArgPage(Page):
        stores = ["ssr_arg_entry"]

    Store._registry.clear()
    ArgPage.load(ssr=True, request=None)

    store = Store._registry.get("ssr_arg_entry")
    assert isinstance(store, ArgStore)
    assert store.label == "Lbl"
    assert store.flag is False


# ---------------------------------------------------------------------------
# HTTP-level: full SSR render emits subclass constructor state
# ---------------------------------------------------------------------------

def test_ssr_http_initial_state_contains_subclass_state():
    app = Basis()
    CounterStore("ssr_http_counter")
    app.include_store("ssr_http_counter")  # global store -> global_stores path
    app.bootstrap()

    class Root(Component):
        """
        <div>{$ssr_http_counter.count}</div>
        """

    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="/test_root.py"))
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200

    match = re.search(
        r'<script id="basis-initial-state"[^>]*>(.*?)</script>',
        resp.text,
        re.DOTALL,
    )
    assert match, "basis-initial-state script not found in SSR output"
    state = json.loads(match.group(1))

    assert "ssr_http_counter" in state
    assert state["ssr_http_counter"].get("count") == 0
