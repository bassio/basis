import pytest
from fastapi.testclient import TestClient
from basis.server.app import Basis
from basis.server.plugin import BasisPlugin

def test_plugin_actions_registration_and_execution():
    app = Basis()
    plugin = BasisPlugin(prefix="/chat", name="chat")

    # 1. Test action without parameters to decorator (inferred name)
    @plugin.action
    def send_message(text: str):
        return f"Message: {text}"

    # 2. Test action with custom name passed to decorator
    @plugin.action(name="register_user")
    def add_user(username: str):
        return f"User {username} registered"

    # Verify registration in plugin.actions
    assert "send_message" in plugin.actions
    assert "register_user" in plugin.actions
    assert plugin.actions["send_message"] == send_message
    assert plugin.actions["register_user"] == add_user

    # Include plugin and bootstrap app
    app.bootstrap()
    app.include_plugin(plugin)

    client = TestClient(app)

    # 3. Test RPC call to send_message action via the plugin-action endpoint
    payload = {
        "plugin_name": "chat",
        "action_name": "send_message",
        "args": ["Hello, Basis!"],
        "kwargs": {}
    }
    response = client.post("/basis/api/plugin-action", json=payload)
    assert response.status_code == 200
    assert response.json() == {"data": "Message: Hello, Basis!"}

    # 4. Test RPC call to register_user action
    payload = {
        "plugin_name": "chat",
        "action_name": "register_user",
        "args": [],
        "kwargs": {"username": "alice"}
    }
    response = client.post("/basis/api/plugin-action", json=payload)
    assert response.status_code == 200
    assert response.json() == {"data": "User alice registered"}

    # 5. Test RPC call to non-existent plugin
    payload = {
        "plugin_name": "unknown_plugin",
        "action_name": "send_message",
        "args": ["hello"],
        "kwargs": {}
    }
    response = client.post("/basis/api/plugin-action", json=payload)
    assert response.status_code == 404
    assert "Plugin 'unknown_plugin' not found" in response.text

    # 6. Test RPC call to non-existent action in valid plugin
    payload = {
        "plugin_name": "chat",
        "action_name": "non_existent_action",
        "args": [],
        "kwargs": {}
    }
    response = client.post("/basis/api/plugin-action", json=payload)
    assert response.status_code == 404
    assert "Action 'non_existent_action' not found on plugin 'chat'" in response.text


def test_ast_action_stripper():
    from basis.server.ast_utils import strip_server_actions

    source_code = """
@plugin.action
def get_db_credentials():
    secret_key = "123456"
    return secret_key

@heroes_plugin.action(name="save_hero")
def save_hero(hero: str):
    db.save(hero)
    return True

@server_action
async def global_action():
    print("Executing server action...")
    return 42

def regular_helper():
    return "This should not be stripped"
"""

    stripped = strip_server_actions(source_code)

    # 1. Assert @plugin.action body is replaced with pass
    assert "secret_key = \"123456\"" not in stripped
    assert "pass" in stripped

    # 2. Assert @heroes_plugin.action(name="save_hero") body is replaced with pass
    assert "db.save(hero)" not in stripped

    # 3. Assert @server_action body is replaced with pass
    assert "print(\"Executing server action...\")" not in stripped

    # 4. Assert regular helper is intact
    assert "regular_helper" in stripped
    assert "This should not be stripped" in stripped


def test_dynamic_plugins_client_generation():
    app = Basis()
    plugin = BasisPlugin(prefix="/heroes", name="Heroes Plugin")

    @plugin.action
    def generate_random_hero():
        return "random hero"

    @plugin.action(name="assign_hero_to_team")
    def assign(hero_id: int, team: str):
        return f"assigned {hero_id} to {team}"

    app.bootstrap()
    app.include_plugin(plugin)

    with TestClient(app) as client:
        # 1. Fetch dynamic plugins registry JSON
        response = client.get("/basis/api/plugins-registry")
        assert response.status_code == 200
        registry = response.json()
        assert "Heroes Plugin" in registry
        assert "generate_random_hero" in registry["Heroes Plugin"]
        assert "assign_hero_to_team" in registry["Heroes Plugin"]

        # 2. Assert pyscript.json maps the static plugins.py file correctly
        response = client.get("/pyscript.json")
        assert response.status_code == 200
        pyscript_config = response.json()
        files = pyscript_config.get("files", {})
        
        # We find the DOMAIN-placeholder key mapping to the static file
        domain_key = [k for k in files.keys() if k.endswith("/basis/client/plugins.py")]
        assert len(domain_key) == 1
        assert files[domain_key[0]] == "./basis/client/plugins.py"


