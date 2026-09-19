"""The container-query spike fixture Page."""

from basis.shared.page import Page

from browser_app.components.container_panel import ContainerPanel


class ContainerPage(Page):
    title = "Basis container-query spike"
    root_component = ContainerPanel
