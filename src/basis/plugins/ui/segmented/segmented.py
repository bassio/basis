"""The ``Segmented`` — one choice out of a handful, laid out as adjacent segments.

The items are data (``[{"id", "label", "icon", "disabled"}]``), the way every menu-shaped
family in this catalogue declares its rows, so the control has one template for every
number of items and the app never hand-wires a child per choice.

Each segment is a toggle button that reports itself through ``aria-pressed``. That is
the honest role here: the segments live in one shadow root built from data, so a native
``<input type="radio">`` group — whose checked state follows the DOM, not a computed —
cannot be expressed per item. The pressed state is derived from ``value``, so the
control is driven from outside by the same prop it writes back.
"""
from basis.shared.breakpoints import compact_block
from basis.shared.component import IS_CLIENT, Component, scoped
from basis.shared.reactive import computed

if IS_CLIENT:
    from pyscript import ffi, window
else:
    ffi = window = None

_BASE_CSS = """
:scope {
    display: block;
}

.ui-segmented {
    display: inline-flex;
    gap: 2px;
    max-width: 100%;
    overflow-x: auto;
    padding: 2px;
    border: 1px solid var(--border-color, #E1E1E4);
    border-radius: var(--radius-md, 0.5rem);
    background: var(--bg-tertiary, #EEF0F3);
}

.ui-segmented-item {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.35em;
    flex: 0 0 auto;
    min-height: var(--control-height, 2rem);
    padding: 0 0.75rem;
    border: 0;
    border-radius: calc(var(--radius-md, 0.5rem) - 2px);
    background: transparent;
    color: var(--text-secondary, #61636E);
    font: inherit;
    font-size: 0.8rem;
    font-weight: 500;
    white-space: nowrap;
    cursor: pointer;
}

.ui-segmented-item[aria-pressed="true"] {
    background: var(--bg-secondary, #FFFFFF);
    color: var(--text-primary, #1E2431);
    box-shadow: var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.05));
}

@media (hover: hover) {
    .ui-segmented-item:hover:not([aria-pressed="true"]):not([aria-disabled="true"]) {
        background: var(--hover-bg, rgba(0, 0, 0, 0.04));
        color: var(--text-primary, #1E2431);
    }
}

.ui-segmented-item:active:not([aria-disabled="true"]) {
    background: var(--hover-bg, rgba(0, 0, 0, 0.06));
}

.ui-segmented-item:focus-visible {
    outline: 2px solid var(--accent-color, #007acc);
    outline-offset: 1px;
}

.ui-segmented-item[aria-disabled="true"] {
    opacity: 0.45;
    cursor: not-allowed;
}

/* A tablet is compact-sized content on a coarse pointer: the segment grows, the
   pill's padding does not. */
@media (pointer: coarse) {
    .ui-segmented-item {
        min-height: var(--touch-target, 44px);
    }
}

.ui-segmented-label {
    display: block;
    margin-bottom: 0.3rem;
    font-size: 0.8rem;
    color: var(--text-secondary, #61636E);
}
"""

_COMPACT_CSS = """
/* Full width, and the segments share it: a phone's thumb reaches the whole row. */
.ui-segmented {
    display: flex;
    width: 100%;
    scroll-snap-type: x mandatory;
}

/* Each segment keeps its label's width and takes an equal share of what is left; a set
   that does not fit scrolls, snapped, rather than squeezing labels into ellipses. */
.ui-segmented-item {
    flex: 1 0 auto;
    scroll-snap-align: start;
}
"""


class Segmented(Component):
    """A single choice from a handful of options, shown as adjacent segments.

    ``items`` — ``[{"id", "label", "icon", "disabled"}]``, or a list of plain strings
    (the string is both the id and the label). ``value`` — the selected item's id; the
    control writes back the id the user picked and dispatches a bubbling ``change``
    whose ``detail.value`` is that id. ``label`` — the caption above the control, which
    also names the group. ``disabled`` — ``""`` | ``"true"``.
    """

    __tag__ = "ui-segmented"

    items = []
    value = ""
    label = ""
    disabled = ""

    @computed(dependencies=["items", "value", "disabled"])
    def segments(self):
        """One row per item, with the state the markup and assistive tech both read."""
        selected = "" if _off(self.disabled) else str(self.value)
        resolved = []
        for index, raw in enumerate(self.items or []):
            item = raw if isinstance(raw, dict) else {"label": str(raw)}
            item_id = str(item.get("id") or item.get("value") or item.get("label") or index)
            pressed = item_id == selected
            item_off = _off(item.get("disabled")) or _off(self.disabled)
            resolved.append(
                {
                    "id": item_id,
                    "label": item.get("label", ""),
                    "icon": item.get("icon", ""),
                    "pressed": "true" if pressed else "false",
                    "aria_disabled": "true" if item_off else "false",
                }
            )
        return resolved

    def on_segment_click(self, event):
        target = getattr(event, "currentTarget", None)
        if target is None:
            return
        # The row states its own availability, so a disabled segment stays inert without
        # a second copy of the item data in the handler.
        if _off(self.disabled) or target.getAttribute("aria-disabled") == "true":
            return
        chosen = target.getAttribute("data-segment") or ""
        if not chosen or chosen == str(self.value):
            return
        self.value = chosen
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "change",
                ffi.to_js({"detail": {"value": chosen}, "bubbles": True}),
            ))

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + compact_block(_COMPACT_CSS)

    def template(self):
        """
        <div class="ui-segmented-field">
            <span class="ui-segmented-label" if="{label}">{label}</span>
            <div class="ui-segmented" role="group" aria-label="{label}">
                <button class="ui-segmented-item"
                        for="segment" in="{segments}" key="id"
                        type="button"
                        data-segment="{segment['id']}"
                        aria-pressed="{segment['pressed']}"
                        aria-disabled="{segment['aria_disabled']}"
                        onclick="{on_segment_click}">
                    <span class="ui-segmented-icon" if="{segment['icon']}">{segment['icon']}</span>
                    <span class="ui-segmented-text">{segment['label']}</span>
                </button>
            </div>
        </div>
        """


def _off(raw):
    """Whether a prop or item field says "unavailable".

    Markup gives text and Python gives booleans, so both spellings answer here.
    """
    if raw is True:
        return True
    return str(raw).lower() == "true"