def test_keyed_loop_binding_reordering_with_custom_elements():
    from basis.shared.bindings import LoopBinding, ChildBinding, LoopItem, LoopScope
    import unittest.mock as mock

    class MockDOMNode:
        def __init__(self, tag_name="div", parent=None):
            self.tagName = tag_name
            self.parentNode = parent
            self.childNodes = []
            self.attributes = {}

        def getAttribute(self, key):
            return self.attributes.get(key)

        def setAttribute(self, key, value):
            self.attributes[key] = value

        def removeAttribute(self, key):
            self.attributes.pop(key, None)

        def getAttributeNames(self):
            return list(self.attributes.keys())

        def cloneNode(self, deep=True):
            cloned = MockDOMNode(self.tagName)
            cloned.attributes = self.attributes.copy()
            return cloned

        def remove(self):
            if self.parentNode and self in self.parentNode.childNodes:
                self.parentNode.childNodes.remove(self)
                self.parentNode = None

        @property
        def nextSibling(self):
            if not self.parentNode:
                return None
            idx = self.parentNode.childNodes.index(self)
            if idx < len(self.parentNode.childNodes) - 1:
                return self.parentNode.childNodes[idx + 1]
            return None

        def insertBefore(self, node, ref_node):
            if ref_node is not None:
                if ref_node not in self.childNodes:
                    raise ValueError("Child to insert before is not a child of this node")
                idx = self.childNodes.index(ref_node)
                self.childNodes.insert(idx, node)
            else:
                self.childNodes.append(node)
            node.parentNode = self
            return node

        def appendChild(self, node):
            self.childNodes.append(node)
            node.parentNode = self
            return node

    # Setup parent element
    parent = MockDOMNode("ui-tab-content")

    # Mock component instance and its registry/mount logic
    class MockComponent:
        _registry = {}
        __bindings__ = []
        __fields__ = []
        _deps = {}
        
        def __init__(self):
            self.__dict__['__bindings__'] = []
            self.__dict__['__fields__'] = []
            self.__dict__['_deps'] = {}

        def _create_document_fragment(self):
            return MockDOMNode("fragment")

        def add_binding(self, binding):
            self.__bindings__.append(binding)

        def remove_binding(self, binding):
            if binding in self.__bindings__:
                self.__bindings__.remove(binding)

        import contextlib
        @contextlib.contextmanager
        def refrain(self):
            yield self

    # Mock child component class
    class MockChildComponent:
        @classmethod
        def mount(cls, container, replace=False, **kwargs):
            inst = MockComponent()
            inst_inner = MockDOMNode("div", parent=container)
            container.appendChild(inst_inner)
            inst.__dict__['__element__'] = inst_inner
            return inst

    MockComponent._registry["hero-card"] = MockChildComponent

    comp_inst = MockComponent()
    comp_inst.heroes = [{"id": 1}, {"id": 2}]

    # Create the template clone node (the custom element tag)
    clone_node = MockDOMNode("hero-card")

    # Create explicit key loop binding
    loop_binding = LoopBinding(
        component_instance=comp_inst,
        node=MockDOMNode("div"),
        ast_trees={},
        item="hero",
        collection="heroes",
        clone=clone_node,
        parent=parent,
        key="id"
    )

    # Initial populating/updates
    # ChildBindings represent hydrated state: instances hold LoopItems wrapping
    # the mounted component.
    inst1 = MockChildComponent.mount(MockDOMNode("hero-card", parent=parent))
    cb1 = ChildBinding(component_instance=comp_inst, node=inst1.__element__.parentNode, childclass=MockChildComponent, childinstance=inst1, loop_binding=loop_binding)
    comp_inst.add_binding(cb1)
    loop_binding.instances[1] = LoopItem(
        node=inst1.__element__.parentNode, bindings=[], key=1,
        scope=LoopScope({"hero": {"id": 1}}), instance=inst1, child_binding=cb1)
    parent.appendChild(inst1.__element__.parentNode)

    inst2 = MockChildComponent.mount(MockDOMNode("hero-card", parent=parent))
    cb2 = ChildBinding(component_instance=comp_inst, node=inst2.__element__.parentNode, childclass=MockChildComponent, childinstance=inst2, loop_binding=loop_binding)
    comp_inst.add_binding(cb2)
    loop_binding.instances[2] = LoopItem(
        node=inst2.__element__.parentNode, bindings=[], key=2,
        scope=LoopScope({"hero": {"id": 2}}), instance=inst2, child_binding=cb2)
    parent.appendChild(inst2.__element__.parentNode)

    # Ensure children are in the parent
    assert len(parent.childNodes) == 2

    # Now simulate adding a third hero (which triggers LIS reordering update)
    comp_inst.heroes = [{"id": 1}, {"id": 2}, {"id": 3}]

    # This should execute without throwing NotFoundError / ValueError
    loop_binding.update()

    # The parent should now have 3 nodes in its childNodes
    assert len(parent.childNodes) == 3


