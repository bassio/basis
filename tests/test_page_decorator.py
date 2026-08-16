"""
Tests for the Page / root-component API:

* ``@app.page`` decorates a root Component, synthesizes a page, serves it at ``path``.
* ``@app.page`` rejects a ``Page`` subclass (a Page is the shell, not a root).
* ``@app.page`` rejects a custom shell that already declares ``root_component``/``stores``.
* ``app.include_page(path, page_cls=...)`` registers a Page; also usable as a decorator.
* ``include_page`` requires a Page subclass.
* ``Page`` defaults: ``root_component = None`` (abstract/static shell), ``stores = []``.
* Synthesized pages are NOT emitted into ``#basis-entrypoint-imports``.
"""
import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component


def test_page_decorator_serves_at_root_by_default():
    app = Basis()

    @app.page
    class Hello(Component):
        """<div>Hi {name}</div>"""
        name = "World"

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Hi World" in resp.text


def test_page_decorator_serves_at_custom_path():
    app = Basis()

    @app.page(path="/hello")
    class Hello(Component):
        """<div>Hi {name}</div>"""
        name = "World"

    client = TestClient(app)
    resp = client.get("/hello")
    assert resp.status_code == 200
    assert "Hi World" in resp.text
    # Not mounted at the default path.
    assert client.get("/").status_code == 404


def test_page_decorator_returns_component_class():
    app = Basis()

    @app.page(path="/")
    class Hello(Component):
        """<div>Hi</div>"""

    # The decorator returns the decorated class, not the app.
    assert Hello is not app
    assert issubclass(Hello, Component)


def test_page_decorator_rejects_page_subclass():
    from basis.shared.page import Page

    app = Basis()

    class MyPage(Page):
        pass

    with pytest.raises(TypeError, match="is a Page, not a root component"):
        app.page(MyPage)


def test_page_decorator_rejects_shell_with_own_root():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>hi</div>"""

    class Shell(Page):
        root_component = Root

    with pytest.raises(ValueError, match="already declares"):
        app.page(Root, path="/x", page_cls=Shell)


def test_page_decorator_rejects_shell_with_stores():
    from basis.shared.page import Page

    app = Basis()

    class Root(Component):
        """<div>hi</div>"""

    class Shell(Page):
        stores = ["s"]

    with pytest.raises(ValueError, match="already declares"):
        app.page(Root, path="/x", page_cls=Shell)


def test_include_page_requires_a_page_subclass():
    app = Basis()
    app.bootstrap()

    class NotAPage(Component):
        """<div>hi</div>"""

    with pytest.raises(TypeError, match="requires a Page subclass"):
        app.include_page("/x", page_cls=NotAPage)


def test_include_page_declarative_root_from_page_cls():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>Declarative root</div>"""

    class MyPage(Page):
        title = "Declarative"
        root_component = Root
        entry_module = "/test_root.py"

    app.include_page("/dec", page_cls=MyPage)

    client = TestClient(app)
    resp = client.get("/dec")
    assert resp.status_code == 200
    assert "Declarative root" in resp.text
    assert "<title>Declarative</title>" in resp.text


def test_include_page_decorator_form():
    from basis.shared.page import Page

    app = Basis()
    app.bootstrap()

    class Root(Component):
        """<div>Decorator root</div>"""

    @app.include_page("/decorator")
    class DecoratorPage(Page):
        title = "Decorator"
        root_component = Root
        entry_module = "/test_root.py"

    # include_page returns the Page class so the name stays bound to it.
    assert issubclass(DecoratorPage, Page)

    client = TestClient(app)
    resp = client.get("/decorator")
    assert resp.status_code == 200
    assert "Decorator root" in resp.text
    assert "<title>Decorator</title>" in resp.text


def test_page_defaults_are_abstract_shell():
    from basis.shared.page import Page

    assert Page.root_component is None
    assert Page.stores == []


def test_page_subclass_carries_root_and_stores():
    from basis.shared.page import Page

    class Root(Component):
        """<div>hi</div>"""

    class Concrete(Page):
        root_component = Root
        stores = ["one", "two"]

    assert Concrete.root_component is Root
    assert Concrete.stores == ["one", "two"]


def test_synthesized_page_not_in_entrypoint_imports():
    app = Basis()

    @app.page(path="/")
    class Home(Component):
        """<div>Hi</div>"""

    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    # The synthesized class is server-side shell config only — its (unimportable)
    # name must not leak into #basis-entrypoint-imports.
    assert "HomePage" not in resp.text
