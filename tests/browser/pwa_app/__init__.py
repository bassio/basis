"""A minimal *installable* Basis app for the PWA browser tests.

Deliberately separate from ``browser_app``: declaring a ``PwaStore`` is app-wide, so a
worker would register and precache a shell for every page of the main fixture — a cost
and a race the hydration/reactivity lane does not need. This app pays it only where the
service worker is the thing under test.

Structure mirrors a scaffolded app: ``bootstrap()`` imports ``stores/`` (where the PWA
declaration lives) and mounts ``components/`` at ``/pwa_app/components/`` for the client
VFS.
"""

import os

from basis.server.app import Basis

from pwa_app.components.page import PwaPage
from pwa_app.components.second_page import SecondPage

app = Basis()

app.bootstrap()

#: An extra mounted dir the update test can rewrite, so that "a new build is deployed" is
#: a changed served file (which moves the shell version) instead of an edit to a file in
#: this repository. Unset outside that lane.
SCRATCH = os.environ.get("BASIS_PWA_SCRATCH")
if SCRATCH:
    app.include_components_dir("/pwa_app/scratch", SCRATCH, name="scratch")

app.serve("/")(PwaPage)
# Never visited by the offline tests before they go offline: it is the route that has no
# cached copy, which is what the fallback document is for.
app.serve("/second")(SecondPage)
