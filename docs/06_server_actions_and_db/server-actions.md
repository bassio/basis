# Server Actions

**Server Actions** allow Python methods or functions to execute exclusively on the backend server while being called directly from browser client code as if they were local async functions.

---

## 1. Defining a `@server_action`

To turn any Python method into a server action, decorate it with `@server_action`:

```python
from basis.shared.store import Store
from basis.shared.actions import server_action

class TaskStore(Store):
    tasks = []

    @server_action
    async def add_task(self, title: str):
        # Runs on the backend server:
        # Access database, secrets, environment variables, third-party APIs
        new_task = {"id": len(self.tasks) + 1, "title": title, "done": False}
        self.tasks.append(new_task)
        return new_task
```

---

## 2. Calling Server Actions from Components

From client components or event handlers, invoke the store method using `await`:

```python
from basis.shared.component import Component

class NewTaskForm(Component):
    """
    <div class="form">
        <input bind="{title}" placeholder="New task..." />
        <button onclick="{submit}">Add Task</button>
    </div>
    """
    title = ""

    async def submit(self):
        if self.title:
            result = await task_store.add_task(self.title)
            self.title = ""
```

---

## 3. How It Works Under the Hood

### Dual Execution Model
The `@server_action` decorator detects whether code is executing in the backend Python runtime or the browser PyScript runtime:

- **On the Server**: Decorating registers the function in the global `_action_registry` with a canonical string path (e.g. `myapp.TaskStore.add_task`). The method executes normally.
- **In the Browser**: Decorating replaces the function body with an async RPC proxy. When called, the proxy intercepts the invocation and issues an HTTP POST request to `/basis/api/action`.

### Payload & Response Format

The client sends a JSON payload:
```json
{
  "path": "myapp.TaskStore.add_task",
  "store_name": "tasks",
  "args": ["Buy Groceries"],
  "kwargs": {}
}
```

The server processes the action, mutates the server-side store state, serializes the updated store state, and returns:
```json
{
  "data": {"id": 1, "title": "Buy Groceries", "done": false},
  "new_state": {
    "tasks": [{"id": 1, "title": "Buy Groceries", "done": false}]
  }
}
```

The client receives `new_state`, updates the local client store instance, and the DAG propagates changes to subscribed DOM bindings.

---

## 4. Security & PYC Mode Integration

When running in **PYC Mode** (`basis dev --pyc`), Basis parses component and store module ASTs before compilation and strips out the body of `@server_action` functions. 

This ensures backend credentials, internal API keys, database queries, and server imports are never included in the WebAssembly bytecode sent to the browser.
