"""The touch/pointer contract — hover is decoration, never a dependency.

A touch engine answers ``:hover`` on tap, and unlike a mouse it never un-answers it:
an unguarded hover rule latches as a stuck style, and a hover-*revealed* affordance
is unreachable. The rules below are what M1.5 makes true of every component in the
catalogue, checked against each component's own CSS so they cannot rot:

1. every hover rule sits inside an ``@media (hover: hover)`` guard;
2. every component that suppresses the UA focus ring draws one of its own;
3. capability queries are the shared constants (``basis.shared.styling``), not
   one-off literals;
4. coarse-pointer sizing goes through the ``--touch-target`` theme token.
"""
import pytest

from _catalogue import (
    AUDITED,
    COMMENT as _COMMENT,
    guarded_block_bodies as _with_guarded_blocks,
    media_queries as _media_queries,
    strip_guarded_blocks as _without_guarded_blocks,
)
from basis.plugins.theme.default import DEFAULT_TOKENS
from basis.plugins.theme.schema import TOKEN_SLOTS, css_var
from basis.shared.styling import (
    COARSE_QUERY,
    HOVER_QUERY,
    NO_HOVER_QUERY,
    POINTER_QUERIES,
    TOUCH_TARGET,
)


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
