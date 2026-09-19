"""The new families' fixture Page — SSR-rendered, then hydrated."""

from basis.shared.page import Page

from browser_app.components.families_panel import FamiliesPanel


class FamiliesPage(Page):
    title = "Basis mobile families fixture"
    root_component = FamiliesPanel
