"""``<input {disabled}>`` — a boolean attribute driven by a component field.

The attribute's NAME is the expression: the element keeps the attribute while the field
is truthy and drops it otherwise. This is what makes ``{disabled}``/``{checked}`` on a
control mean "the owner says so" rather than "present forever", and it is the only way
to express a boolean attribute at all — a *valued* ``disabled="false"`` still disables
the control, because HTML boolean attributes are true whenever they are present.
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
    disabled = "true"

    def template(self):
        """
        <div class="root">
            <input class="probe" {disabled} />
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


def test_a_truthy_field_keeps_the_attribute():
    html = _render(_Owner, "/test_bool_attr_on.py")

    assert re.search(r'<input class="probe"[^>]* disabled', html)


def test_a_falsy_field_drops_the_attribute():
    class Enabled(_Owner):
        disabled = ""

    html = _render(Enabled, "/test_bool_attr_off.py")

    assert "disabled" not in html


def test_an_expression_beside_the_attribute_name_still_drives_it():
    """The tidy spelling of a computed boolean: ``{selected}="{expr}"``."""
    class Month(Component):
        current = 3

        def template(self):
            """
            <div class="root">
                <select>
                    <option value="1" {selected}="{current == 1}">Jan</option>
                    <option value="3" {selected}="{current == 3}">Mar</option>
                </select>
            </div>
            """

    html = _render(Month, "/test_bool_attr_expr.py")

    selected = re.findall(r"<option\b[^>]*>", html)
    assert len(selected) == 2, selected
    assert " selected" not in selected[0]
    assert " selected" in selected[1]
