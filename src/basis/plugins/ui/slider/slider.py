"""The ``Slider`` — one value picked out of a continuous range.

The native ``<input type="range">`` stays the control: it is the thing a finger, a mouse
and a keyboard already know how to drive, and it brings the arrow-key/Home/End behaviour
for free. What the family adds is the theme's look and the two things a phone needs — a
rail that says how far along the value is, and a thumb that grows to the touch target.

The rail's fill is drawn from a custom property rather than a pseudo-element, because
the fill *is* data: ``--slider-fill`` follows the value as the user drags, with the
stylesheet deciding what to do with the fraction.
"""
from basis.plugins.ui.numbers import number, plain
from basis.shared.component import Component, scoped
from basis.shared.reactive import computed

_BASE_CSS = """
:scope {
    display: block;
}

.ui-slider {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    width: 100%;
}

.ui-slider-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
}

.ui-slider-label {
    font-size: 0.8rem;
    color: var(--text-secondary, #61636E);
}

.ui-slider-value {
    font-size: 0.8rem;
    color: var(--text-secondary, #61636E);
    font-variant-numeric: tabular-nums;
}

/* The input *is* the rail: appearance is off, so the two background layers below are
   the unfilled and filled halves of it, and the engine draws only the thumb. */
.ui-slider-input {
    appearance: none;
    -webkit-appearance: none;
    width: 100%;
    height: var(--control-height, 2rem);
    margin: 0;
    border: 0;
    border-radius: 999px;
    background-color: transparent;
    background-image:
        linear-gradient(var(--accent-color, #007acc), var(--accent-color, #007acc)),
        linear-gradient(var(--bg-tertiary, #EEF0F3), var(--bg-tertiary, #EEF0F3));
    background-size: var(--slider-fill, 0%) 0.25rem, 100% 0.25rem;
    background-position: 0 center, 0 center;
    background-repeat: no-repeat;
    cursor: pointer;
}

.ui-slider-input:focus-visible {
    outline: 2px solid var(--accent-color, #007acc);
    outline-offset: 2px;
}

.ui-slider-input::-webkit-slider-runnable-track,
.ui-slider-input::-moz-range-track {
    height: 100%;
    background: transparent;
}

/* Both engines need the thumb declared, and both need their own pseudo-element. */
.ui-slider-input::-webkit-slider-thumb {
    -webkit-appearance: none;
    width: 1.125rem;
    height: 1.125rem;
    border: 2px solid var(--bg-primary, #ffffff);
    border-radius: 50%;
    background: var(--accent-color, #007acc);
    box-shadow: var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.18));
}

.ui-slider-input::-moz-range-thumb {
    width: 1.125rem;
    height: 1.125rem;
    border: 2px solid var(--bg-primary, #ffffff);
    border-radius: 50%;
    background: var(--accent-color, #007acc);
    box-shadow: var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.18));
}

@media (hover: hover) {
    .ui-slider-input:hover::-webkit-slider-thumb {
        box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent-color, #007acc) 18%, transparent);
    }
    .ui-slider-input:hover::-moz-range-thumb {
        box-shadow: 0 0 0 6px color-mix(in srgb, var(--accent-color, #007acc) 18%, transparent);
    }
}

/* The engine scales the rail by the value it owns; a wider rail is not the answer. */
.ui-slider-input:active::-webkit-slider-thumb {
    box-shadow: 0 0 0 8px color-mix(in srgb, var(--accent-color, #007acc) 24%, transparent);
}
.ui-slider-input:active::-moz-range-thumb {
    box-shadow: 0 0 0 8px color-mix(in srgb, var(--accent-color, #007acc) 24%, transparent);
}

.ui-slider-disabled {
    opacity: 0.5;
}

.ui-slider-disabled .ui-slider-input {
    cursor: not-allowed;
}

/* A precise 18px knob is right for a mouse; a finger needs the whole target. */
@media (pointer: coarse) {
    .ui-slider-input {
        height: var(--touch-target, 44px);
    }
    .ui-slider-input::-webkit-slider-thumb {
        width: var(--touch-target, 44px);
        height: var(--touch-target, 44px);
    }
    .ui-slider-input::-moz-range-thumb {
        width: var(--touch-target, 44px);
        height: var(--touch-target, 44px);
    }
}
"""


class Slider(Component):
    """A single value picked out of a range.

    ``value`` — the current value (bind it to drive the control from outside; the
    control writes back the value it is dragged to and lets the event bubble, so the
    owner persists). ``min`` / ``max`` / ``step`` — the range and its granularity.
    ``label`` — the caption above the rail, shown beside the current value.
    ``disabled`` — ``""`` | ``"true"``.
    """

    __tag__ = "ui-slider"

    value = ""
    min = 0
    max = 100
    step = 1
    label = ""
    disabled = ""

    @computed(dependencies=["value", "min", "max", "step"])
    def slider(self):
        """Everything the markup needs, already in the text form it needs it in.

        The bounds travel together as one dict because ``{min}``, ``{max}`` and ``{step}``
        each resolve to the allowed builtin of that name — a bare name can never read the
        component's own prop — while a subscript off a non-builtin name can.
        """
        low = number(self.min, 0)
        high = number(self.max, 100)
        if high < low:
            low, high = high, low
        increment = number(self.step, 1) or 1
        if increment < 0:
            increment = -increment

        current = number(self.value, low)
        current = min(max(current, low), high)
        span = high - low
        fill = 0.0 if span <= 0 else (current - low) / span * 100

        return {
            "min": plain(low),
            "max": plain(high),
            "step": plain(increment),
            "value": plain(current),
            "fill": f"{fill:.4g}%",
        }

    @computed(dependencies=["slider"])
    def slider_vars(self):
        return f"--slider-fill: {self.slider['fill']};"

    def on_input(self, event):
        # The control keeps its own declared state in step with the DOM; writing the
        # value somewhere durable is the owner's job, through the bubbling event.
        self.value = event.target.value

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS

    def template(self):
        """
        <label class="ui-slider {disabled and 'ui-slider-disabled' or ''}">
            <span class="ui-slider-head" if="{label}">
                <span class="ui-slider-label">{label}</span>
                <span class="ui-slider-value">{slider['value']}</span>
            </span>
            <input class="ui-slider-input"
                   type="range"
                   min="{slider['min']}"
                   max="{slider['max']}"
                   step="{slider['step']}"
                   value="{slider['value']}"
                   style="{slider_vars}"
                   {disabled}
                   oninput="{on_input}" />
        </label>
        """
