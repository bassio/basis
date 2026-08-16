import pytest
import inspect
from basis.shared.component import Component, scoped
from basis.shared.base_component import BaseComponent


def test_classmethod_template_and_style_no_docstrings():
    class TestComp1(Component):
        __tag__ = "test-comp-1"

        @classmethod
        def template(cls):
            return "<div>Classmethod Template</div>"

        @classmethod
        def style(cls):
            return "div { color: blue; }"

    assert TestComp1._get_template_string() == "<div>Classmethod Template</div>"
    assert TestComp1._get_style_string() == "div { color: blue; }"


def test_classmethod_template_and_style_with_docstrings():
    class TestComp2(Component):
        __tag__ = "test-comp-2"

        @classmethod
        def template(cls):
            """<div>Docstring Classmethod Template</div>"""
            pass

        @classmethod
        def style(cls):
            """div { color: red; }"""
            pass

    assert TestComp2._get_template_string().strip() == "<div>Docstring Classmethod Template</div>"
    assert TestComp2._get_style_string().strip() == "div { color: red; }"


def test_regular_method_docstrings():
    class TestComp3(Component):
        __tag__ = "test-comp-3"

        def template(self):
            """<div>Regular Method Template</div>"""
            pass

        def style(self):
            """div { color: green; }"""
            pass

    assert TestComp3._get_template_string().strip() == "<div>Regular Method Template</div>"
    assert TestComp3._get_style_string().strip() == "div { color: green; }"


def test_scoped_decorator_combinations():
    # 1. @classmethod on the outside
    class TestScoped1(Component):
        __tag__ = "test-scoped-1"

        @classmethod
        def template(cls):
            return "<div>1</div>"

        @classmethod
        @scoped
        def style(cls):
            return "span { font-weight: bold; }"

    # 2. @scoped on the outside
    class TestScoped2(Component):
        __tag__ = "test-scoped-2"

        @classmethod
        def template(cls):
            return "<div>2</div>"

        @scoped
        @classmethod
        def style(cls):
            return "span { font-weight: bold; }"

    # 3. Regular method (not classmethod) with @scoped
    class TestScoped3(Component):
        __tag__ = "test-scoped-3"

        @classmethod
        def template(cls):
            return "<div>3</div>"

        @scoped
        def style(self):
            """span { font-weight: bold; }"""
            pass

    # Assert style content matches scoped format
    expected_style1 = "@scope (test-scoped-1) {\nspan { font-weight: bold; }\n}"
    expected_style2 = "@scope (test-scoped-2) {\nspan { font-weight: bold; }\n}"
    expected_style3 = "@scope (test-scoped-3) {\nspan { font-weight: bold; }\n}"

    assert TestScoped1._get_style_string() == expected_style1
    assert TestScoped2._get_style_string() == expected_style2
    assert TestScoped3._get_style_string().strip() == expected_style3
