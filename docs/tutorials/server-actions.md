# Tutorial: Server Actions

The full-stack story: a Python function that runs on the **server**, called
straight from the browser as if it were a local function. Try it live on the
site's Showcase page (under **Mini-Apps → Server Actions**).

This is the "from DB to DOM" mechanism — the server owns the data, and the
client just calls a Python function.

---

## The whole app

```python
from basis.shared.component import Component
from basis.shared.actions import server_action


@server_action
def greet(name: str) -> str:
    return f"Hello, {name}! This came from the server."


class Greeter(Component):
    name = "Basis"
    reply = ""

    async def greet_me(self, event):
        self.reply = await greet(self.name)

    def template(self):
        """
        <input bind="{name}" placeholder="Your name" />
        <button onclick="{greet_me}">Greet me</button>
        <p>{reply}</p>
        """
```

Click the button and the reply text arrives from the server — with no fetch
call, no JSON marshalling, no HTTP plumbing written by hand.

---

## 1. `@server_action` marks a function as an RPC endpoint

The `@server_action` decorator does different things on each side of the wire:

- **On the server**, it registers the function in the global action registry
  under its canonical path — `module.qualname`, e.g.
  `my_app.components.greeter.greet` — so the RPC endpoint can find it.
- **On the client** (PyScript), it *replaces* the function with an async proxy:
  calling `greet(name)` sends a `POST` to the framework's single
  `/basis/api/action` endpoint with that canonical path and the arguments.

From your code's point of view it's just an `await`:

```python
self.reply = await greet(self.name)
```

The server runs the *same* Python function and returns its result.

> [!NOTE]
> The framework dispatches every action — `@server_action` and plugin-scoped
> actions alike — through one RPC endpoint, keyed by canonical path. See
> [Server Actions](../06_server_actions_and_db/server-actions.md) for the full
> picture, including how to send complex arguments and handle errors.

## 2. Why the server matters

Everything before this tutorial has been client-side reactivity. A server
action is the moment you reach for **authority**:

- reading or writing a **database** (`SELECT`/`INSERT` — see
  [Database & SQLModel](../06_server_actions_and_db/database.md)),
- calling another service or a library that must not run in the browser,
- computing something from data only the server has.

The rule of thumb: keep the *fast, local* reactivity on the client; use a
server action when a task genuinely belongs on the server.

## 3. Async handlers

`greet_me` is `async def`, because it awaits the network round-trip. Event
handlers can be async — the framework runs the coroutine for you, so the UI
stays responsive while the request is in flight.

---

## What you learned

- `@server_action` turns a Python function into an RPC endpoint.
- The client calls it with `await` — no HTTP code by hand.
- Server actions are how you reach databases and server-side authority.

## Where to go next

- Server actions in depth: [Server Actions](../06_server_actions_and_db/server-actions.md)
- Persistent models with SQLModel: [Database & SQLModel](../06_server_actions_and_db/database.md)
- Plugin-scoped actions: [Plugin System & Architecture](../07_plugins/plugin-system.md)
- The next mini-app, which swaps global state instead of calling the server:
  [The Theme Changer](theme-changer.md)
