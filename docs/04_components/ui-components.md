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

## 8. Accordion (`<ui-accordion>` / `<ui-accordion-item>`)

Collapsible accordion sections for organizing content vertically.

```html
<ui-accordion>
    <ui-accordion-item name="faq" title="What is Basis?">
        <p>Basis is a full-stack reactive Python framework.</p>
    </ui-accordion-item>
    <ui-accordion-item name="docs" title="Where are the docs?">
        <p>Start at <code>docs/index.md</code>.</p>
    </ui-accordion-item>
</ui-accordion>
```

### `<ui-accordion-item>` Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `name` | `str` | `"default-group"` | Group the item belongs to (only one open per group). |
| `title` | `str` | `""` | Header text of the collapsible section. |

---

## 9. Card (`<ui-card>`)

A container component that groups content on a bordered, hover-highlighted surface.

```html
<ui-card>
    <h3>Account Overview</h3>
    <p>Usage and billing details…</p>
</ui-card>
```

No configuration attributes — content is projected through the default slot.

---

## 10. Checkbox (`<ui-checkbox>`)

A custom-styled, accessible checkbox with label and sizing.

```html
<ui-checkbox label="Accept terms" checked="{accepted}" onchange="{on_toggle}"></ui-checkbox>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | `""` | Text label placed to the right. |
| `checked` | `"" \| "true"` | `""` | Checked state. |
| `disabled` | `"" \| "true"` | `""` | Disables interaction. |
| `name` | `str` | `""` | HTML `name` attribute. |
| `value` | `str` | `""` | HTML `value` attribute. |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | Size scaling. |

---

## 11. Calendar (`<ui-calendar>`)

A premium, responsive monthly calendar with reactive date selection.

```html
<ui-calendar selected_date="{selected_date}" update="date_store.selected_date"></ui-calendar>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `selected_date` | `str` (`YYYY-MM-DD`) | today | Currently selected date. |
| `current_year` | `int` | current year | Year being viewed. |
| `current_month` | `int` (1–12) | current month | Month being viewed. |
| `update` | `str` | `""` | Optional store path (e.g. `"date_store.selected_date"`) written reactively when a date is selected. |

---

## 12. Text Input (`<ui-text-input>`)

A labeled text input with optional prefix/suffix icons, helper text, and validation-error styling.

```html
<ui-text-input label="Email" type="email" value="{email}" error="{email_error}"
               placeholder="you@example.com" helper="We never share your email."></ui-text-input>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | `""` | Label shown above the input. |
| `placeholder` | `str` | `""` | Placeholder text. |
| `value` | `str` | `""` | Bound value (two-way). |
| `type` | `'text' \| 'email' \| 'password' \| 'search' \| 'number'` | `'text'` | HTML input type. |
| `prefix_icon` | `str` | `""` | Leading icon (HTML string / emoji). |
| `suffix_icon` | `str` | `""` | Trailing icon (HTML string / emoji). |
| `helper` | `str` | `""` | Hint text shown below the input. |
| `error` | `str` | `""` | Error message — when non-empty the input is styled as invalid. |
| `disabled` | `"" \| "true"` | `""` | Disables interaction. |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | Size scaling. |

---

## 13. Select (`<ui-select>`)

A custom, styleable dropdown built on the native `<select>`.

```html
<ui-select label="Role" options="{role_options}" value="{role}" placeholder="Choose a role…"></ui-select>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | `""` | Label shown above the select. |
| `options` | `list[dict] \| list[str]` | `[]` | Options as `[{label, value}, …]` or plain strings. |
| `value` | `str` | `""` | Currently selected value. |
| `placeholder` | `str` | `"Select an option…"` | Grayed-out prompt option (`value=""`). |
| `disabled` | `"" \| "true"` | `""` | Disables interaction. |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | Size scaling. |
| `helper` / `error` | `str` | `""` | Hint text / validation error message. |

---

## 14. Modal (`<ui-modal>`)

An accessible dialog/overlay component.

```html
<ui-modal open="{show_modal}" title="Confirm" size="md" close_on_backdrop="true">
    <p>Are you sure you want to continue?</p>
    <ui-button label="OK" onclick="{confirm}"></ui-button>
</ui-modal>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `open` | `"" \| "true"` | `""` | Reactive control of the open state. |
| `title` | `str` | `""` | Optional header title. |
| `size` | `'sm' \| 'md' \| 'lg' \| 'full'` | `'md'` | Modal size. |
| `close_on_backdrop` | `"true" \| ""` | `"true"` | Close when the backdrop is clicked. |

---

## 15. Context Menu (`<ui-context-menu>`)

A positionable context-menu overlay.

```html
<ui-context-menu open="{menu_open}" x="{menu_x}" y="{menu_y}" items="{menu_items}"></ui-context-menu>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `open` | `"" \| "true"` | `""` | Display state. |
| `x` / `y` | `int` | `0` | Menu position in pixels. |
| `items` | `list[dict]` | `[]` | Menu options — `{"label", "action"}` entries and `{"type": "separator"}` dividers. |

---

## 16. File Upload (`<ui-file-upload>`)

A drag-and-drop uploader with real-time progress bars and server-side chunked append logic.

