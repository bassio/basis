"""The overlay fixture Page — a site frame with four overlays open at once."""

from basis.shared.page import Page

from browser_app.components.overlay_panel import OverlayPanel


class OverlayPage(Page):
    title = "Basis overlay fixture"
    root_component = OverlayPanel
