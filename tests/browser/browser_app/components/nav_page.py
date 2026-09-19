"""The nav fixture Page — a site frame with one ``ui-nav`` in its header."""

from basis.shared.page import Page

from browser_app.components.nav_panel import NavPanel


class NavPage(Page):
    title = "Basis nav fixture"
    root_component = NavPanel
