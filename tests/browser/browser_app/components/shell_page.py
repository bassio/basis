"""The shell fixture Page — the responsive frame, SSR-rendered and hydrated."""

from basis.shared.page import Page

from browser_app.components.shell_frame import ShellFrame


class ShellPage(Page):
    title = "Basis shell fixture"
    root_component = ShellFrame
