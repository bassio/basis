"""The touch/pointer contract — hover is decoration, never a dependency.

A touch engine answers ``:hover`` on tap, and unlike a mouse it never un-answers it:
an unguarded hover rule latches as a stuck style, and a hover-*revealed* affordance
is unreachable. The rules below are what M1.5 makes true of every component in the
catalogue, checked against each component's own CSS so they cannot rot:

1. every hover rule sits inside an ``@media (hover: hover)`` guard;
2. every component that suppresses the UA focus ring draws one of its own;
3. capability queries are the shared constants (``basis.shared.pointer``), not
   one-off literals;
4. coarse-pointer sizing goes through the ``--touch-target`` theme token.
"""
import importlib
import pkgutil
import re

import pytest

from basis.plugins.theme.default import DEFAULT_TOKENS
from basis.plugins.theme.schema import TOKEN_SLOTS, css_var
from basis.shared.base_component import BaseComponent
from basis.shared.pointer import (
    COARSE_QUERY,
    HOVER_QUERY,
    NO_HOVER_QUERY,
    POINTER_QUERIES,
    TOUCH_TARGET,
)

#: The plugin packages whose styles are audited (the chrome and the catalogue).
AUDITED_PACKAGES = ("basis.plugins.ui", "basis.plugins.shell")

_MEDIA_OPEN = re.compile(r"@media([^{]*)\{")
_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_QUERY = re.compile(r"@media\s*([^{]+)\{")


def _audited_classes():
    """Every component class defined under :data:`AUDITED_PACKAGES`."""
    found = {}
    for package_name in AUDITED_PACKAGES:
        package = importlib.import_module(package_name)
        for info in pkgutil.walk_packages(package.__path__, package_name + "."):
            module = importlib.import_module(info.name)
            for name in dir(module):
                obj = getattr(module, name)
                if (
                    isinstance(obj, type)
                    and issubclass(obj, BaseComponent)
                    and obj is not BaseComponent
                    and obj.__module__ == info.name
                    and obj.__tag__
                ):
                    found[f"{info.name}.{name}"] = obj
    return found


AUDITED = _audited_classes()


def _matching_brace(text, open_index):
    """Index of the ``}`` closing the ``{`` at *open_index*."""
    depth = 0
    for index in range(open_index, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return index
    raise AssertionError("unbalanced braces in component CSS")


def _without_guarded_blocks(css, queries):
    """*css* with every ``@media`` block whose query matches *queries* removed."""
    out, index = [], 0
    while True:
        match = _MEDIA_OPEN.search(css, index)
        if not match:
            out.append(css[index:])
            return "".join(out)
        out.append(css[index : match.start()])
        end = _matching_brace(css, match.end() - 1)
        if any(query in match.group(1) for query in queries):
            index = end + 1
        else:
            out.append(css[match.start() : end + 1])
            index = end + 1


def _with_guarded_blocks(css, queries):
    """Only the body of every ``@media`` block whose query matches *queries*."""
    bodies, index = [], 0
    while True:
        match = _MEDIA_OPEN.search(css, index)
        if not match:
            return "".join(bodies)
        end = _matching_brace(css, match.end() - 1)
        if any(query in match.group(1) for query in queries):
            bodies.append(css[match.end() : end])
        index = end + 1


def _media_queries(css):
    return [m.group(1).strip() for m in _QUERY.finditer(css)]


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_hover_rules_are_capability_guarded(name):
    """No component style latches a hover state on a device that cannot hover."""
    css = _COMMENT.sub("", AUDITED[name]._get_style_string() or "")
    unguarded = _without_guarded_blocks(css, (HOVER_QUERY,))
    assert ":hover" not in unguarded, (
        f"{name} styles :hover outside an '@media {HOVER_QUERY}' guard — it would "
        "stick after a tap"
    )


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_capability_queries_are_shared_constants(name):
    """A component repeats the query text, never invents its own."""
    css = AUDITED[name]._get_style_string() or ""
    for query in _media_queries(css):
        if "hover" in query or "pointer" in query:
            assert query in POINTER_QUERIES, (
                f"{name} uses '@media {query}', which is not one of "
                f"{POINTER_QUERIES}"
            )


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_suppressed_outline_is_replaced(name):
    """``outline: none`` without a ring of our own loses keyboard focus."""
    css = _COMMENT.sub("", AUDITED[name]._get_style_string() or "")
    if "outline: none" not in css:
        return
    assert ":focus-visible" in css or ":focus-within" in css, (
        f"{name} suppresses the UA focus ring but draws no :focus-visible / "
        ":focus-within indicator"
    )


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_coarse_pointer_rules_use_the_token(name):
    """Touch sizing follows the theme token, so an app can tune density."""
    css = _COMMENT.sub("", AUDITED[name]._get_style_string() or "")
    coarse = _with_guarded_blocks(css, (COARSE_QUERY,))
    if not coarse:
        return
    assert f"var(--touch-target, {TOUCH_TARGET})" in coarse, (
        f"{name} hard-codes a touch target instead of var(--touch-target, ...)"
    )


def test_touch_target_is_a_theme_token():
    """The 44px floor is themeable, and the schema is what emits it."""
    assert TOKEN_SLOTS["touch_target"] == "size"
    assert css_var("touch_target") == "--touch-target"
    assert DEFAULT_TOKENS.touch_target == TOUCH_TARGET


def test_scroll_area_keeps_a_scrollbar_without_hover():
    """``visibility="hover"`` must not mean "invisible" on a touch device."""
    from basis.plugins.ui.scroll_area.scroll_area import ScrollArea

    css = _COMMENT.sub("", ScrollArea._get_style_string() or "")
    baseline = _without_guarded_blocks(css, POINTER_QUERIES)
    assert 'visibility="hover"' in baseline
    assert "--scrollbar-thumb: transparent" in baseline

    fallback = _with_guarded_blocks(css, (NO_HOVER_QUERY,))
    assert 'visibility="hover"' in fallback, "no no-hover fallback for the hover mode"
    assert "--scrollbar-thumb: var(" in fallback


def test_the_audit_covers_the_catalogue():
    """A guard against the walk silently finding nothing."""
    assert len(AUDITED) >= 25
