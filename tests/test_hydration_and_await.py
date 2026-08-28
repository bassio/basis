import pytest
import asyncio
import json
import sys
from unittest.mock import AsyncMock, MagicMock

# Define simple SQLModel for testing
from sqlmodel import SQLModel, Field
class TestModel(SQLModel, table=True):
    __table_args__ = {'extend_existing': True}
    id: int | None = Field(default=None, primary_key=True)
    name: str

@pytest.fixture(autouse=True)
def mock_environment():
    import sys
    import basis.shared.store
    import basis.shared.store_provider
    import basis.shared.component
    
    # Save original state
    orig_modules = dict(sys.modules)
    orig_document = getattr(basis.shared.store, "document", None)
    orig_fetch = getattr(basis.shared.store_provider, "fetch", None)
    orig_is_client_component = basis.shared.component.IS_CLIENT
    orig_is_client_provider = basis.shared.store_provider.IS_CLIENT
    
    # Setup mocks
    basis.shared.component.IS_CLIENT = True
    basis.shared.store_provider.IS_CLIENT = True
    
    mock_pyodide = MagicMock()
    mock_pyfetch = AsyncMock()
    mock_pyodide.http.pyfetch = mock_pyfetch
    sys.modules["pyodide"] = mock_pyodide
    sys.modules["pyodide.http"] = mock_pyodide.http
    
    mock_pyscript = MagicMock()
    mock_pyscript.fetch = AsyncMock()
    sys.modules["pyscript"] = mock_pyscript
    
    mock_fetch = AsyncMock()
    basis.shared.store_provider.fetch = mock_fetch
    
    mock_document = MagicMock()
    mock_script_tag = MagicMock()
    mock_document.getElementById.return_value = mock_script_tag
    basis.shared.store.document = mock_document
    
    yield mock_script_tag, mock_fetch, mock_pyfetch
    
    # Restore original state
    sys.modules.clear()
    sys.modules.update(orig_modules)
    basis.shared.store.document = orig_document
    basis.shared.store_provider.fetch = orig_fetch
    basis.shared.component.IS_CLIENT = orig_is_client_component
    basis.shared.store_provider.IS_CLIENT = orig_is_client_provider

from basis.shared.store import Store, ModelStore
from basis.shared.store_provider import StoreProvider, ModelStoreProvider
from basis.server.render import _serialize_initial_state
from basis.shared.basis_await import BasisAwait

def test_ssr_serialization_and_client_hydration(mock_environment):
    mock_script_tag, _, _ = mock_environment
    
    # 1. Clean registry
    Store._registry.clear()
    
    # 2. Setup stores with metadata
    test_store = Store("test_store")
    test_store._ssr_url = "/api/test"
    
    test_model_store = ModelStore("test_model_store", TestModel)
    test_model_store._ssr_params = {"id": "42"}
    
    # 3. Serialize initial state
    serialized_json = _serialize_initial_state({
        "test_store": test_store,
        "test_model_store": test_model_store
    })
    
    data = json.loads(serialized_json)
    
    # Verify JSON structure
    assert "test_store" in data
    assert "test_model_store" in data
    assert "__basis_meta__" in data
    assert data["__basis_meta__"]["ssr_url"]["test_store"] == "/api/test"
    assert data["__basis_meta__"]["ssr_params"]["test_model_store"] == {"id": "42"}
    
    # Verify metadata is not in the store's public serialized dict
    assert "_ssr_url" not in data["test_store"]
    assert "ssr_url" not in data["test_store"]
    assert "_ssr_params" not in data["test_model_store"]
    assert "ssr_params" not in data["test_model_store"]
    
    # 4. Clean registry and simulate client hydration
    Store._registry.clear()
    mock_script_tag.textContent = serialized_json
    
    hydrated_store = Store("test_store")
    hydrated_model_store = ModelStore("test_model_store", TestModel)
    
    assert hydrated_store._hydrated_from_ssr is True
    assert hydrated_store._ssr_url == "/api/test"
    
    assert hydrated_model_store._hydrated_from_ssr is True
    assert hydrated_model_store._ssr_params == {"id": "42"}

