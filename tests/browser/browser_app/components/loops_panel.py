"""One row component, two loop shapes — the same child, so the shapes are the only variable.

Shape one writes the loop on the component element itself; shape two wraps the component
in a plain element, which is how a row with anything of its own inside it is written (the
website's docs nav is this shape).

The two buttons are the two things a row's value can follow: ``active`` — a store field
the row's prop reads, which follows because the props of a loop written on the component
element are owner-bound like a loop body — and the collection, which re-runs the loop and
pushes every prop again.

The hidden section is a loop of the same child on a branch neither side renders: those
rows have no SSR counterpart, so the adoption pass has to leave them alone rather than
report the whole page as unhydrated.
"""

from basis.shared.component import Component

from browser_app.components.loop_row import LoopRow  # noqa: F401  # registers the tag
from browser_app.stores.loops import loops


class LoopsPanel(Component):
    """Both loop shapes, one child component."""

    __tag__ = "browser-loops-panel"

    def pick_second(self, event=None):
        loops.active = "b"

    def add_row(self, event=None):
        loops.items = loops.items + [
            {"id": f"x{len(loops.items)}", "title": f"Extra {len(loops.items)}"}
        ]

    def template(self):
        """
        <div class="loops-panel">
            <section class="loops-shape-one">
                <browser-loop-row class="loops-host" for="it" in="{$loops.items}" key="id"
                                  label="{it['title']}"
                                  selected="{it['id'] == $loops.active}"></browser-loop-row>
            </section>
            <section class="loops-shape-two">
                <div class="loops-wrapper" for="it" in="{$loops.items}" key="id">
                    <browser-loop-row label="{it['title']}"
                                      selected="{it['id'] == $loops.active}"></browser-loop-row>
                </div>
            </section>
            <section class="loops-hidden" if="{False}">
                <div class="loops-wrapper" for="it" in="{$loops.items}" key="id">
                    <browser-loop-row label="{it['title']}"></browser-loop-row>
                </div>
            </section>
            <button class="pick-second" type="button" onclick="{pick_second}">Second</button>
            <button class="add-row" type="button" onclick="{add_row}">Add</button>
        </div>
        """
