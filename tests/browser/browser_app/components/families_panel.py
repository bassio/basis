"""The new families' fixture — the shapes whose *geometry* is the claim.

Eight components on one page, because the lane pays a Pyodide boot per page: a slider,
a stepper, a segmented control, a progress bar, a skeleton, a list, a toggle row, and a
FAB inside a phone frame whose bottom edge already carries a docked nav.

The nav is deliberate: the FAB's claim is that it clears whatever the page has pinned to
the bottom edge, and that is only a real claim when something *is* pinned there.
"""

from basis.plugins.shell.regions import Footer, Header, Main  # noqa: F401
from basis.plugins.shell.site import SiteShell  # noqa: F401
from basis.plugins.ui.fab.fab import Fab  # noqa: F401
from basis.plugins.ui.list.list import List, ListItem  # noqa: F401
from basis.plugins.ui.nav.nav import Nav  # noqa: F401
from basis.plugins.ui.progress.progress import Progress  # noqa: F401
from basis.plugins.ui.segmented.segmented import Segmented  # noqa: F401
from basis.plugins.ui.skeleton.skeleton import Skeleton  # noqa: F401
from basis.plugins.ui.slider.slider import Slider  # noqa: F401
from basis.plugins.ui.stepper.stepper import Stepper  # noqa: F401
from basis.plugins.ui.toggle.toggle import Toggle  # noqa: F401
from basis.shared.component import Component


class FamiliesPanel(Component):
    """Every new family, in the frame a phone gives it."""

    __tag__ = "browser-families-panel"

    links = [
        {"id": "home", "label": "Home", "href": "/"},
        {"id": "families", "label": "Families", "href": "/families", "icon": "🧩"},
    ]

    views = [
        {"id": "list", "label": "List"},
        {"id": "grid", "label": "Grid"},
        {"id": "board", "label": "Board"},
    ]

    notes = [
        {"id": "a", "title": "Groceries"},
        {"id": "b", "title": "Standup notes"},
        {"id": "c", "title": "Trip packing list"},
    ]

    def style(self):
        """
        browser-families-panel {
            display: contents;
        }

        body { margin: 0; }

        .families-body {
            display: flex;
            flex-direction: column;
            gap: 1.5rem;
            padding: 1rem 0 6rem;
        }

        .families-note {
            margin: 0;
            padding: 0 1rem;
            color: var(--text-secondary, #aaa);
            font: 0.8rem/1.5 system-ui, sans-serif;
        }
        """

    def template(self):
        """
        <shell-site>
            <shell-header>
                <span class="families-note">Families</span>
                <ui-nav items="{links}"></ui-nav>
            </shell-header>
            <shell-main>
                <div class="families-body">
                    <ui-progress value="37" total="100" label="Uploading"
                                 variant="primary"></ui-progress>
                    <ui-skeleton variant="text" lines="3"></ui-skeleton>
                    <ui-slider value="30" min="0" max="100" step="5"
                               label="Opacity"></ui-slider>
                    <ui-stepper value="3" min="1" max="5" label="Rows"></ui-stepper>
                    <ui-segmented items="{views}" value="list" label="View"></ui-segmented>
                    <ui-toggle arrangement="row" label="Dark mode"
                               first="off" second="on"></ui-toggle>
                    <ui-list>
                        <ui-list-item arrangement="header">Today</ui-list-item>
                        <ui-list-item for="note" in="{notes}" key="id"
                                       label="{note['title']}"
                                       href="#"></ui-list-item>
                    </ui-list>
                </div>
            </shell-main>
            <ui-fab icon="＋" label="New note"></ui-fab>
            <shell-footer>
                <span class="families-note">Footer</span>
            </shell-footer>
        </shell-site>
        """
