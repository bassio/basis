"""The stylesheet contract — the queries and markers a component's CSS is written in.

Two clients have to agree on "narrow" and on "can hover": the stylesheet, which reflows
the layout, and the reactive fields (``basis.shared.device``), which let Python make the
same decision. They agree only if both are derived from one constant, which is why the
boundaries and the query strings live here and are handed out in both forms — the
``matchMedia`` string a ``Store`` field declares, and the ``@media`` / ``@container``
text a component's stylesheet is built from.

Hover is **decoration** in Basis. It may add emphasis; it may never be the only way to
see or reach something, because a touch engine answers ``:hover`` on tap and — unlike a
mouse — never un-answers it. An unguarded hover rule therefore latches as a stuck style
on a phone, and a hover-*revealed* affordance is simply unreachable. ``pointer``
answers the other question, the SIZING one ("is the primary input a finger?"): a
touchscreen laptop whose primary pointer is a mouse stays ``fine`` and keeps its dense
controls, while a phone is ``coarse`` and gets touch targets.

Nothing here imports framework machinery, so a module that only writes CSS can import
it for free.
"""

#: Compact covers every phone viewport (a phone in landscape included). 768–1023 is the
#: tablet band; ``regular`` is everything wider.
COMPACT_MAX_WIDTH = 767
MEDIUM_MAX_WIDTH = 1023

#: The tier names ``$device.tier`` can take, narrowest first.
TIERS = ("compact", "medium", "regular")


def compact_query() -> str:
    """The ``matchMedia`` query answering "this is a phone-class viewport"."""
    return f"(max-width: {COMPACT_MAX_WIDTH}px)"


def medium_query() -> str:
    """The ``matchMedia`` query answering "this is a tablet-class viewport"."""
    return (
        f"(min-width: {COMPACT_MAX_WIDTH + 1}px) "
        f"and (max-width: {MEDIUM_MAX_WIDTH}px)"
    )


def compact_media() -> str:
    """The compact query as an ``@media`` prelude."""
    return f"@media {compact_query()}"


def medium_media() -> str:
    """The medium query as an ``@media`` prelude."""
    return f"@media {medium_query()}"


def compact_block(css: str) -> str:
    """Wrap *css* so it applies only in the compact viewport class.

    Lets a component keep its compact rules as ordinary CSS text next to the rest of
    its stylesheet, without interpolating the query into the string by hand::

        style = _BASE_CSS + compact_block(_COMPACT_CSS)

    The ``max-width``/``min-width`` form is deliberate: it predates Media Queries Level 4
    range syntax by a decade, and phones are exactly where old engines turn up. An
    unparsed query would silently answer "no" and leave the desktop frame on a phone.
    """
    return f"@media {compact_query()} {{\n{css}\n}}"


def container_block(name: str, css: str) -> str:
    """Wrap *css* so it applies only while the nearest ``name`` container is narrow.

    The box-scope sibling of :func:`compact_block`, at the same boundary: a component can
    be compact because of the room it was *given* rather than because of the device. A
    list inside a 240px sidebar and the same list inside a 1040px pane are two different
    layouts at one viewport, and only a container query can tell them apart.

    The querying element may not be its own container, so the component that *wants* the
    answer does not declare it — the box that owns the room does::

        .shell-sidebar {
            container-type: inline-size;
            container-name: pane;
        }

    ``container-type: inline-size`` sizes the box as if it had no contents, which is free
    for a box whose width is already definite (a set width, a flex basis, a grid track) and
    fatal for a content-sized one: declaring it there collapses the box to zero. That is
    why the framework names no containers of its own and each caller opts in where it
    knows the width.
    """
    return f"@container {name} (max-width: {COMPACT_MAX_WIDTH}px) {{\n{css}\n}}"


#: A fine pointer that can hover — the desktop/laptop default.
HOVER_QUERY = "(hover: hover)"

#: No hover at all: a phone, or a device whose primary pointer cannot hover.
NO_HOVER_QUERY = "(hover: none)"

#: The primary input is a finger.
COARSE_QUERY = "(pointer: coarse)"

#: Every pointer query the framework speaks (the audit test checks component CSS
#: against this set).
POINTER_QUERIES = (HOVER_QUERY, NO_HOVER_QUERY, COARSE_QUERY)

#: The user asks the system for less movement.
REDUCED_MOTION_QUERY = "(prefers-reduced-motion: reduce)"

#: Every user-preference query the framework speaks (the mobile audit allows these
#: alongside :data:`POINTER_QUERIES`).
PREFERENCE_QUERIES = (REDUCED_MOTION_QUERY,)

#: The touch-target floor, and the fallback for the ``--touch-target`` theme token:
#: a page rendered without a theme provider still gets finger-sized controls.
TOUCH_TARGET = "44px"


def reduced_motion_block(css: str) -> str:
    """Wrap *css* so it applies only while the user asks for less movement.

    Endless or sweeping motion (a shimmer, an indeterminate bar) is the case this
    exists for: a loading placeholder still has to say "working" without moving.
    """
    return f"@media {REDUCED_MOTION_QUERY} {{\n{css}\n}}"


def scoped(func):
    """Mark a component's style method as encapsulated in a CSS ``@scope (...)`` block.

    The scope root is the component's own tag, read at render time, so a subclass that
    ships an alias tag is styled by the same rule.
    """
    func.__scoped__ = True
    return func


def extra_style(func):
    """Mark a method as an *additional* (additive) style block.

    Unlike ``style()`` — which a subclass overrides to REPLACE the inherited
    stylesheet — an ``@extra_style`` block is injected as its own ``<style>``
    element *after* the component's main stylesheet, so a subclass can restyle
    a parent component without copying the parent's whole ``style()``::

        class MyTitleBar(TitleBar):
            @extra_style
            def tweaks(self):
                \"\"\"
                shell-title-bar { background: var(--accent-color); }
                \"\"\"

    The same conventions as ``style()`` apply (docstring, classmethod, or a
    plain string), it supports ``{expr}`` dynamic fields (see the styling guide),
    and it may be combined with ``@scoped`` to keep the block encapsulated.
    """
    func.__extra_style__ = True
    return func


__all__ = [
    "COMPACT_MAX_WIDTH",
    "MEDIUM_MAX_WIDTH",
    "TIERS",
    "compact_query",
    "medium_query",
    "compact_media",
    "medium_media",
    "compact_block",
    "container_block",
    "HOVER_QUERY",
    "NO_HOVER_QUERY",
    "COARSE_QUERY",
    "POINTER_QUERIES",
    "REDUCED_MOTION_QUERY",
    "PREFERENCE_QUERIES",
    "TOUCH_TARGET",
    "reduced_motion_block",
    "scoped",
    "extra_style",
]
