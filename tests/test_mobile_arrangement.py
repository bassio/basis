"""The responsive-by-default contract — a phone is an arrangement, not a fork.

M2.1 ships the mobile catalogue as *arrangements* of the families that already exist:
an app declares one component tree and the viewport rearranges it. That promise only
holds while four things stay true of every component, so each is checked here against
the component's own template and stylesheet rather than left to review:

1. an inline ``style`` carries custom-property declarations only — a literal
   ``width``/``top`` in the markup cannot be reached by a media query, so it silently
   pins desktop geometry onto a phone;
2. viewport queries come from ``basis.shared.styling``, never a hand-written
   width, because the same constant has to answer ``matchMedia`` for ``$device.tier``;
3. templates never branch on ``$device`` — the server has no viewport, so any such
   branch renders the wrong tree and disagrees with the client on hydration;
4. a component that declares a ``mobile_*`` dimension prop consumes it in a compact
   block, so a phone-sized override cannot rot into a dead parameter.

The mobile *scale* (``--control-height`` / ``--row-height`` / ``--page-gutter``) is
what lets a family be phone-sized without owning a query at all; the last test keeps
that scope and its declared defaults honest.
"""
import inspect
import re

import pytest

from _catalogue import (
    AUDITED,
    COMMENT,
    component_css,
    guarded_block_bodies,
    media_queries,
    strip_guarded_blocks,
)
from basis.shared.page import _VIEWPORT_BASE_CSS
from basis.shared.styling import (
    POINTER_QUERIES,
    PREFERENCE_QUERIES,
    compact_query,
    medium_query,
)

#: Queries that answer a *capability* rather than a viewport: allowed anywhere, because
#: they say nothing about the size the CSS believes it is rendering at.
_CAPABILITY_QUERIES = (*POINTER_QUERIES, *PREFERENCE_QUERIES)

_INLINE_STYLE = re.compile(r'style="([^"]*)"')
_OPAQUE_STYLE = re.compile(r"^\{(\w+)(?:\(\))?\}$")
_SCALE_VARS = ("--control-height", "--row-height", "--page-gutter")
_DECLARATION = re.compile(r"(--[a-z-]+)\s*:\s*([^;}]+);")
_SCALE_READING = re.compile(r"var\((--[a-z-]+)\s*,\s*([^)]+)\)")
_VAR_READ = re.compile(r"var\(\s*(--[a-z-]+)")


def _template(name):
    return AUDITED[name]._get_template_string() or ""


def _css(name):
    return COMMENT.sub("", component_css(AUDITED[name]))


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_templates_keep_layout_out_of_inline_styles(name):
    """Inline geometry is unreachable by a media query, so it pins the desktop."""
    for style in _INLINE_STYLE.findall(_template(name)):
        opaque = _OPAQUE_STYLE.match(style.strip())
        if opaque:
            assert opaque.group(1).endswith("_vars"), (
                f"{name} fills an inline style from {style}. A style the audit cannot "
                "read must come from a *_vars computed that emits custom properties, "
                "so the value stays overridable by a rule."
            )
            continue
        for declaration in (part.strip() for part in style.split(";")):
            if not declaration:
                continue
            assert declaration.startswith("--"), (
                f"{name} writes '{declaration}' into an inline style. Set a custom "
                "property and consume it from the stylesheet instead, or the phone "
                "cannot restyle it."
            )


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_viewport_queries_come_from_the_shared_contract(name):
    """A hand-written width lets the CSS and the ``$device`` fields disagree."""
    viewport_queries = {compact_query(), medium_query()}
    for query in media_queries(_css(name)):
        if query in _CAPABILITY_QUERIES:
            continue
        assert query in viewport_queries, (
            f"{name} uses '@media {query}'. Viewport queries must come from "
            "basis.shared.styling so the stylesheet and $device.tier agree."
        )


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_templates_do_not_branch_on_the_viewport(name):
    """The server cannot see the viewport, so markup must be viewport-invariant."""
    assert "$device" not in _template(name), (
        f"{name} reads $device in its template. The server renders the neutral, so "
        "the branch would disagree with the client on hydration; read the store in "
        "Python and pass the result down as a prop instead."
    )


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_declared_mobile_dimensions_are_consumed(name):
    """A ``mobile_*`` prop that no rule reads is a parameter that lies."""
    declared = [
        param
        for param in inspect.signature(AUDITED[name].__init__).parameters
        if param.startswith("mobile_")
    ]
    if not declared:
        return
    compact = guarded_block_bodies(_css(name), (compact_query(),))
    assert compact, f"{name} declares {declared} but has no compact block"
    assert re.search(r"var\(\s*--[a-z-]*-mobile-[a-z-]*", compact), (
        f"{name} declares {declared} but its compact block consumes no "
        "'--…-mobile-…' variable"
    )


def _page_scale():
    """The desktop values the page declares for the scale."""
    base = strip_guarded_blocks(_VIEWPORT_BASE_CSS, (compact_query(),))
    return dict(_DECLARATION.findall(base))


@pytest.mark.parametrize("name", sorted(AUDITED))
def test_scale_fallbacks_match_the_page_defaults(name):
    """The fallback *is* the desktop size, so a stale copy silently reflows desktops."""
    scale = _page_scale()
    for var, fallback in _SCALE_READING.findall(_css(name)):
        if var not in scale:
            continue
        assert fallback.strip() == scale[var], (
            f"{name} assumes {var} defaults to '{fallback.strip()}', but the page "
            f"declares '{scale[var]}'"
        )


def test_the_control_scale_has_readers():
    """A scale variable nothing reads is a contract nobody signed."""
    readers = {var for name in AUDITED for var in _VAR_READ.findall(_css(name))}
    assert "--control-height" in readers, (
        "no component reads --control-height, so the phone control height is unused"
    )


def test_the_page_owns_the_mobile_scale():
    """One scope on the page, so components inherit the phone scale for free."""
    base = strip_guarded_blocks(_VIEWPORT_BASE_CSS, (compact_query(),))
    compact = guarded_block_bodies(_VIEWPORT_BASE_CSS, (compact_query(),))
    for var in _SCALE_VARS:
        assert var in base, f"the page scale never declares {var}"
        assert var in compact, f"the compact scope never restates {var}"

    declared = dict(_DECLARATION.findall(base))
    override = dict(_DECLARATION.findall(compact))
    for var in _SCALE_VARS:
        assert declared[var] != override[var], (
            f"{var} is restated in the compact scope with its desktop value, so the "
            "phone scale is a no-op"
        )
