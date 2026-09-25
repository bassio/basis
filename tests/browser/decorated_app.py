"""Browser fixture for isomorphic ``@app.page`` declarations."""

from pathlib import Path

from basis.shared.component import Basis, Component, IS_SERVER

app = Basis()
fixture_dir = Path(__file__).parent
if IS_SERVER:
    app.vfs.add_component_route("/", str(fixture_dir))


@app.page(
    path="/",
    title="Decorated browser fixture",
    pyscript_src="/pyscript",
    render_mode="ssr",
)
@app.page(
    path="/nested/decorated",
    title="Decorated browser fixture",
    pyscript_src="/pyscript",
    render_mode="csr",
)
class DecoratedCounter(Component):
    __tag__ = "decorated-browser-counter"
    count = 0

    def increment(self, event=None):
        self.count += 1

    def template(self):
        """
        <main class="decorated-counter">
            <span class="count">Count: {count}</span>
            <button class="inc" type="button" onclick="{increment}">Increment</button>
        </main>
        """


if IS_SERVER:
    app.include_components_dir("/", str(fixture_dir), name="decorated_app_root")
