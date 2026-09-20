"""``{attr}="{None}"`` — an attribute whose expression says "not applicable".

A ``None`` value removes the attribute. It used to write the literal ``"None"`` into the
DOM, which is never what an optional attribute means: a ``<link>`` with
``sizes="None"`` is wrong markup, and no caller wants a stringified sentinel in their
page. Absence is the only honest rendering of "this attribute does not apply here".
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

_STYLE = re.compile(r"<style.*?</style>", re.DOTALL)


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes


class _Owner(Component):
    sizes = None

    def template(self):
        """
        <div class="root">
            <link class="probe" rel="icon" href="/favicon.png" sizes="{sizes}" />
        </div>
        """


def _render(root_component, entry_module):
    app = Basis()
    app.bootstrap()
    app.include_page(
        "/", page_cls=_synthesize_page(root_component, entry_module=entry_module)
    )
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    return _STYLE.sub("", resp.text)


def test_a_none_value_removes_the_attribute():
    html = _render(_Owner, "/test_none_attr_off.py")

    # Scoped to the element: the page's viewport meta legitimately contains the
    # substring "sizes" ("interactive-widget=resizes-content").
    probe = re.search(r"<link class=\"probe\"[^>]*>", html)
    assert probe is not None, html
    assert "sizes" not in probe.group(0)
    assert "None" not in probe.group(0)


def test_a_value_keeps_the_attribute():
    class Sized(_Owner):
        sizes = "32x32"

    html = _render(Sized, "/test_none_attr_on.py")

    assert re.search(r'<link class="probe"[^>]* sizes="32x32"', html)


def test_flipping_between_none_and_a_value_adds_and_removes():
    """A value that goes away must *remove* an attribute the binding set earlier."""
    from basis.shared.bindings import AttributeBinding
    from basis.shared.element import Element

    class Probe(Component):
        sizes = "48x48"

        def template(self):
            """<link rel="icon" href="/favicon.png" sizes="{sizes}" />"""

    probe = Probe.mount(Element("div", attrs={}, children=[]))
    binding = next(
        b for b in probe.__bindings__ if isinstance(b, AttributeBinding)
    )
    node = probe.__element__
    assert node.getAttribute("sizes") == "48x48"

    probe.sizes = None
    binding.update()
    assert node.getAttribute("sizes") is None

    probe.sizes = "32x32"
    binding.update()
    assert node.getAttribute("sizes") == "32x32"
