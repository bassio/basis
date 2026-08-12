# Built-in UI Component Suite (`basis.ui`)

Basis ships with a built-in suite of UI components (`basis.ui`) designed for high visual appeal, accessibility, and smooth integration into Basis apps without requiring external CSS libraries or build steps.

When `app.bootstrap()` runs (or when using `@app.entrypoint`), Basis automatically mounts the UI suite at `/basis/ui/`.

---

## 1. Button (`<ui-button>`)

A customizable button component supporting variants, sizes, loading spinners, and icons.

```html
<ui-button label="Save Changes" variant="primary" size="md"></ui-button>
<ui-button label="Deleting..." variant="danger" loading="true"></ui-button>
<ui-button label="Github" variant="outline" icon="⭐"></ui-button>
```

### Attributes

| Attribute | Type / Allowed Values | Default | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | `""` | Button text content. |
| `variant` | `'primary' \| 'secondary' \| 'ghost' \| 'outline' \| 'danger'` | `'primary'` | Visual style variant. |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | Size scaling. |
| `loading` | `"" \| "true"` | `""` | Displays a loading spinner and disables interaction. |
| `disabled` | `"" \| "true"` | `""` | Disables user clicks. |
| `icon` | `str` | `""` | Leading icon HTML string or emoji. |
| `icon_right`| `str` | `""` | Trailing icon HTML string or emoji. |

---

## 2. Badge (`<ui-badge>`)

A status badge component for labels, counts, and tags.

```html
<ui-badge label="Active" variant="success"></ui-badge>
<ui-badge label="Warning" variant="warning"></ui-badge>
<ui-badge label="Beta" variant="primary"></ui-badge>
```

### Attributes

| Attribute | Values | Default |
| :--- | :--- | :--- |
| `label` | `str` | `""` |
| `variant` | `'default' \| 'primary' \| 'success' \| 'warning' \| 'danger'` | `'default'` |

---

## 3. Toggle (`<ui-toggle>`)

An accessible boolean switch toggle control.

```html
<ui-toggle label="Enable Notifications" checked="{is_enabled}" onclick="{toggle_setting}"></ui-toggle>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `checked` | `"" \| "true"` | `""` | Toggle state. |
| `label` | `str` | `""` | Text label next to the toggle. |

---

## 4. Toast (`<ui-toast>`)

Notification toast alerts for ephemeral status updates.

```html
<ui-toast message="Profile saved successfully!" type="success"></ui-toast>
```

### Attributes

| Attribute | Values | Default |
| :--- | :--- | :--- |
| `message` | `str` | `""` |
| `type` | `'info' \| 'success' \| 'warning' \| 'error'` | `'info'` |

---

## 5. Breadcrumbs (`<ui-breadcrumbs>`)

Navigation breadcrumb path for application hierarchy.

```html
<ui-breadcrumbs items="{nav_items}"></ui-breadcrumbs>
```

---

## 6. Command Palette (`<ui-command-palette>`)

A popover command palette component (`Ctrl+K` style) for searching and executing actions across an application.

```html
<ui-command-palette placeholder="Search commands..."></ui-command-palette>
```

---

## 7. Audio Recorder (`<ui-audio-recorder>`)

An interactive audio recording component built with HTML5 audio APIs for capturing and submitting audio clips directly from Python web apps.

---

## Using UI Components in Custom Components

Because components map to HTML Custom Elements, you can use `basis.ui` tags directly inside your component HTML templates:

```python
from basis.shared.component import Component

class SettingsPanel(Component):
    """
    <div class="panel">
        <h2>Account Settings</h2>
        <ui-toggle label="Dark Mode" checked="{dark_mode}"></ui-toggle>
        <div style="margin-top: 16px;">
            <ui-button label="Save" variant="primary" onclick="{save_settings}"></ui-button>
        </div>
    </div>
    """
    dark_mode = True

    def save_settings(self):
        pass
```
