"""The ``Stepper`` — a number nudged one increment at a time.

Two buttons and a value, sized from the page scale so a phone gets the touch target
without the family owning a query. Typing is out of scope on purpose: a number a user
has to enter exactly is a text input, and this is the control for adjusting one that is
already roughly right.

The value is clamped at the bounds, so pressing at a limit is a no-op — and the button
that produced it says ``aria-disabled`` rather than disappearing, which keeps the two
targets in the same place as the value moves.
"""
from basis.plugins.ui.numbers import number, plain
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

.ui-stepper {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1rem;
    width: 100%;
    min-height: var(--control-height, 2rem);
}

.ui-stepper-label {
    font-size: 0.8rem;
    color: var(--text-secondary, #61636E);
}

.ui-stepper-control {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
}

.ui-stepper-button {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: var(--control-height, 2rem);
    height: var(--control-height, 2rem);
    border: 1px solid var(--border-color, #E1E1E4);
    border-radius: var(--radius-sm, 0.25rem);
    background: var(--bg-secondary, #FFFFFF);
    color: var(--text-primary, #1E2431);
    font: inherit;
    font-size: 1rem;
    line-height: 1;
    cursor: pointer;
}

@media (hover: hover) {
    .ui-stepper-button:hover:not(:disabled):not([aria-disabled="true"]) {
        border-color: var(--border-hover, #C9C9CE);
        background: var(--hover-bg, rgba(0, 0, 0, 0.04));
    }
}

.ui-stepper-button:active:not(:disabled) {
    background: var(--hover-bg, rgba(0, 0, 0, 0.06));
}

.ui-stepper-button:focus-visible {
    outline: 2px solid var(--accent-color, #007acc);
    outline-offset: 2px;
}

.ui-stepper-button:disabled,
.ui-stepper-button[aria-disabled="true"] {
    opacity: 0.4;
    cursor: not-allowed;
}

.ui-stepper-value {
    min-width: 2.5rem;
    text-align: center;
    font-size: 0.875rem;
    font-variant-numeric: tabular-nums;
    color: var(--text-primary, #1E2431);
}

.ui-stepper-disabled .ui-stepper-label,
.ui-stepper-disabled .ui-stepper-value {
    opacity: 0.5;
}

@media (pointer: coarse) {
    .ui-stepper-button {
        width: var(--touch-target, 44px);
        height: var(--touch-target, 44px);
    }
}
"""


class Stepper(Component):
    """A number adjusted by one increment at a time.

    ``value`` — the current value; the control clamps it inside the bounds, writes it
    back to itself and dispatches a bubbling ``change`` whose ``detail.value`` is the
    new number (persisting it is the owner's job). ``min`` / ``max`` — bounds, left empty
    for unbounded. ``step`` — how far one press moves. ``label`` — the row's caption,
    which also names the button group. ``disabled`` — ``""`` | ``"true"``.
    """

    __tag__ = "ui-stepper"

    value = ""
    min = ""
    max = ""
    step = 1
    label = ""
    disabled = ""

    @computed(dependencies=["value", "min", "max", "step"])
    def stepper(self):
        """Where the value sits and how far one press may move it."""
        increment = abs(number(self.step, 1) or 1)
        return {
            "value": _clamp(number(self.value, 0), number(self.min), number(self.max)),
            "min": number(self.min),
            "max": number(self.max),
            "step": increment,
        }

    @computed(dependencies=["stepper"])
    def stepper_view(self):
        """The same state as the markup needs it: text, and whether a bound is reached."""
        state = self.stepper
        return {
            "value": plain(state["value"]),
            "at_min": _at_bound(state["value"], state["min"], below=True),
            "at_max": _at_bound(state["value"], state["max"], below=False),
        }

    def nudge(self, delta):
        """Move the value by *delta*, held inside the bounds, and announce the result."""
        state = self.stepper
        moved = _clamp(state["value"] + delta, state["min"], state["max"])
        if moved == state["value"]:
            return
        self.value = plain(moved)
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "change",
                ffi.to_js({"detail": {"value": moved}, "bubbles": True}),
            ))

    def on_increase(self, event):
        self.nudge(self.stepper["step"])

    def on_decrease(self, event):
        self.nudge(-self.stepper["step"])

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS

    def template(self):
        """
        <div class="ui-stepper {disabled and 'ui-stepper-disabled' or ''}">
            <span class="ui-stepper-label" if="{label}">{label}</span>
            <span class="ui-stepper-control" role="group" aria-label="{label}">
                <button class="ui-stepper-button"
                        type="button"
                        aria-label="Decrease"
                        aria-disabled="{stepper_view['at_min']}"
                        {disabled}
                        onclick="{on_decrease}">−</button>
                <span class="ui-stepper-value">{stepper_view['value']}</span>
                <button class="ui-stepper-button"
                        type="button"
                        aria-label="Increase"
                        aria-disabled="{stepper_view['at_max']}"
                        {disabled}
                        onclick="{on_increase}">+</button>
            </span>
        </div>
        """


def _clamp(value, low, high):
    """*value* held inside *low*/*high*; either bound may be ``None`` for unbounded."""
    if low is not None:
        value = max(value, low)
    if high is not None:
        value = min(value, high)
    return value


def _at_bound(value, bound, below):
    """``"true"``/``"false"`` for the markup's ``aria-disabled``."""
    if bound is None:
        return "false"
    return "true" if (value <= bound if below else value >= bound) else "false"
