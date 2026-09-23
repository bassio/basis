"""``$pwa`` — the app's installable identity (declaration only; the plugin's routes,
head links and worker land with their own wiring).

Covers the store contract:

* the declaration lands in plain instance fields, so it serializes into
  ``#basis-initial-state`` and the client hydrates the app's identity without a request;
* ``standalone`` is a declared media query (a capability the browser answers) with a
  serializable neutral, and the worker's fields are neutrals the client overwrites;
* the store-subclass footgun — ``__init__`` runs after hydration inside ``Store.__init__``
  and must not clobber a hydrated value;
* the per-request reconstruction contract — ``Store._registry`` is cleared per request,
  so the declaration must survive in the blueprint.
"""
import json

import pytest

import basis.shared.store as store_module
from basis.plugins import mobile
from basis.plugins.mobile import PwaStore
from basis.plugins.mobile.store import STANDALONE_QUERY
from basis.shared.media import MediaQuery
from basis.shared.store import Store


class _Script:
    """Stand-in for the ``#basis-initial-state`` script tag."""

    def __init__(self, payload: str):
        self.textContent = payload


class _Document:
    """Stand-in for the client document, serving one initial-state payload."""

    def __init__(self, state: dict):
        self._state = state

    def getElementById(self, element_id: str):
        return _Script(json.dumps(self._state))


@pytest.fixture(autouse=True)
def _clean_registries(monkeypatch):
    monkeypatch.setattr(store_module, "_client_ready", False)
    monkeypatch.setattr(store_module, "document", None)
    Store._registry.clear()
    Store._store_blueprints.clear()
    for query in list(MediaQuery._instance_registry.values()):
        query._mql = None
    yield
    Store._registry.clear()
    Store._store_blueprints.clear()


def test_a_bare_declaration_has_sane_defaults():
    pwa = PwaStore("pwa")

    assert pwa.start_url == "/"
    assert pwa.scope == "/"
    assert pwa.display == "standalone"
    assert pwa.icons == []
    assert pwa.offline is True
    assert pwa.title is None


def test_the_declaration_serializes_as_plain_json():
    pwa = PwaStore(
        "pwa",
        title="Myapp",
        short_name="Myapp",
        icons=["/static/icon-192.png"],
        offline=False,
    )

    state = pwa.serialize()
    assert state["title"] == "Myapp"
    assert state["short_name"] == "Myapp"
    assert state["icons"] == ["/static/icon-192.png"]
    assert state["offline"] is False
    assert json.dumps(state)


def test_standalone_is_a_declared_media_query_with_a_serializable_neutral():
    declared = PwaStore.__dict__["standalone"]
    assert declared.query == STANDALONE_QUERY
    assert declared.default is False

    pwa = PwaStore("pwa")
    # The server serializes the declared neutral (an ordinary tab is not installed).
    assert pwa.serialize()["standalone"] is False


def test_the_worker_fields_are_neutrals_the_client_overwrites():
    pwa = PwaStore("pwa")

    assert pwa.controlled is False
    assert pwa.ready is False
    assert pwa.waiting_version is None
    assert pwa.can_install is False
    assert pwa.error is None


def test_hydration_wins_over_the_constructor_defaults(monkeypatch):
    """A hydrated identity must survive construction — the defaulting loop runs after
    ``Store.__init__`` already read ``#basis-initial-state`` (the store-subclass footgun)."""
    monkeypatch.setattr(
        store_module,
        "document",
        _Document({"pwa": {"title": "Hydrated", "icons": [{"src": "/a.png"}]}}),
    )

    pwa = PwaStore("pwa", title="Myapp", icons=["/i.png"])

    assert pwa.title == "Hydrated"
    assert pwa.icons == [{"src": "/a.png"}]
    # A key the payload omits still gets the declaration's default.
    assert pwa.start_url == "/"
    assert pwa.offline is True


def test_the_declaration_survives_the_per_request_registry_reset():
    """``Store._registry`` is cleared per request; the blueprint is what rebuilds it."""
    PwaStore("pwa", title="Myapp", start_url="/app", icons=["/i.png"])
    Store._registry.clear()

    rebuilt = Store.reinstantiate("pwa")
    assert isinstance(rebuilt, PwaStore)
    assert rebuilt.title == "Myapp"
    assert rebuilt.start_url == "/app"
    assert rebuilt.icons == ["/i.png"]


def test_icons_and_shortcuts_are_copied_not_aliased():
    """A module-level declaration must not share a mutable list with the store."""
    declared = ["/i.png"]
    pwa = PwaStore("pwa", icons=declared)

    pwa.icons.append("/j.png")
    assert declared == ["/i.png"]


# --- the client hooks (server-side safety) --------------------------------

def test_the_client_hooks_are_inert_and_safe_without_a_browser():
    """The store is built on the server too, and the hooks are its contract.

    Nothing calls them without PyScript, but they are the client's entry point: an
    exception here (or a registration attempted on the server) would be a framework bug,
    not an app's.
    """
    pwa = PwaStore("pwa", title="Myapp")

    pwa.on_client_ready()
    pwa.on_client_teardown()
    pwa.on_client_teardown()  # documented as safe to call repeatedly

    assert pwa.controlled is False
    assert pwa.error is None


def test_the_client_calls_are_honest_no_ops_on_the_server():
    """An app writes one handler that runs on both sides (the ``haptic()`` shape), so
    these report "nothing was asked" rather than raising."""
    assert mobile.apply_update() is False
    assert mobile.install() is False