@pytest.mark.anyio
async def test_hydration_guard_store_providers(mock_environment):
    mock_script_tag, mock_fetch, _ = mock_environment
    
    Store._registry.clear()
    mock_script_tag.textContent = "{}"
    
    # Setup hydrated stores
    store = Store("users")
    store._ssr_url = "/api/users"
    store._hydrated_from_ssr = True
    
    model_store = ModelStore("patients", TestModel)
    model_store._ssr_params = {"id": "99"}
    model_store._hydrated_from_ssr = True
    
    # 1. Test StoreProvider Hydration Guard
    provider = StoreProvider.initialize(MagicMock(), name="users", url="/api/users")
    
    mock_response = MagicMock()
    mock_response.json = AsyncMock(return_value={"status": "ok"})
    mock_fetch.return_value = mock_response
    mock_fetch.reset_mock()
    
    await provider.fetch_data()
    
    # Verify fetch was skipped due to guard
    mock_fetch.assert_not_called()
    assert store._hydrated_from_ssr is False
    
    # Clear last fetched url to force refetch
    provider._last_fetched_url = ""
    await provider.fetch_data()
    mock_fetch.assert_called_once()
    
    # 2. Test ModelStoreProvider Hydration Guard
    model_provider = ModelStoreProvider.initialize(MagicMock(), name="patients", model="TestModel", one=True)
    model_provider._model_kwargs = {"id": "99"}
    
    # Mock model_store fetch methods
    model_store.fetch_one = AsyncMock(return_value=TestModel(id=99, name="Alice"))
    model_store.fetch_one.reset_mock()
    
    await model_provider.fetch_data()
    
    # Verify model_store fetch_one was skipped due to guard
    model_store.fetch_one.assert_not_called()
    assert model_store._hydrated_from_ssr is False
    
    # Clear last kwargs str to force refetch
    model_provider._last_kwargs_str = ""
    await model_provider.fetch_data()
    model_store.fetch_one.assert_called_once_with(id="99")

def test_basis_await_component_reactivity(mock_environment):
    mock_script_tag, _, _ = mock_environment
    
    Store._registry.clear()
    Store._pending_subscriptions.clear()
    mock_script_tag.textContent = "{}"
    
    # 1. Create basis-await component for a store that doesn't exist yet
    await_comp = BasisAwait.initialize(MagicMock(), store="tasks")
    
    assert await_comp._show_loading is True
    assert await_comp._show_content is False
    assert await_comp._show_error is False
    
    # 2. Create the store to fulfill pending subscriptions
    tasks_store = Store("tasks")
    
    assert await_comp._show_loading is False
    assert await_comp._show_content is True
    assert await_comp._show_error is False
    
    # 3. Simulate store changing state to loading
    tasks_store.loading = True
    
    assert await_comp._show_loading is True
    assert await_comp._show_content is False
    assert await_comp._show_error is False
    
    # 4. Simulate store error
    tasks_store.loading = False
    tasks_store.error = "Database offline"
    
    assert await_comp._show_loading is False
    assert await_comp._show_error is True
    assert await_comp._show_content is False

def test_missing_store_safe_eval(mock_environment):
    from basis.shared.bindings import safe_eval, ALLOWED_BUILTINS
    from basis.shared.base_component import BaseComponent
    
    # Ensure non_existent_store is not in registry
    if "non_existent_store" in BaseComponent.S:
        del BaseComponent.S["non_existent_store"]
        
    class DummyContext:
        pass
        
    ctx = DummyContext()
    
    # Evaluating a missing store should safely return None (falsy) instead of raising KeyError / generating [Error: ...]
    result_attr = safe_eval("BaseComponent.S['non_existent_store'].some_attr", ctx, ALLOWED_BUILTINS)
    assert result_attr is None
    
    # Boolean checking on a missing store should also be safely falsy
    result_bool = bool(safe_eval("BaseComponent.S['non_existent_store']", ctx, ALLOWED_BUILTINS))
    assert result_bool is False

