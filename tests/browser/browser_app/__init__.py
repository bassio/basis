"""A tiny Basis app used as the client-browser CI fixture.

Deliberately minimal and *real*: a server-rendered Page whose root is one
reactive component, served through the framework's normal SSR → hydration →
PyScript client path (the offline vendored runtime — no network). The Playwright
harness in ``tests/browser`` boots this app and asserts the two things the
server-side suite structurally cannot: a clean hydration report and a live DOM
update driven by the client DAG.

Structure mirrors a scaffolded app (``basis init``): a package with
``components/`` auto-discovered and mounted into the client VFS under the
package path, so the client can import the page module + root component and
hydrate the SSR tree (isomorphism: VFS namespace == import namespace).
"""

from basis.server.app import Basis

from browser_app.components.page import CounterPage
from browser_app.components.container_page import ContainerPage
from browser_app.components.families_page import FamiliesPage
from browser_app.components.loops_page import LoopsPage
from browser_app.components.nav_page import NavPage
from browser_app.components.overlay_page import OverlayPage
from browser_app.components.shell_page import ShellPage
from browser_app.components.touch_page import TouchPage

app = Basis()

# Conventional auto-discovery imports stores/ and mounts components/ at
# /browser_app/components/ so the client can import them.
app.bootstrap()

app.serve("/")(CounterPage)
app.serve("/shell")(ShellPage)
app.serve("/touch")(TouchPage)
app.serve("/nav")(NavPage)
app.serve("/overlays")(OverlayPage)
app.serve("/container")(ContainerPage)
app.serve("/families")(FamiliesPage)
app.serve("/loops")(LoopsPage)