```html
<ui-file-upload multiple="true" accept="image/*,application/pdf" max_size_mb="10"
                auto_upload="true" label="Upload Files"></ui-file-upload>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `multiple` | `"true" \| "false"` | `"false"` | Allow multiple files. |
| `accept` | `str` | `"*/*"` | Accepted MIME types. |
| `disabled` | `"" \| "true"` | `""` | Disables interaction. |
| `auto_upload` | `"true" \| "false"` | `"true"` | Upload immediately on selection. |
| `show_progress` | `"true" \| "false"` | `"true"` | Show progress bars. |
| `max_size_mb` | `str` (number) | `"10"` | Per-file size limit in MB. |
| `label` / `description` | `str` | `"Upload Files"` / `""` | Dropzone title / subtitle. |

---

## 17. Schedule (`<ui-schedule>`)

A daily appointment schedule with a vertical time axis, configurable ticks, dynamic columns, and all-day events.

```html
<ui-schedule entries="{appointments}" columns="{columns}" tick_interval="30"
             start_hour="6" end_hour="20"></ui-schedule>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `entries` | `list[dict]` | `[]` | Appointment data source. |
| `time_attr` | `str` | `"time"` | Key holding the `HH:MM` time. |
| `duration_attr` | `str` | `"duration"` | Key holding duration in minutes. |
| `all_day_attr` | `str` | `"all_day"` | Key marking an entry as all-day. |
| `columns` | `list[dict]` | `[]` | Column specs `[{key, label}, …]`. |
| `tick_interval` | `int` | `30` | Minutes between time-axis ticks. |
| `start_hour` / `end_hour` | `int` | `6` / `20` | Visible day range (0–23). |
| `title` | `str` | `""` | Optional header title. |

---

## 18. Scroll Area (`<ui-scroll-area>`)

A styled scroll container with configurable scrollbar behaviour.

```html
<ui-scroll-area orientation="vertical" visibility="auto">
    <!-- long content -->
</ui-scroll-area>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `orientation` | `'vertical' \| 'horizontal' \| 'both'` | `'vertical'` | Scroll direction. |
| `visibility` | `'auto' \| 'always' \| 'hover'` | `'auto'` | Scrollbar visibility. |

---

## 19. Sidebar (`<ui-sidebar>`)

A collapsible sidebar container.

```html
<ui-sidebar side="left" collapsible="offcanvas">
    <!-- navigation content -->
</ui-sidebar>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `side` | `'left' \| 'right'` | `'left'` | Which side the sidebar docks to. |
| `collapsible` | `'offcanvas' \| 'icon'` | `'offcanvas'` | Collapse behaviour. |

---

## 20. Split Pane (`<ui-split-pane>` / `<ui-pane>` / `<ui-split-handle>`)

Draggable, resizable panes for building complex layouts.

```html
<ui-split-pane direction="horizontal">
    <ui-pane initial-size="220px" min_size="160px">Left</ui-pane>
    <ui-split-handle></ui-split-handle>
    <ui-pane initial-size="100%">Main content</ui-pane>
</ui-split-pane>
```

### Attributes

| Component | Attribute | Default | Description |
| :--- | :--- | :--- | :--- |
| `<ui-split-pane>` | `direction` | `'horizontal'` | `'horizontal' \| 'vertical'` split orientation. |
| `<ui-pane>` | `initial_size` | `'auto'` | Initial size (CSS length or percentage). |
| `<ui-pane>` | `min_size` / `max_size` | `'0px'` / `'none'` | Resize constraints. |
| `<ui-split-handle>` | `direction` | `'horizontal'` | Orientation of the draggable handle. |

---

## 21. Tabs (`<ui-tabs>` / `<ui-tab>`)

A tabbed interface with closable tabs, optional add button, and drag reordering.

```html
<ui-tabs target="editor">
    <ui-tab label="Notes" value="notes" checked="true"></ui-tab>
    <ui-tab label="Preview" value="preview" icon="👁" closable="true"></ui-tab>
</ui-tabs>
```

### Attributes

| Component | Attribute | Default | Description |
| :--- | :--- | :--- | :--- |
| `<ui-tabs>` | `target` | `""` | Target container/pane name the tabs switch. |
| `<ui-tabs>` | `selected_value` | `""` | Currently selected tab value. |
| `<ui-tabs>` | `show_add_button` | `"false"` | Show the "add tab" button. |
| `<ui-tab>` | `label` / `value` | `""` | Display label and identity value. |
| `<ui-tab>` | `name` | `"tabs-group"` | Radio group the tab belongs to. |
| `<ui-tab>` | `checked` | `"false"` | Initially selected. |
| `<ui-tab>` | `icon` | `""` | Optional leading icon (SVG / emoji). |
| `<ui-tab>` | `closable` | `"false"` | Show a close button. |

---

## 22. Tree View (`<ui-tree-view>`)

A recursive file/folder explorer.

```html
<ui-tree-view data="{tree_data}" selected_path="{selected_path}"></ui-tree-view>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `data` | `list[dict]` | `[]` | Nested data — `[{"label", "path", "children": […]}, …]`. |
| `selected_path` | `str` | `""` | Currently selected node path/key. |

---

## ThemeStore (`basis.ui.theme`)

`ThemeStore` is a reactive `Store` of CSS design tokens, registered by default under the name `"theme"` (so it's reachable as `$theme` in templates):

```python
from basis.ui.theme import ThemeStore

theme = ThemeStore()          # registers the store as "theme"
theme.dark_mode = True
theme.accent_color = "light-dark(#6E5FD8, #9384F5)"
```

It exposes `dark_mode` plus design-token attributes — `bg_primary`, `bg_secondary`, `bg_tertiary`, `text_primary`, `text_secondary`, `text_muted`, `accent_color`, `accent_bg`, `accent_text`, `border_color` — expressed with CSS `light-dark()` values so the UI suite adapts to both light and dark mode automatically.

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
