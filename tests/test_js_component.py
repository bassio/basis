"""
Server-side tests for the ``@js_component`` decorator / ``JsComponent`` base
(ROADMAP-AMBITIOUS.md Bet 5; JS-COMPONENT-PLAN.md).

Server-side only: verifies the decorator metadata, the MRO injection (user lifecycle
overrides win), the registry, that a decorated component still SSR-renders its
deterministic template with every JS path inert, and the ``/basis/js`` mount. Client
behaviour (module loading, ``boot_js``, the event bridge) is exercised by the browser
A/B gate / Playwright harness.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.page import _synthesize_page
from basis.shared.component import Component
from basis.shared.js_component import (
    JsComponent,
    JsComponentRegistry,
    js_component,
)


@pytest.fixture(autouse=True)
def _clean_state():
    saved_by_tag = dict(JsComponentRegistry._by_tag)
    saved_by_module = {k: set(v) for k, v in JsComponentRegistry._by_module.items()}
    saved_name_to_url = dict(JsComponentRegistry._name_to_url)
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    yield
    JsComponentRegistry._by_tag.clear()
    JsComponentRegistry._by_module.clear()
    JsComponentRegistry._name_to_url.clear()
    JsComponentRegistry._by_tag.update(saved_by_tag)
    JsComponentRegistry._by_module.update(saved_by_module)
    JsComponentRegistry._name_to_url.update(saved_name_to_url)
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes


@js_component(module="/basis/js/fake/index.js", exports=["Widget"])
class FakeEditor(Component):
    __tag__ = "ui-fake-editor"
    value = ""

    def boot_js(self, module):
        self.widget = None

    def sync_js(self):
        self.synced_value = self.value


def test_decorator_sets_metadata_and_registers():
    assert FakeEditor.__js_module__ == "/basis/js/fake/index.js"
    assert FakeEditor.__js_exports__ == ("Widget",)
    assert FakeEditor.__js_component__ is True
    assert JsComponentRegistry.classes_for_module("/basis/js/fake/index.js") == (
        FakeEditor,
    )
    assert "/basis/js/fake/index.js" in JsComponentRegistry.modules()


def test_decorator_injects_jscomponent_below_the_class():
    assert issubclass(FakeEditor, JsComponent)
    # The user class must come BEFORE JsComponent in the MRO so its own
    # lifecycle-hook overrides (on_mounted / on_hydrated / destroy) still win.
    assert FakeEditor.__mro__.index(FakeEditor) < FakeEditor.__mro__.index(JsComponent)


def test_explicit_jscomponent_subclass_is_not_wrapped():
    @js_component(module="/basis/js/x.js")
    class Direct(JsComponent):
        __tag__ = "ui-direct"

    assert Direct.__mro__[1] is JsComponent
    assert Direct.__js_module__ == "/basis/js/x.js"


def test_bridge_prop_set_is_inert_on_server():
    """Without a client JS runtime (``_js_ready`` never becomes True), assigning a
    bridge prop must not call ``sync_js`` — SSR/headless safe."""
    inst = FakeEditor()
    inst.value = "hello"
    assert not hasattr(inst, "synced_value")


def test_ssr_renders_placeholder_with_js_inert():
    """The decorated component SSR-renders its template; boot_js/sync_js never run
    server-side (on_mounted is a no-op off the client)."""
    calls = {"boot": 0, "sync": 0}

    @js_component(module="/basis/js/fake2.js")
    class PlaceholderEditor(Component):
        __tag__ = "ui-placeholder-editor"
        value = ""

        def template(self):
            """
            <div class="cm-host">{value}</div>
            """

        def boot_js(self, module):
            calls["boot"] += 1

        def sync_js(self):
            calls["sync"] += 1

    class Root(Component):
        def template(self):
            """
            <div class="root">
                <ui-placeholder-editor value="hi"></ui-placeholder-editor>
            </div>
            """

    app = Basis()
    app.bootstrap()
    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="test.page"))
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ui-placeholder-editor" in resp.text
    assert "hi" in resp.text
    # JS hooks are inert on the server.
    assert calls == {"boot": 0, "sync": 0}


def test_framework_manifest_registers_js_component_modules():
    """The client VFS manifest must include the @js_component framework modules.

    ``VFSRegistry.add_framework_files`` registers framework client/shared files from a
    hardcoded list — a new module MUST be added there or the client can't import it
    ("No module named 'basis.shared.js_component'" at boot).
    """
    app = Basis()
    app.bootstrap()
    client = TestClient(app)
    d = client.get("/pyscript.json").json()
    files = d.get("files", {})
    assert any(k.endswith("/basis/shared/js_component.py") for k in files)
    assert any(k.endswith("/basis/client/js_bridge.py") for k in files)


def test_js_component_name_default_and_explicit():
    @js_component(module="/basis/js/foo/index.js")
    class Foo(Component):
        __tag__ = "ui-foo-x"

        def template(self):
            """<div>foo</div>"""

        def boot_js(self, module):
            pass

    @js_component(module="/basis/js/bar/index.js", name="custom_name")
    class Bar(Component):
        __tag__ = "ui-bar-x"

        def template(self):
            """<div>bar</div>"""

        def boot_js(self, module):
            pass

    assert Foo.__js_name__ == "foo"
    assert Bar.__js_name__ == "custom_name"
    assert JsComponentRegistry.js_modules()["foo"] == "/basis/js/foo/index.js"
    assert JsComponentRegistry.js_modules()["custom_name"] == "/basis/js/bar/index.js"


def test_js_component_name_collision_raises():
    @js_component(module="/basis/js/dup1.js", name="dup")
    class C1(Component):
        __tag__ = "ui-dup1"

        def template(self):
            """<div>c1</div>"""

        def boot_js(self, module):
            pass

    with pytest.raises(ValueError):
        @js_component(module="/basis/js/dup2.js", name="dup")
        class C2(Component):
            __tag__ = "ui-dup2"

            def template(self):
                """<div>c2</div>"""

            def boot_js(self, module):
                pass


def test_page_js_modules_are_per_page():
    @js_component(module="/basis/js/chartlib/index.js", name="chartlib")
    class ChartLib(Component):
        __tag__ = "ui-chartlib"

        def template(self):
            """<div>chart</div>"""

        def boot_js(self, module):
            pass

    class WithEditor(Component):
        def template(self):
            """
            <div class="root"><ui-chartlib></ui-chartlib></div>
            """

    class NoEditor(Component):
        def template(self):
            """
            <div class="root"><p>plain</p></div>
            """

    app = Basis()
    app.bootstrap()
    app.include_page("/with-editor", page_cls=_synthesize_page(WithEditor, entry_module="test.page"))
    app.include_page("/no-editor", page_cls=_synthesize_page(NoEditor, entry_module="test.page"))
    client = TestClient(app)

    d = client.get("/pyscript.json?url=/with-editor").json()
    assert d["js_modules"]["main"] == {"chartlib": "/basis/js/chartlib/index.js"}

    d2 = client.get("/pyscript.json?url=/no-editor").json()
    assert "js_modules" not in d2


def test_unserved_js_module_warns(monkeypatch):
    from basis.server import vfs

    warnings = []

    class _SpyLogger:
        def warning(self, msg, *args, **kwargs):
            warnings.append(str(msg))

        def info(self, msg, *args, **kwargs):
            pass

        def error(self, msg, *args, **kwargs):
            pass

        def debug(self, msg, *args, **kwargs):
            pass

    monkeypatch.setattr(vfs, "logger", _SpyLogger())

    @js_component(module="/myapp/js/ghost.js", name="ghost")
    class Ghost(Component):
        __tag__ = "ui-ghost"

        def template(self):
            """<div>ghost</div>"""

        def boot_js(self, module):
            pass

    class Root(Component):
        def template(self):
            """
            <div class="root"><ui-ghost></ui-ghost></div>
            """

    app = Basis()
    app.bootstrap()
    app.include_page("/", page_cls=_synthesize_page(Root, entry_module="test.page"))
    client = TestClient(app)
    client.get("/pyscript.json?url=/")
    assert any("not served by any registered mount" in w for w in warnings)
