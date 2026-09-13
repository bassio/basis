"""The fixture Page — lives under ``components/`` so the client VFS can import it
(reads ``root_component`` and hydrates it against the SSR tree)."""

from basis.shared.page import Page

from browser_app.components.counter import Counter


class CounterPage(Page):
    title = "Basis browser fixture"
    root_component = Counter
