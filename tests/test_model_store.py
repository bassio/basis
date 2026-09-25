import pytest
import asyncio
import json
import sys
import types
from sqlmodel import SQLModel, Field, create_engine, Session
from sqlalchemy.pool import StaticPool

from basis.server.plugin import BasisPlugin as ServerPlugin
from basis.client.plugin import BasisPlugin as ClientPlugin
from basis.shared.store import ModelStore, Store, ReactiveCollection
from basis.shared.context import db_session_var

# Setup test DB
engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)

def test_endpoints_registration():
    # 1. Test Server Decorator
    server_plugin = ServerPlugin(prefix="/chat")
    
    @server_plugin.expose("/messages/", method="GET", one=False)
    @server_plugin.expose("/messages/{id}", method="DELETE", one=True)
    class StoreMessage(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        text: str

    assert hasattr(StoreMessage, "__endpoints__")
    assert StoreMessage.__endpoints__[("GET", False)] == "/chat/messages/"
    assert StoreMessage.__endpoints__[("DELETE", True)] == "/chat/messages/{id}"

    # 2. Test Client Decorator Stub
    client_plugin = ClientPlugin(prefix="/chat")
    
    # We define a stub model class for the client
    @client_plugin.expose("/messages/", method="GET", one=False)
    @client_plugin.expose("/messages/{id}", method="DELETE", one=True)
    class ClientMessage:
        id: int | None = None
        text: str

    assert hasattr(ClientMessage, "__endpoints__")
    assert ClientMessage.__endpoints__[("GET", False)] == "/chat/messages/"
    assert ClientMessage.__endpoints__[("DELETE", True)] == "/chat/messages/{id}"


def test_model_store_ssr_behavior():
    # In SSR, the ModelStore relies on the provider populating items directly
    # and fetch_all/fetch_one returns the cached state.
    server_plugin = ServerPlugin(prefix="/chat")
    
    @server_plugin.expose("/items/", method="GET", one=False)
    @server_plugin.expose("/items/{id}", method="GET", one=True)
    class StoreItem(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str

    store = ModelStore("test_items", StoreItem)
    
    # Simulate provider setting items on server
    store.items = [
        StoreItem(id=1, name="Apple"),
        StoreItem(id=2, name="Banana")
    ]
    
    # Calling fetch_all on server (ImportError on pyfetch) should return cached items
    async def run_ssr_test():
        items = await store.fetch_all()
        assert len(items) == 2
        assert items[0].name == "Apple"
        
        single = await store.fetch_one(id=2)
        assert single is not None
        assert single.name == "Banana"

        # fetch_one of non-existent item
        non_existent = await store.fetch_one(id=99)
        assert non_existent is None

    asyncio.run(run_ssr_test())


def test_model_store_applies_state_synchronously():
    class SnapshotItem(SQLModel):
        id: int

    store = ModelStore("snapshot_items", SnapshotItem)

    result = store.apply_state({"loading": True, "items": [{"id": 1}]})

    assert result is None
    assert store.loading is True
    assert len(store.items) == 1
    assert isinstance(store.items[0], SnapshotItem)
    assert store.items[0].id == 1


def test_rpc_response_applies_model_store_state(monkeypatch):
    from basis.client.actions import _post_rpc

    class SnapshotItem(SQLModel):
        id: int

    class Response:
        ok = True
        status = 200

        async def json(self):
            return {
                "data": "done",
                "new_state": {"items": [{"id": 2}], "loading": False},
            }

    requests = []

    async def pyfetch(url, **kwargs):
        requests.append((url, kwargs))
        return Response()

    pyodide = types.ModuleType("pyodide")
    pyodide_http = types.ModuleType("pyodide.http")
    pyodide_http.pyfetch = pyfetch
    pyodide.http = pyodide_http
    monkeypatch.setitem(sys.modules, "pyodide", pyodide)
    monkeypatch.setitem(sys.modules, "pyodide.http", pyodide_http)
    store_name = "rpc_snapshot_items"
    store = ModelStore(store_name, SnapshotItem)

    result = asyncio.run(
        _post_rpc({"path": "example.action", "store_name": store_name})
    )

    assert result == "done"
    assert len(store.items) == 1
    assert isinstance(store.items[0], SnapshotItem)
    assert store.items[0].id == 2
    assert store.loading is False
    assert requests[0][0] == "/basis/api/action"
    assert json.loads(requests[0][1]["body"])["store_name"] == store_name


def test_model_store_client_crud_and_optimistic_updates():
    import sys
    from unittest.mock import AsyncMock, MagicMock

    # Setup mock pyodide
    mock_pyodide = MagicMock()
    mock_pyfetch = AsyncMock()
    mock_pyodide.http.pyfetch = mock_pyfetch
    sys.modules["pyodide"] = mock_pyodide
    sys.modules["pyodide.http"] = mock_pyodide.http

    server_plugin = ServerPlugin(prefix="/chat")
    
    @server_plugin.expose("/items/", method="GET", one=False)
    @server_plugin.expose("/items/{id}", method="GET", one=True)
    @server_plugin.expose("/items/", method="POST", one=False)
    @server_plugin.expose("/items/{id}", method="PATCH", one=True)
    @server_plugin.expose("/items/{id}", method="DELETE", one=True)
    class ClientItem(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str

    store = ModelStore("client_items", ClientItem)

    async def run_client_test():
        # 1. Test fetch_all
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json = AsyncMock(return_value=[{"id": 1, "name": "Apple"}])
        mock_pyfetch.return_value = mock_response

        items = await store.fetch_all()
        assert len(items) == 1
        assert items[0].name == "Apple"
        mock_pyfetch.assert_called_with("/chat/items/")

        # 2. Test fetch_one
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json = AsyncMock(return_value={"id": 2, "name": "Banana"})
        mock_pyfetch.return_value = mock_response

        item = await store.fetch_one(id=2)
        assert item is not None
        assert item.name == "Banana"
        # Since fetch_one updates the items list, let's verify both are present
        assert len(store.items) == 2
        mock_pyfetch.assert_called_with("/chat/items/2")

        # 3. Test create success
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json = AsyncMock(return_value={"id": 3, "name": "Cherry"})
        mock_pyfetch.return_value = mock_response

        new_item = ClientItem(name="Cherry")
        created = await store.create(new_item)
        assert created is not None
        assert created.id == 3
        assert len(store.items) == 3
        assert store.items[-1].name == "Cherry"

        # 4. Test update success
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json = AsyncMock(return_value={"id": 1, "name": "Green Apple"})
        mock_pyfetch.return_value = mock_response

        updated = await store.update(id=1, data={"name": "Green Apple"})
        assert updated is not None
        assert updated.name == "Green Apple"
        assert store.items[0].name == "Green Apple"

        # 5. Test delete success
        mock_response = MagicMock()
        mock_response.ok = True
        mock_pyfetch.return_value = mock_response

        success = await store.delete(id=2)
        assert success is True
        assert len(store.items) == 2  # Banana should be deleted

        # 6. Test create failure (reversion check)
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 500
        mock_pyfetch.return_value = mock_response

        fail_item = ClientItem(name="Failed Item")
        failed = await store.create(fail_item)
        assert failed is None
        # items should be restored to before the create (Green Apple and Cherry)
        assert len(store.items) == 2
        assert store.error == "Create failed: 500"

        # 7. Test delete failure (reversion check)
        success = await store.delete(id=1)
        assert success is False
        assert len(store.items) == 2
        assert store.items[0].name == "Green Apple"
        assert store.error == "Delete failed: 500"

    try:
        asyncio.run(run_client_test())
    finally:
        # Clean up sys.modules mock
        sys.modules.pop("pyodide", None)
        sys.modules.pop("pyodide.http", None)


def test_recursive_json_serialization():
    # Verify that SQLModel instances are recursively stripped to serializable dicts
    server_plugin = ServerPlugin(prefix="/test")
    
    @server_plugin.expose("/test-items/", method="GET", one=False)
    class SerialItem(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str

    store = Store("test_serialize_store")
    
    # Store a list of SQLModel objects
    store.items = [
        SerialItem(id=1, name="Obj1"),
        SerialItem(id=2, name="Obj2")
    ]
    
    # Serialize the store
    serialized = store.serialize()
    
    # Check that items were serialized to dicts and not objects
    assert "items" in serialized
    assert isinstance(serialized["items"], list)
    assert len(serialized["items"]) == 2
    assert serialized["items"][0] == {"id": 1, "name": "Obj1"}
    assert serialized["items"][1] == {"id": 2, "name": "Obj2"}


def test_model_store_custom_route_parameters():
    server_plugin = ServerPlugin(prefix="/chat")
    
    @server_plugin.expose("/messages/{name}", method="GET", one=True)
    @server_plugin.expose("/messages/{name}", method="DELETE", one=True)
    class NamedMessage(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str
        text: str

    store = ModelStore("named_messages", NamedMessage)
    
    # 1. SSR test with multiple cached items
    msg1 = NamedMessage(id=1, name="alice", text="hello")
    msg2 = NamedMessage(id=2, name="bob", text="world")
    store.items = [msg1, msg2]
    
    async def run_test():
        res = await store.fetch_one(name="alice")
        assert res is not None
        assert res.text == "hello"
        
        # Match using keyword parameter
        res2 = await store.fetch_one(name="bob")
        assert res2 is not None
        assert res2.text == "world"
        
        # Match non-existent
        res3 = await store.fetch_one(name="charlie")
        assert res3 is None

    asyncio.run(run_test())


def test_reactive_model_relationships():
    import sys
    from unittest.mock import AsyncMock, MagicMock
    from basis.shared.element import Element

    # Setup mock pyodide
    mock_pyodide = MagicMock()
    mock_pyfetch = AsyncMock()
    mock_pyodide.http.pyfetch = mock_pyfetch
    sys.modules["pyodide"] = mock_pyodide
    sys.modules["pyodide.http"] = mock_pyodide.http
    
    # Patch IS_CLIENT
    import basis.shared.component
    import basis.shared.store_provider
    orig_shared_client = basis.shared.component.IS_CLIENT
    orig_provider_client = basis.shared.store_provider.IS_CLIENT
    basis.shared.component.IS_CLIENT = True
    basis.shared.store_provider.IS_CLIENT = True

    try:
        from basis.shared.store import Store, ModelStore
        from basis.shared.store_provider import ModelStoreProvider
        from basis.shared.component import Component, include_model

        # Define custom AppState
        class DummyAppState(Store):
            selected_id = 1

        app_state = DummyAppState("dummy_app_state")

        # Define target model and expose endpoint
        server_plugin = ServerPlugin(prefix="/clinic")
        @server_plugin.expose("/visits/", method="GET", one=False)
        class DummyVisit(SQLModel, table=True):
            __table_args__ = {'extend_existing': True}
            id: int | None = Field(default=None, primary_key=True)
            patient_id: int
            notes: str

        # Create ModelStoreProvider with reactive patient_id parameter
        container = Element("div", {}, [])
        
        # We define a Component subclass to hold our bindings
        @include_model(DummyVisit, name="dummy_visits", patient_id="{$dummy_app_state.selected_id}")
        class PatientVisitsComponent(Component):
            __tag__ = "patient-visits"
            
            def template(self):
                """<div></div>"""

        # Mock the fetch response
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json = AsyncMock(return_value=[{"id": 101, "patient_id": 1, "notes": "Checkup"}])
        mock_pyfetch.return_value = mock_response

        # Let async task run
        async def run_test():
            # Mount the component. This will initialize the ModelStoreProvider and evaluate bindings.
            # Since we are on client (sys.modules has pyodide), it will call fetch_data
            comp = PatientVisitsComponent.mount_with_providers(container)

            await asyncio.sleep(0.1)
            # Verify that pyfetch was called with patient_id=1
            mock_pyfetch.assert_called_with("/clinic/visits/?patient_id=1")

            # Reset the mock
            mock_pyfetch.reset_mock()
            mock_response.json = AsyncMock(return_value=[{"id": 102, "patient_id": 2, "notes": "Followup"}])

            # Now, simulate changing the app state selected_id!
            app_state.selected_id = 2

            # Let the reactive loop/DAG run
            await asyncio.sleep(0.1)

            # Verify that pyfetch was called with patient_id=2!
            mock_pyfetch.assert_called_with("/clinic/visits/?patient_id=2")

            # Clean up store registry
            Store._registry.pop("dummy_app_state", None)
            Store._registry.pop("dummy_visits", None)

        asyncio.run(run_test())

    finally:
        sys.modules.pop("pyodide", None)
        sys.modules.pop("pyodide.http", None)
        basis.shared.component.IS_CLIENT = orig_shared_client
        basis.shared.store_provider.IS_CLIENT = orig_provider_client


def test_reactive_model_ssr_resolution():
    from basis.shared.store import Store, ModelStore
    from basis.shared.store_provider import ModelStoreProvider
    from basis.shared.element import Element

    # Define custom AppState
    class DummyAppState(Store):
        selected_id = 5

    app_state = DummyAppState("dummy_app_state_ssr")

    # Define target model and expose endpoint
    server_plugin = ServerPlugin(prefix="/clinic")
    @server_plugin.expose("/visits/", method="GET", one=False)
    class DummyVisitSSR(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        patient_id: int
        notes: str

    container = Element("div", {}, [])
    
    # Create the ModelStoreProvider instance manually with a raw template string
    provider = ModelStoreProvider.initialize(
        container,
        name="dummy_visits_ssr",
        model=DummyVisitSSR,
        one=False,
        patient_id="{$dummy_app_state_ssr.selected_id}"
    )

    # Since the store is registered, the binding resolves it immediately during initialization
    assert provider._model_kwargs["patient_id"] == "5"
    assert isinstance(ModelStoreProvider.__binding_blueprints__, tuple)
    assert all(
        blueprint.kwargs.get("attr") != "patient_id"
        for blueprint in ModelStoreProvider.__binding_blueprints__
    )

    # Now run server_load
    from unittest.mock import MagicMock
    from basis.shared.context import db_session_var
    
    mock_session = MagicMock()
    mock_session.exec = MagicMock()
    mock_session.exec.return_value.all.return_value = [
        DummyVisitSSR(id=105, patient_id=5, notes="SSR checkup")
    ]
    
    token = db_session_var.set(mock_session)
    try:
        async def run_server_load():
            await provider.server_load()
            
            # Verify sqlmodel query statement was filtered by patient_id == 5
            statement = mock_session.exec.call_args[0][0]
            # Verify SQL statement filters on patient_id
            assert "patient_id = :patient_id_1" in str(statement)
            
            # Verify resolved items in the store
            visits_store = Store._registry["dummy_visits_ssr"]
            assert len(visits_store.items) == 1
            assert visits_store.items[0].notes == "SSR checkup"

        asyncio.run(run_server_load())
    finally:
        db_session_var.reset(token)
        Store._registry.pop("dummy_app_state_ssr", None)
        Store._registry.pop("dummy_visits_ssr", None)


def test_provider_no_dom_orphan():
    from basis.shared.element import Element
    from basis.shared.component import Component, include_store

    container = Element("div", {}, [])

    @include_store("dummy_store", url="/api/dummy")
    class DummyComponent(Component):
        __tag__ = "dummy-comp"
        
        def template(self):
            """<div>Hello World</div>"""

    comp = DummyComponent.mount_with_providers(container)

    child_tags = [getattr(child, "tagName", None) for child in container.children]
    assert "slot" not in child_tags
    assert "store-provider" not in child_tags


def test_model_store_config_is_not_reactive_state():
    server_plugin = ServerPlugin(prefix="/cfg")

    @server_plugin.expose("/cfg-items/", method="GET", one=False)
    class CfgItem(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str

    store = ModelStore("cfg_items", CfgItem, url="/api/custom")

    # Config metadata must NOT be reactive state nodes in the DAG.
    assert "model" not in store._dag.nodes
    assert "model_name" not in store._dag.nodes
    assert "custom_url" not in store._dag.nodes

    # ... and must NOT leak into the SSR serialization payload.
    serialized = store.serialize()
    assert "model" not in serialized
    assert "model_name" not in serialized
    assert "custom_url" not in serialized

    # Config is still readable through the public read-only accessors.
    assert store.model is CfgItem
    assert store.model_name == "CfgItem"
    assert store.custom_url == "/api/custom"


def test_model_store_config_is_read_only():
    server_plugin = ServerPlugin(prefix="/cfg")

    @server_plugin.expose("/cfg-items/", method="GET", one=False)
    class RoItem(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str

    store = ModelStore("ro_items", RoItem)

    with pytest.raises(AttributeError):
        store.model = RoItem
    with pytest.raises(AttributeError):
        store.custom_url = "/other"


def test_model_store_reinstantiate_preserves_config():
    server_plugin = ServerPlugin(prefix="/cfg")

    @server_plugin.expose("/cfg-items/", method="GET", one=False)
    class ReinstItem(SQLModel, table=True):
        __table_args__ = {'extend_existing': True}
        id: int | None = Field(default=None, primary_key=True)
        name: str

    ModelStore("reinst_items", ReinstItem, url="/api/reinst")

    # Blueprint stores an explicit flat config snapshot (not raw args/kwargs).
    blueprint = Store._store_blueprints["reinst_items"]
    assert blueprint[0] is ModelStore
    assert blueprint[1] == {"model": ReinstItem, "url": "/api/reinst"}

    # Reinstantiation rebuilds a full ModelStore with the same config.
    revived = Store.reinstantiate("reinst_items")
    assert isinstance(revived, ModelStore)
    assert revived.model is ReinstItem
    assert revived.model_name == "ReinstItem"
    assert revived.custom_url == "/api/reinst"


# ---------------------------------------------------------------------------
# Snapshot preparation keeps ModelStore payloads typed on every input path.
# ---------------------------------------------------------------------------

class HydrationItem(SQLModel):
    id: int | None = None
    name: str


class PlainItem:
    """A model class with no pydantic ``model_validate`` (non-ModelStore data)."""
    def __init__(self, id=None, name=""):
        self.id = id
        self.name = name


def test_state_import_validates_items_into_instances():
    store = ModelStore("hydr_revalidate", HydrationItem)
    store.apply_state({
        "items": [{"id": 1, "name": "Apple"}, {"id": 2, "name": "Banana"}],
    })

    assert isinstance(store.items, ReactiveCollection)
    assert all(isinstance(i, HydrationItem) for i in store.items)
    assert store.items[0].name == "Apple"
    assert store.items[1].id == 2


def test_state_import_preserves_empty_items():
    store = ModelStore("hydr_empty", HydrationItem)
    store.apply_state({"items": []})

    assert store.items == []


def test_state_import_preserves_already_typed_items():
    item = HydrationItem(id=1, name="Apple")
    store = ModelStore("hydr_typed", HydrationItem)
    store.apply_state({"items": [item]})

    assert store.items[0] is item


def test_state_import_keeps_payload_for_model_without_validator():
    store = ModelStore("hydr_plain", PlainItem)
    store.apply_state({"items": [{"id": 1, "name": "Apple"}]})

    assert isinstance(store.items[0], dict)


def test_apply_state_prepares_every_model_item():
    existing = HydrationItem(id=1, name="Apple")
    store = ModelStore("apply_typed_items", HydrationItem)

    store.apply_state({
        "items": [existing, {"id": 2, "name": "Banana"}],
    })

    assert isinstance(store.items, ReactiveCollection)
    assert store.items[0] is existing
    assert isinstance(store.items[1], HydrationItem)
    assert store.items[1].name == "Banana"


def test_invalid_model_patch_leaves_existing_items_unchanged():
    original = HydrationItem(id=1, name="Apple")
    store = ModelStore("apply_invalid_items", HydrationItem)
    store.items = ReactiveCollection([original])

    with pytest.raises(ValueError, match=r"apply_invalid_items.*items\[0\]"):
        store.apply_state({"items": [{"id": 2}]})

    assert list(store.items) == [original]