def test_unkeyed_loop_binding_with_custom_element():
    from basis.shared.bindings import LoopBinding, ChildBinding
    import contextlib

    class MockDOMNode:
        def __init__(self, tag_name="div", parent=None):
            self.tagName = tag_name
            self.parentNode = parent
            self.childNodes = []
            self.attributes = {}

        def getAttribute(self, key):
            return self.attributes.get(key)

        def setAttribute(self, key, value):
            self.attributes[key] = value

        def removeAttribute(self, key):
            self.attributes.pop(key, None)

        def getAttributeNames(self):
            return list(self.attributes.keys())

        def cloneNode(self, deep=True):
            cloned = MockDOMNode(self.tagName)
            cloned.attributes = self.attributes.copy()
            return cloned

        def remove(self):
            if self.parentNode and self in self.parentNode.childNodes:
                self.parentNode.childNodes.remove(self)
                self.parentNode = None

        @property
        def nextSibling(self):
            if not self.parentNode:
                return None
            idx = self.parentNode.childNodes.index(self)
            if idx < len(self.parentNode.childNodes) - 1:
                return self.parentNode.childNodes[idx + 1]
            return None

        def insertBefore(self, node, ref_node):
            if ref_node is not None:
                if ref_node not in self.childNodes:
                    raise ValueError("Child to insert before is not a child of this node")
                idx = self.childNodes.index(ref_node)
                self.childNodes.insert(idx, node)
            else:
                self.childNodes.append(node)
            node.parentNode = self
            return node

        def appendChild(self, node):
            self.childNodes.append(node)
            node.parentNode = self
            return node

    # Setup parent element
    parent = MockDOMNode("ui-tab-content")

    # Mock component instance
    class MockComponent:
        _registry = {}
        __bindings__ = []
        __fields__ = ["for", "in", "key"]
        _deps = {}
        
        def __init__(self):
            self.__dict__['__bindings__'] = []
            self.__dict__['__fields__'] = []
            self.__dict__['_deps'] = {}

        def _create_document_fragment(self):
            return MockDOMNode("fragment")

        def add_binding(self, binding):
            self.__bindings__.append(binding)

        def remove_binding(self, binding):
            if binding in self.__bindings__:
                self.__bindings__.remove(binding)

        @contextlib.contextmanager
        def refrain(self):
            yield self

    # Mock child component class
    mounted_attrs = []
    class MockChildComponent:
        @classmethod
        def mount(cls, container, replace=False, **kwargs):
            mounted_attrs.append(kwargs)
            inst = MockComponent()
            inst_inner = MockDOMNode("div", parent=container)
            container.appendChild(inst_inner)
            inst.__dict__['__element__'] = inst_inner
            return inst

    MockComponent._registry["team-entry"] = MockChildComponent

    comp_inst = MockComponent()
    comp_inst.teams = [{"name": "Alpha"}, {"name": "Beta"}]

    # Create the template clone node (the custom element tag)
    clone_node = MockDOMNode("team-entry")
    clone_node.setAttribute("for", "team")
    clone_node.setAttribute("in", "{$teams_model.items}")

    # Create unkeyed loop binding (no key arg -> fallback to index keys 0, 1...)
    loop_binding = LoopBinding(
        component_instance=comp_inst,
        node=MockDOMNode("div"),
        ast_trees={},
        item="team",
        collection="teams",
        clone=clone_node,
        parent=parent
    )

    loop_binding.update()

    # Verify initial mounting
    assert len(mounted_attrs) == 2
    assert mounted_attrs[0]["team"] == {"name": "Alpha"}
    assert mounted_attrs[1]["team"] == {"name": "Beta"}

    # Update item at index 1 without destroying nodes
    comp_inst.teams = [{"name": "Alpha"}, {"name": "Beta Updated"}]
    loop_binding.update()

    # Verify instance was preserved (index 1 key reused)
    assert 0 in loop_binding.instances
    assert 1 in loop_binding.instances
    # instances[1] is a LoopItem; the mounted component holds the props.
    assert loop_binding.instances[1].instance.team == {"name": "Beta Updated"}