def test_empty_store_attribute_safe_eval(mock_environment):
    from basis.shared.bindings import safe_eval, ALLOWED_BUILTINS
    from basis.shared.base_component import BaseComponent
    
    # 1. Create a store but do not populate any custom attributes on it
    empty_store = Store("empty_store")
    
    class DummyContext:
        pass
        
    ctx = DummyContext()
    
    # 2. Evaluating a non-existent public attribute on this existing store should return None
    val = safe_eval("BaseComponent.S['empty_store'].some_unpopulated_attr", ctx, ALLOWED_BUILTINS)
    assert val is None

def test_empty_path_parameter_url_resolution(mock_environment):
    from basis.shared.store import _resolve_url_and_params
    
    # 1. Test URL resolution with an empty/None path parameter value
    url_pattern = "/team/{id}"
    resolved_url, params = _resolve_url_and_params(url_pattern, {"id": None})
    assert resolved_url == ""
    assert params == {}
    
    resolved_url2, params2 = _resolve_url_and_params(url_pattern, {"id": ""})
    assert resolved_url2 == ""
    assert params2 == {}
    
    resolved_url3, params3 = _resolve_url_and_params(url_pattern, {"id": "None"})
    assert resolved_url3 == ""
    assert params3 == {}
    
    # 2. Test valid path parameter value
    resolved_url4, params4 = _resolve_url_and_params(url_pattern, {"id": 5})
    assert resolved_url4 == "/team/5"
    assert params4 == {"id": 5}

def test_store_typo_attribute_errors(mock_environment):
    from sqlmodel import SQLModel, Field
    import pytest
    from basis.shared.store import ModelStore
    
    class FakeModel(SQLModel):
        id: int | None = Field(default=None, primary_key=True)
        name: str
        
    model_store = ModelStore("fake_store", FakeModel)
    
    # 1. Accessing a valid model field before load/population should safely return None
    assert model_store.name is None
    
    # 2. Accessing a typo/non-existent model field should immediately raise AttributeError
    with pytest.raises(AttributeError):
        _ = model_store.naame
        
    # 3. For schema-less stores, accessing attributes before load returns None
    schema_less = Store("schema_less")
    assert schema_less.anything is None
    
    # 4. Once first load completes on the schema-less store, accessing missing attributes raises AttributeError
    schema_less.__dict__['_first_load_completed'] = True
    with pytest.raises(AttributeError):
        _ = schema_less.anything


