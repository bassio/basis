"""Stores for the installable browser-test app.

The declaration *is* the opt-in (``basis.plugins.mobile``): nothing else in this app
mentions the PWA plugin, and the manifest link, the manifest itself and the app-shell
worker all follow from this one line.
"""

from basis.plugins.mobile import PwaStore

pwa = PwaStore(
    "pwa",
    title="Basis PWA fixture",
    short_name="Basis PWA",
    description="The browser lane's installable fixture.",
)
