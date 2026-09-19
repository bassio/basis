"""
Tests for ``ui-text-input`` (``basis.plugins.ui.input``).

The field's HTML type is a prop, and it cannot be spelled ``type``: inside a template a
bare ``{type}`` resolves to the builtin, so the prop is ``input_type`` and the template
reads the prop. Anything else leaves the attribute empty — and prints an eval error on
every render — while looking like it worked whenever the caller happened to pass the
builtin name through as an unmapped attribute.
"""
import re

import pytest
from fastapi.testclient import TestClient

from basis.server.app import Basis
from basis.shared.component import Component
from basis.shared.page import _synthesize_page

import basis.plugins.ui.input.input  # noqa: F401
from basis.plugins.ui.input.input import TextInput

_STYLE = re.compile(r"<style.*?</style>", re.DOTALL)
_FIELD = re.compile(r"<input\b[^>]*>")


@pytest.fixture(autouse=True)
def _clean_app_state():
    saved_global_stores = list(Basis._global_stores)
    saved_component_routes = list(Basis._component_routes)
    yield
    Basis._global_stores = saved_global_stores
    Basis._component_routes = saved_component_routes


def _render(root_component, entry_module, capsys):
    app = Basis()
    app.bootstrap()
    app.include_page(
        "/", page_cls=_synthesize_page(root_component, entry_module=entry_module)
    )
    resp = TestClient(app).get("/")
    assert resp.status_code == 200
    captured = capsys.readouterr()
    assert "eval error" not in captured.out + captured.err, captured.out
    return _STYLE.sub("", resp.text)


def _field(html):
    fields = _FIELD.findall(html)
    assert len(fields) == 1, fields
    return fields[0]


class _Default(Component):
    def template(self):
        """
        <ui-text-input label="Plain" placeholder="Name"></ui-text-input>
        """


class _Typed(Component):
    def template(self):
        """
        <ui-text-input label="Email" input_type="email"></ui-text-input>
        """


class _StrayBuiltin(Component):
    def template(self):
        """
        <ui-text-input label="Email" type="email"></ui-text-input>
        """


class _PickerField(Component):
    def template(self):
        """
        <ui-text-input label="Date" readonly="true"></ui-text-input>
        """


def test_the_tag():
    assert TextInput.__tag__ == "ui-text-input"


def test_the_prop_is_input_type_because_type_is_a_builtin():
    assert TextInput.input_type == "text"
    assert not hasattr(TextInput, "type"), "a prop named after a builtin cannot be read"


def test_the_declared_default_reaches_the_field(capsys):
    html = _render(_Default, "/test_input_default.py", capsys)

    field = _field(html)
    assert 'type="text"' in field, field
    assert 'placeholder="Name"' in field


def test_input_type_drives_the_field(capsys):
    html = _render(_Typed, "/test_input_type.py", capsys)

    field = _field(html)
    assert 'type="email"' in field, field
    assert "input_type" not in field, "the prop must not leak onto the element"


def test_an_attribute_named_after_the_builtin_is_not_a_prop(capsys):
    """``type=`` stays an ordinary unmapped attribute — ``input_type`` is the API."""
    html = _render(_StrayBuiltin, "/test_input_stray_type.py", capsys)

    field = _field(html)
    assert 'type="text"' in field, field


def test_readonly_renders_the_boolean_attribute(capsys):
    html = _render(_PickerField, "/test_input_readonly.py", capsys)

    field = _field(html)
    assert " readonly" in field, field