def test_get_nodes_skip_loops(mock_environment):
    from basis.client.component import Component
    from basis.server.server_component import ServerComponent
    from basis.shared.element import Element, ElementString
    from unittest.mock import MagicMock

    # 1. Test ServerComponent._get_nodes_skip_loops (Server-side)
    # Tree:
    # <div>
    #   <span>
    #     <p for="item" in="items">
    #       <span>child</span>
    #     </p>
    #   </span>
    #   <aside>aside sibling</aside>
    # </div>
    child_text = ElementString("child")
    inner_span = Element(tag="span", attrs={}, children=[child_text])
    loop_p = Element(tag="p", attrs={"for": "item", "in": "items"}, children=[inner_span])
    outer_span = Element(tag="span", attrs={}, children=[loop_p])
    
    aside_text = ElementString("aside sibling")
    aside = Element(tag="aside", attrs={}, children=[aside_text])
    
    root = Element(tag="div", attrs={}, children=[outer_span, aside])
    
    # Set parent links (bs4 tree builder sets them automatically, we set them here manually)
    child_text.parent = inner_span
    inner_span.parent = loop_p
    loop_p.parent = outer_span
    outer_span.parent = root
    aside_text.parent = aside
    aside.parent = root

    server_nodes = ServerComponent._get_nodes(root, skip_loop_descendants=True)
    
    # Expected nodes: root, outer_span, loop_p, aside, aside_text
    # Excluded nodes: inner_span, child_text
    assert root in server_nodes
    assert outer_span in server_nodes
    assert loop_p in server_nodes
    assert aside in server_nodes
    assert aside_text in server_nodes
    assert inner_span not in server_nodes
    assert child_text not in server_nodes

    # Test ServerComponent._get_nodes(root, skip_loop_descendants=False)
    server_nodes_all = ServerComponent._get_nodes(root, skip_loop_descendants=False)
    assert inner_span in server_nodes_all
    assert child_text in server_nodes_all

    # 2. Test Component._get_nodes (Client-side)
    # We mock the browser DOM elements and createTreeWalker.
    mock_root = MagicMock()
    mock_root.nodeType = 1
    mock_root.hasAttribute.return_value = False
    
    mock_outer_span = MagicMock()
    mock_outer_span.nodeType = 1
    mock_outer_span.hasAttribute.return_value = False
    
    mock_loop_p = MagicMock()
    mock_loop_p.nodeType = 1
    mock_loop_p.hasAttribute.side_effect = lambda attr: attr in ("for", "in")
    
    mock_inner_span = MagicMock()
    mock_inner_span.nodeType = 1
    mock_inner_span.hasAttribute.return_value = False
    
    mock_child_text = MagicMock()
    mock_child_text.nodeType = 3
    
    mock_aside = MagicMock()
    mock_aside.nodeType = 1
    mock_aside.hasAttribute.return_value = False
    
    mock_aside_text = MagicMock()
    mock_aside_text.nodeType = 3


    # Define DFS order of nodes
    dfs_nodes = [
        mock_outer_span,
        mock_loop_p,
        mock_inner_span,
        mock_child_text,
        mock_aside,
        mock_aside_text
    ]

    # Map each node to its parent (used by parentNode())
    parent_map = {
        mock_outer_span: mock_root,
        mock_loop_p: mock_outer_span,
        mock_inner_span: mock_loop_p,
        mock_child_text: mock_inner_span,
        mock_aside: mock_root,
        mock_aside_text: mock_aside
    }

    # Map each node to its next sibling (used by nextSibling())
    sibling_map = {
        mock_outer_span: mock_aside,
        mock_loop_p: None,
        mock_inner_span: None,
        mock_child_text: None,
        mock_aside: None,
        mock_aside_text: None
    }

    class MockTreeWalker:
        def __init__(self):
            self.nodes = [mock_root] + dfs_nodes
            self.index = 0
            self.current = mock_root

        def nextNode(self):
            self.index += 1
            if self.index < len(self.nodes):
                self.current = self.nodes[self.index]
                return self.current
            self.current = None
            return None

        def nextSibling(self):
            sibling = sibling_map.get(self.current)
            if sibling:
                self.current = sibling
                self.index = self.nodes.index(sibling)
                return sibling
            return None

        def parentNode(self):
            parent = parent_map.get(self.current)
            if parent:
                self.current = parent
                self.index = self.nodes.index(parent)
                return parent
            return None

    # Patch the document.createTreeWalker and NodeFilter.SHOW_ELEMENT | ...
    from basis.client import component
    orig_document = component.document
    orig_window = component.window

    mock_doc = MagicMock()
    mock_win = MagicMock()
    mock_doc.createTreeWalker.return_value = MockTreeWalker()
    
    component.document = mock_doc
    component.window = mock_win

    try:
        client_nodes = Component._get_nodes(mock_root, skip_loop_descendants=True)
        
        # Expected: mock_outer_span, mock_loop_p, mock_aside, mock_aside_text
        # Excluded: mock_inner_span, mock_child_text
        assert mock_outer_span in client_nodes
        assert mock_loop_p in client_nodes
        assert mock_aside in client_nodes
        assert mock_aside_text in client_nodes
        assert mock_inner_span not in client_nodes
        assert mock_child_text not in client_nodes

        # Test Component._get_nodes(mock_root, skip_loop_descendants=False)
        # Reset MockTreeWalker index/current for a new walk
        mock_doc.createTreeWalker.return_value = MockTreeWalker()
        client_nodes_all = Component._get_nodes(mock_root, skip_loop_descendants=False)
        assert mock_inner_span in client_nodes_all
        assert mock_child_text in client_nodes_all
    finally:
        component.document = orig_document
        component.window = orig_window



