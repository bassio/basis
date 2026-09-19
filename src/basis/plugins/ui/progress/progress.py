"""The ``Progress`` — how far along a job of known length is.

Two states, one element. A determinate bar takes ``value``/``total`` as data and the
stylesheet reads the fraction from a custom property, so the geometry stays
restatable without a Python branch. With no ``value`` there is nothing to measure and
the bar becomes indeterminate: a sweep that says "working" without pretending to know
how much is left.

The bound is called ``total`` rather than ``max`` because a bare ``{max}`` in a template
resolves to the allowed builtin of that name, never to the component's own prop.

The family owns no viewport query. A progress bar is the first paint on a slow link,
so it has to be correct before the viewport has been answered — and its geometry does
not change with the viewport anyway.
"""
from basis.plugins.ui.numbers import number
from basis.shared.component import Component, scoped
from basis.shared.pointer import reduced_motion_block
from basis.shared.reactive import computed

_BASE_CSS = """
:scope {
    display: block;
}

.ui-progress {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    width: 100%;
}

.ui-progress-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
}

.ui-progress-label {
    font-size: 0.8rem;
    color: var(--text-secondary, #61636E);
}

.ui-progress-value {
    font-size: 0.8rem;
    color: var(--text-secondary, #61636E);
    font-variant-numeric: tabular-nums;
}

.ui-progress-track {
    overflow: hidden;
    width: 100%;
    background: var(--bg-tertiary, #EEF0F3);
    border-radius: 999px;
}

.ui-progress-fill {
    height: 100%;
    width: var(--progress-value, 0%);
    background: var(--progress-color, var(--accent-color, #007acc));
    border-radius: inherit;
    transition: width 0.25s ease;
}

.ui-progress-sm .ui-progress-track { height: 0.25rem; }
.ui-progress-md .ui-progress-track { height: 0.375rem; }
.ui-progress-lg .ui-progress-track { height: 0.625rem; }

/* The default variant needs no rule: an unqualified fill is the accent. */
.ui-progress-success { --progress-color: #22c55e; }
.ui-progress-warning { --progress-color: #f59e0b; }
.ui-progress-danger  { --progress-color: #ef4444; }

/* Nothing to measure: a band sweeping the track, so the bar still reads as working. */
.ui-progress-indeterminate .ui-progress-fill {
    width: 35%;
    animation: ui-progress-sweep 1.4s ease-in-out infinite;
}

@keyframes ui-progress-sweep {
    0%   { transform: translateX(-100%); }
    100% { transform: translateX(calc(100% / 0.35)); }
}
"""

#: Movement a user asked not to see: the bar keeps its meaning without moving.
_REDUCED_MOTION_CSS = """
.ui-progress-fill {
    transition: none;
}

.ui-progress-indeterminate .ui-progress-fill {
    width: 100%;
    animation: none;
    opacity: 0.55;
}
"""


class Progress(Component):
    """A determinate or indeterminate progress bar.

    ``value`` — how far along on a ``total`` scale; leave it empty and the bar is
    indeterminate. ``label`` — the caption above the track, which also names the bar
    for assistive tech. ``variant`` — ``primary`` | ``success`` | ``warning`` |
    ``danger``. ``size`` — ``sm`` | ``md`` | ``lg``.
    """

    __tag__ = "ui-progress"

    value = ""
    total = 100
    label = ""
    variant = "primary"
    size = "md"

    @computed(dependencies=["value", "total"])
    def percent(self):
        """The filled share of the track as a whole number, or ``None`` if unmeasured."""
        current = number(self.value)
        whole = number(self.total)
        if current is None or not whole:
            return None
        return round(max(0.0, min(current / whole, 1.0)) * 100)

    @computed(dependencies=["percent"])
    def indeterminate(self):
        return self.percent is None

    @computed(dependencies=["percent"])
    def fill_vars(self):
        return "" if self.percent is None else f"--progress-value: {self.percent}%;"

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + reduced_motion_block(_REDUCED_MOTION_CSS)

    def template(self):
        """
        <div class="ui-progress ui-progress-{variant} ui-progress-{size}" style="{fill_vars}">
            <div class="ui-progress-head" if="{label}">
                <span class="ui-progress-label">{label}</span>
                <span class="ui-progress-value" if="{not indeterminate}">{percent}%</span>
            </div>
            <div class="ui-progress-track"
                 if="{not indeterminate}"
                 role="progressbar"
                 aria-valuemin="0"
                 aria-valuemax="{total}"
                 aria-valuenow="{percent}"
                 aria-label="{label}">
                <div class="ui-progress-fill"></div>
            </div>
            <div class="ui-progress-track ui-progress-indeterminate"
                 if="{indeterminate}"
                 role="progressbar"
                 aria-label="{label}">
                <div class="ui-progress-fill"></div>
            </div>
        </div>
        """
