"""The loop-child fixture Page — SSR-rendered, then hydrated."""

from basis.shared.page import Page

from browser_app.components.loops_panel import LoopsPanel


class LoopsPage(Page):
    title = "Basis loop-child fixture"
    root_component = LoopsPanel
