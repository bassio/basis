"""The viewport breakpoint contract — one source for the DAG fields and the CSS.

A viewport class is a *client* fact: the server has no rendering surface, so it can
only agree on a neutral and let the browser correct it. That neutral has to match
whatever the stylesheet does at the same viewport, or the first paint disagrees with
itself — which is why the breakpoint numbers live here, in one place, and are derived
into both forms:

- :func:`compact_query` / :func:`medium_query` — the ``matchMedia`` strings a
  ``Store`` field declares (see ``basis/shared/device.py``);
- :func:`compact_media` / :func:`medium_media` / :func:`compact_block` — the same
  queries as CSS ``@media`` text for component styles.

Because both forms come from one constant, CSS and ``matchMedia`` answer the *same*
string: layout reflow and the ``$device`` fields cannot drift apart.

Tiers (``$device.tier``): ``compact`` ≤ 767px, ``medium`` 768–1023px, ``regular``
≥ 1024px. Only the boundaries are framework knowledge; what a component *does* at
each tier is the component's business (see ``basis.plugins.shell``).

The ``max-width``/``min-width`` form is deliberate: it predates Media Queries Level 4
range syntax by a decade, and phones are exactly where old engines turn up. An
unparsed query would silently answer "no" and leave the desktop frame on a phone.
"""

#: Compact covers every phone viewport (and a phone in landscape). 768–1023 is the
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
