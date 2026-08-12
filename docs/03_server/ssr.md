# Server-Side Rendering (SSR) Pipeline

Basis performs an initial server-side render (SSR) of your application before sending HTML to the browser. This ensures fast time-to-first-byte (TTFB), excellent SEO, and prevents the "blank white screen" commonly seen in single-page applications while waiting for JavaScript to download.

---

## 1. The Rendering Lifecycle

When a user visits a Basis URL mapped via `@app.entrypoint` or `@app.include_ssr_page`, the FastAPI server executes the following sequence:

### Step 1: Component Instantiation
The server looks up the root component for the requested route (e.g., `Dashboard`) and instantiates it within the context of a `Page` shell. 

### Step 2: `server_load` Execution
Basis recursively walks the component tree, checking for any component or registered `Store` that defines an async `server_load()` method. 

These methods are executed concurrently using `asyncio.gather()`. 
`server_load()` is your designated hook for performing backend operations before rendering:
- Fetching data from the database.
- Checking user authentication status.
- Making external API calls.

```python
class ProfilePage(Component):
    """..."""
    async def server_load(self):
        # Access FastAPI dependencies or database sessions
        session = db_session_var.get()
        self.user = session.get(User, 123)
```

### Step 3: Template Evaluation
Once all `server_load` hooks complete, the DAG (Dependency Graph) processes the current state and resolves all template expressions (the `{...}` bindings).

### Step 4: HTML Generation & Hydration IDs
Basis compiles the component templates into static HTML strings. Crucially, as it builds the HTML, it injects `data-hydration-id` attributes onto any DOM node that contains a reactive binding. These IDs map exactly to the component's internal `BindingBlueprints`.

### Step 5: State Serialization
All registered `Store` instances are serialized to JSON. This JSON block is injected directly into the `<head>` of the page inside a `<script id="basis-initial-state">` tag.

### Step 6: Response Delivery
The server returns the fully formed, static HTML document. The browser immediately displays this content. In the background, the PyScript client downloads, boots, and uses the hydration IDs and serialized state to attach live bindings to the existing DOM without rebuilding it (see [SSR & Client Hydration](../05_reactivity/ssr-hydration.md)).

---

## 2. Server-Only Dependencies

During the SSR pass, your components execute in a real Python backend environment (FastAPI). This means you can import and use standard Python libraries, access environment variables, and connect to databases inside `server_load()`.

However, that exact same component file will later be executed by Pyodide in the browser during hydration. If you import server-only libraries at the top of your component file, Pyodide will throw `ImportError`.

### Handling Isomorphic Imports

Basis provides `IS_CLIENT` and `IS_SERVER` flags to safely gate imports:

```python
import sys
from basis.shared.component import Component

# Safe check for environment
IS_CLIENT = "pyscript" in sys.modules

if not IS_CLIENT:
    import boto3
    import os

class FileUploader(Component):
    """..."""
    async def server_load(self):
        # This only runs on the server, so boto3 is guaranteed to exist
        s3 = boto3.client('s3', region_name=os.getenv('AWS_REGION'))
        self.upload_url = s3.generate_presigned_url(...)
```

Alternatively, you can place backend-only logic inside `@server_action` methods (which are safely proxied on the client) or within dedicated plugin routes.
