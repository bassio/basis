from basis.shared.component import Basis, Component

app = Basis()

@app.entrypoint
class HelloBasis(Component):
    """
    <div><input bind="{name}" placeholder="Type your name..." />Hello {name}!</div>
    """

    name = "World"

