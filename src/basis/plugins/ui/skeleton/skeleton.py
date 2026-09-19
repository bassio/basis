"""The ``Skeleton`` — the shape of the content that is still on its way.

A placeholder is only honest when it is the *size* of the thing it stands in for, so the
geometry is the API: ``text`` for a paragraph, ``rect`` for a block, ``circle`` for an
avatar. The bars shimmer while the data loads, and stop moving — without losing their
meaning — for a user who asked for less motion.

Like ``ui-progress`` this family owns no viewport query: it is what the user sees
*before* anything else has been answered, so it has to be right at the first paint, and
its geometry does not change with the viewport.
"""
from basis.shared.component import Component, scoped
from basis.shared.pointer import reduced_motion_block
from basis.shared.reactive import computed

_BASE_CSS = """
:scope {
    display: block;
}

.ui-skeleton {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    width: var(--skeleton-width, 100%);
}

.ui-skeleton-bar {
    height: var(--skeleton-height, 0.75rem);
    border-radius: 999px;
    background-color: var(--bg-tertiary, #EEF0F3);
    background-image: linear-gradient(
        90deg,
        transparent 25%,
        var(--border-soft, #EAEAED) 37%,
        transparent 63%
    );
    background-size: 400% 100%;
    animation: ui-skeleton-shimmer 1.4s ease infinite;
}

/* A paragraph's last line stops short: a full-width one reads as a solid block. */
.ui-skeleton-text .ui-skeleton-bar-last {
    width: 60%;
}

.ui-skeleton-rect .ui-skeleton-bar {
    height: var(--skeleton-height, 6rem);
    border-radius: var(--radius-md, 0.5rem);
}

.ui-skeleton-circle .ui-skeleton-bar {
    width: var(--skeleton-width, 2.5rem);
    height: var(--skeleton-height, 2.5rem);
    border-radius: 50%;
}

@keyframes ui-skeleton-shimmer {
    0%   { background-position: 100% 50%; }
    100% { background-position: 0 50%; }
}
"""

#: Movement a user asked not to see: the placeholder stays a still, quiet block.
_REDUCED_MOTION_CSS = """
.ui-skeleton-bar {
    animation: none;
    background-image: none;
}
"""


class Skeleton(Component):
    """A shimmering placeholder shaped like the content it stands in for.

    ``variant`` — ``text`` (bars, one per ``lines``) | ``rect`` (a block) | ``circle``
    (an avatar). ``lines`` — how many bars a ``text`` skeleton has. ``width`` /
    ``height`` — CSS lengths overriding the variant's default box.
    """

    __tag__ = "ui-skeleton"

    variant = "text"
    lines = 1
    width = ""
    height = ""

    @computed(dependencies=["lines", "variant"])
    def skeleton_lines(self):
        """One entry per bar; only a multi-line paragraph shortens its last line."""
        count = _count(self.lines)
        return [
            {"class": "ui-skeleton-bar-last" if count > 1 and index == count - 1 else ""}
            for index in range(count)
        ]

    @computed(dependencies=["width", "height"])
    def skeleton_vars(self):
        declared = []
        if self.width:
            declared.append(f"--skeleton-width: {self.width};")
        if self.height:
            declared.append(f"--skeleton-height: {self.height};")
        return " ".join(declared)

    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + reduced_motion_block(_REDUCED_MOTION_CSS)

    def template(self):
        """
        <div class="ui-skeleton ui-skeleton-{variant}" style="{skeleton_vars}" aria-hidden="true">
            <div class="ui-skeleton-bar {line['class']}"
                 for="line" in="{skeleton_lines}"></div>
        </div>
        """


def _count(raw):
    """*raw* as a bar count of at least one — a skeleton with no bar is invisible."""
    try:
        return max(1, int(raw))
    except (TypeError, ValueError):
        return 1
