"""The touch fixture Page — the catalogue cases, SSR-rendered and hydrated."""

from basis.shared.page import Page

from browser_app.components.touch_panel import TouchPanel


class TouchPage(Page):
    title = "Basis touch fixture"
    root_component = TouchPanel
