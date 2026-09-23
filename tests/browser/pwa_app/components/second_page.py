"""A second route in the installable fixture.

Exists so the offline lane has a URL it never visited: a navigation there has no cached
copy and no network, which is the only way a request reaches the fallback document.
"""

from basis.shared.page import Page

from pwa_app.components.counter import PwaCounter


class SecondPage(Page):
    title = "Second"
    root_component = PwaCounter
