"""The installable fixture's page — under ``components/`` so the client VFS can import it."""

from basis.shared.page import Page

from pwa_app.components.counter import PwaCounter


class PwaPage(Page):
    title = "Basis PWA fixture"
    root_component = PwaCounter
