"""The ``List`` — rows that read as one list, and the row that fills it.

A list is the shape a phone lives in: stacked, full-width, every row a target. The
family is therefore two components — the container and the row — because that is also
the seam a *windowed* renderer needs: the rows are ordinary children, so a future
virtualised list can mount and unmount them without any call site changing. Faking that
here would mean shipping a renderer nobody asked for; the seam is the honest part.

The row is the whole target, not the words in it. A row's link stretches over the row's
box by CSS, so a finger hits the row wherever it lands while the link keeps its own text
as its accessible name.

A row takes its content two ways, because the framework renders a looped component
differently from a looped element: per-item data reaches a *component* loop child as
attributes, and its slotted content belongs to nobody. So ``label``/``href`` carry the
common row — one declaration per note, no wrapper — while the slots carry a rich row
for a loop written around a plain element.

Rows are spacing-free by construction: leading and trailing are *slots*, so a row that
declares neither carries no empty boxes and no stray gaps. A section header is the same
row with ``arrangement="header"`` — one declaration, sticky at every viewport, because
a header's job does not change with the width even though a phone is where it earns its
keep.
"""
from basis.shared.styling import compact_block
from basis.shared.component import Component, scoped
from basis.shared.reactive import computed

_BASE_CSS = """
:scope {
    display: block;
}

.ui-list {
    display: flex;
    flex-direction: column;
    width: 100%;
    /* Never taller than the box it was given: a list inside a flex pane has to be able
       to scroll instead of pushing its parent open. */
    min-height: 0;
}

/* The hairline between rows belongs to the list, not to the row: the list is what knows
   which row is first, and a loop may wrap each row it renders. */
.ui-list .ui-list-row {
    border-top: 1px solid var(--border-soft, #EAEAED);
}

.ui-list > :first-child .ui-list-row:first-child {
    border-top: 0;
}
"""

_ITEM_BASE_CSS = """
/* The host is inert: the row's box is the one element below, so a row is one box in the
   list's column whatever tag a subclass ships. */
:scope {
    display: contents;
}

.ui-list-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    position: relative;
    /* The declared height *is* the row's height: padding and the hairline live inside it,
       so --row-height means one thing on both sides of the compact breakpoint. */
    box-sizing: border-box;
    min-height: var(--row-height, 2rem);
    padding: 0.5rem 0.75rem;
    color: inherit;
}

/* A slot the caller left unused keeps its placeholder element in the DOM; it must not
   take part in the row's gaps. */
.ui-list-row > slot {
    display: contents;
}

.ui-list-trailing {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    /* Fills the free space, so whatever lands here is pushed to the row's end. */
    margin-inline-start: auto;
}

.ui-list-content {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
    color: inherit;
    text-decoration: none;
}

/* A row whose content is a link lets the finger hit the whole row: the anchor stretches
   over the row's box. A trailing action lives in its own element and keeps its area. */
.ui-list-content > a::after,
.ui-list-row > a::after {
    content: "";
    position: absolute;
    inset: 0;
}

@media (hover: hover) {
    .ui-list-row:hover {
        background: var(--hover-bg, rgba(0, 0, 0, 0.04));
    }
}

.ui-list-row[data-selected="true"] {
    background: var(--accent-bg, rgba(0, 0, 0, 0.05));
}

/* A section header sticks to the top of whatever scrolls it — the list's own scroll box,
   normally, so a frame with sticky chrome of its own offsets it with --list-sticky-top. */
.ui-list-row[data-arrangement="header"] {
    position: sticky;
    top: var(--list-sticky-top, 0px);
    z-index: 1;
    min-height: var(--control-height, 2rem);
    background: var(--bg-secondary, #FFFFFF);
    color: var(--text-secondary, #61636E);
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.04em;
}
"""

_ITEM_COMPACT_CSS = """
/* The row carries the page gutter, so a list inside a frame with no gutter of its own is
   full-bleed with its text still on the page's margin. */
.ui-list-row {
    padding-inline: var(--page-gutter, 1.5rem);
}
"""


class List(Component):
    """A column of rows that behave as one list.

    Takes no props: the rows are its children, and the list supplies what a row cannot
    know on its own — the hairline above every row but the first, and the column that
    keeps them stacked, however a loop nests them.
    """

    __tag__ = "ui-list"

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS

    def template(self):
        """
        <div class="ui-list">
            <slot></slot>
        </div>
        """


class ListItem(Component):
    """One row of a list.

    ``label`` — the row's text; ``href`` — turn the row into a link (the anchor fills the
    row, so the whole row is the target). ``arrangement`` — ``row`` (default) | ``header``
    (a sticky section header). ``selected`` — ``""`` | ``"true"`` (any truthy spelling),
    for the current row.

    Slot richer content in directly: named slots ``leading`` and ``trailing`` hold the
    surround (an avatar, an action), and the default slot holds anything the label does
    not cover. Pass the row's text as ``label`` when a loop renders the row, since a
    loop gives a component its per-item data as attributes.
    """

    __tag__ = "ui-list-item"

    label = ""
    href = ""
    arrangement = "row"  # row | header
    selected = ""

    @computed(dependencies=["selected"])
    def selected_attr(self):
        """The state as the markup spells it, so the stylesheet can read it."""
        return "true" if _truthy(self.selected) else "false"

    @classmethod
    @scoped
    def style(cls):
        return _ITEM_BASE_CSS + compact_block(_ITEM_COMPACT_CSS)

    def template(self):
        """
        <div class="ui-list-row"
             data-arrangement="{arrangement}"
             data-selected="{selected_attr}"><slot name="leading"></slot><span class="ui-list-content" if="{label}"><a class="ui-list-link" if="{href}" href="{href}">{label}</a><span class="ui-list-text" if="{not href}">{label}</span></span><slot></slot><span class="ui-list-trailing"><slot name="trailing"></slot></span></div>
        """


def _truthy(raw):
    """Whether a prop says yes, in either spelling: markup gives text, Python a bool."""
    if raw is True:
        return True
    return str(raw).lower() == "true"
