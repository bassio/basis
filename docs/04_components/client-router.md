# Client SPA Router

Basis includes a built-in client-side router (`basis.shared.router`) that enables Single-Page Application (SPA) navigation without full page refreshes, maintaining application state while updating browser history (`popstate` / `pushState`).

---

## Routing Primitives

Client-side routing relies on three main primitives:

1. **`RouterStore` (`$router`)**: Global store managing current path and route parameters.
2. **`Route` (`<basis-route>`)**: Component container that renders its template content when the current URL matches its `path`.
3. **`Link` (`<basis-link>`)**: Navigation link that intercepts click events to perform smooth client-side transitions.

---

## 1. Declaring Routes (`<basis-route>`)

Wrap view markup inside `<basis-route>` elements to conditionally render components based on the URL path:

```html
<basis-route path="/" exact="true">
    <h2>Home Page</h2>
</basis-route>

<basis-route path="/dashboard">
    <h2>Dashboard Overview</h2>
</basis-route>

<basis-route path="*" fallback="true">
    <h2>404 — Page Not Found</h2>
</basis-route>
```

### Route Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `path` | `str` | `""` | URL pattern to match (e.g. `"/"`, `"/profile"`, `"/user/{id}"`). Use `"*"` for catch-all. |
| `exact` | `bool \| str` | `True` | Requires an exact match of the path. |
| `fallback` | `bool \| str` | `False` | Renders only if no standard routes match (404 fallback). |

---

## 2. Dynamic Route Parameters

Route paths support dynamic parameter extraction using brace syntax (`path="/user/{id}"`). Extracted parameters are automatically populated into `$router.params` and passed to child bindings:

```html
<basis-route path="/users/{user_id}">
    <h3>Viewing User Profile ID: {user_id}</h3>
</basis-route>
```

---

## 3. Client Navigation Links (`<basis-link>`)

Use `<basis-link>` in place of standard `<a>` tags for SPA navigation:

```html
<nav>
    <basis-link href="/">Home</basis-link>
    <basis-link href="/dashboard">Dashboard</basis-link>
    <basis-link href="/settings" active_class="is-active">Settings</basis-link>
</nav>
```

### Features of `<basis-link>`
- Intercepts clicks to trigger `router.navigate(href)`.
- Updates `window.history.pushState`.
- Automatically toggles the `active_class` CSS class when the URL matches `href`.

---

## 4. Programmatic Navigation

To navigate programmatically from Python code (e.g. inside an event handler or form submission):

```python
from basis.shared.component import Component

class LoginForm(Component):
    def submit_login(self, event):
        # Authenticate user...
        
        # Navigate programmatically
        Component.S['router'].navigate("/dashboard")
```

---

## Complete Multi-Page SPA Example

```python
from basis.shared.component import Basis, Component

app = Basis()

@app.page
class AppShell(Component):
    """
    <div class="layout">
        <nav class="sidebar">
            <basis-link href="/">🏠 Home</basis-link>
            <basis-link href="/analytics">📊 Analytics</basis-link>
            <basis-link href="/settings">⚙️ Settings</basis-link>
        </nav>
        
        <main class="content">
            <basis-route path="/" exact="true">
                <h1>Welcome to Dashboard</h1>
            </basis-route>
            
            <basis-route path="/analytics">
                <h1>System Analytics</h1>
            </basis-route>

            <basis-route path="/settings">
                <h1>User Settings</h1>
            </basis-route>
            
            <basis-route path="*" fallback="true">
                <h1>404 — Page Not Found</h1>
            </basis-route>
        </main>
    </div>
    """
```
