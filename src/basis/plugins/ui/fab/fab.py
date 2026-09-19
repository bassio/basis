"""The ``Fab`` — the one action a screen is offering.

Legitimate on a desktop (a primary create action), and the control a phone needs most,
because the thumb lives at the bottom edge. It is fixed to the viewport's inline end and
floats a gutter above the bottom — and, crucially, *above whatever the page has already
pinned there*: the space a docked nav takes is published as ``--shell-bottom-inset``, so
the two never collide without either component knowing about the other.

``label`` is always the accessible name; ``extended`` additionally shows it, which turns
the circle into a pill.
"""
from basis.shared.component import Component, scoped

_BASE_CSS = """
:scope {
    display: contents;
}

.ui-fab {
    position: fixed;
    /* The inset's fallback is the safe area, so the two cases — docked bar or nothing —
       are one declaration: a bar's height already contains the home indicator. */
    bottom: calc(
        var(--page-gutter, 1.5rem)
        + var(--shell-bottom-inset, var(--safe-area-bottom, 0px))
    );
    inset-inline-end: calc(var(--page-gutter, 1.5rem) + var(--safe-area-right, 0px));
    z-index: 25;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    width: 3.5rem;
    height: 3.5rem;
    border: 0;
    border-radius: 999px;
    background: var(--accent-color, #007acc);
    color: #ffffff;
    font: inherit;
    font-size: 0.875rem;
    font-weight: 500;
    box-shadow: var(--shadow-md, 0 4px 6px -1px rgba(0, 0, 0, 0.1));
    cursor: pointer;
}

.ui-fab-extended {
    width: auto;
    min-width: 3.5rem;
    padding: 0 1rem;
}

.ui-fab-icon {
    line-height: 1;
}

@media (hover: hover) {
    .ui-fab:hover:not(:disabled) {
        background: color-mix(in srgb, var(--accent-color, #007acc) 88%, black);
        box-shadow: 0 6px 14px rgba(0, 0, 0, 0.22);
    }
}

.ui-fab:active:not(:disabled) {
    transform: translateY(1px);
}

.ui-fab:focus-visible {
    outline: 2px solid var(--accent-color, #007acc);
    outline-offset: 3px;
}

.ui-fab:disabled {
    opacity: 0.5;
    cursor: not-allowed;
}

/* The floor is the theme's, not this rule's: a skin that shrinks the FAB for dense
   desktop chrome still cannot take a finger's target below the token. It is stated as a
   floor on both axes, so the circle keeps the diameter the rule above gives it. */
@media (pointer: coarse) {
    .ui-fab {
        min-width: var(--touch-target, 44px);
        min-height: var(--touch-target, 44px);
    }
}
"""


class Fab(Component):
    """A floating action button.

    ``icon`` — the glyph (HTML string or emoji). ``label`` — the accessible name, and
    the visible text of an extended FAB. ``extended`` — ``""`` | ``"true"``; shows the
    label beside the icon. ``disabled`` — ``""`` | ``"true"``.

    The click is a plain DOM click: it bubbles out of the component, so the owner binds
    ``onclick`` on ``<ui-fab>`` exactly as it would on a button.
    """

    __tag__ = "ui-fab"

    icon = ""
    label = ""
    extended = ""
    disabled = ""

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS

    def template(self):
        """
        <button class="ui-fab {extended and 'ui-fab-extended' or ''}"
                type="button"
                aria-label="{label}"
                {disabled}>
            <span class="ui-fab-icon" if="{icon}">{icon}</span>
            <span class="ui-fab-label" if="{extended and label}">{label}</span>
        </button>
        """
