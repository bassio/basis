# Built-in UI Component Suite (`basis.plugins.ui`)

Basis ships with a built-in suite of UI components (`basis.plugins.ui`) designed for high visual appeal, accessibility, and smooth integration into Basis apps without requiring external CSS libraries or build steps.

The UI suite ships as an official in-tree plugin (`ui`, under `basis.plugins.ui`), registered through the standard `basis.plugins` entry point. When `app.bootstrap()` runs, Basis auto-registers the plugin and serves its component files at `/basis/plugins/ui` so the client VFS can import them; you then import the components you actually use (e.g. `import basis.plugins.ui.button.button`), exactly as you would any component module.

Every component here works with a mouse, a finger and a keyboard: hover styles are capability-guarded, touch targets follow `--touch-target`, and a suppressed focus ring is always replaced. The rule and the per-family details are in [Touch &amp; Pointer](touch-and-pointer.md).

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

A controlled boolean switch. `value` is the component's state and the owner drives it —
bind it to a store and handle the bubbling `change` to persist, or the switch and the
store will disagree on the next render.

```html
<!-- an inline switch -->
<ui-toggle value="{$theme.dark_mode}" first="off" second="on"
           onchange="{toggle_theme}"></ui-toggle>

<!-- a settings row: the label takes the line's start, the switch its end -->
<ui-toggle arrangement="row" label="Dark mode" value="{$theme.dark_mode}"
           first="off" second="on" onchange="{toggle_theme}"></ui-toggle>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `value` | `str` | `""` | The control's state: `second` means checked, anything else is `first`. |
| `first` / `second` | `str` | `""` | The values that mean off / on, so `value` can be a real domain value (`"b"`/`"a"`, `"public"`/`"private"`). |
| `label` | `str` | `""` | The switch's name. The control is a `<label>`, so this text *is* its accessible name. |
| `arrangement` | `'auto' \| 'row'` | `'auto'` | `auto` — the switch itself, labelled or not. `row` — a full-width settings row (`--row-height` tall, which is finger-sized at compact). |

The control never writes anywhere but its own `value`; persistence is the owner's job
through the `change` event, exactly as for [`ui-checkbox`](#10-checkbox-ui-checkbox).

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

### Container (`<ui-toast-container>`)

```html
<ui-toast-container></ui-toast-container>
```

| Attribute | Values | Default |
| :--- | :--- | :--- |
| `arrangement` | `'auto' \| 'corner' \| 'bottom'` | `'auto'` |

`auto` is a corner stack that spans the bottom edge at the compact breakpoint, padded by
`--page-gutter` and clear of the home indicator.

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

| Attribute | Values | Default |
| :--- | :--- | :--- |
| `arrangement` | `'auto' \| 'dialog' \| 'fullscreen'` | `'auto'` |

`auto` is a drop-down dialog that fills the screen at the compact breakpoint, where it
would otherwise compete with the on-screen keyboard for the same space.

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

On a phone a date is picked in a sheet, not in a popover: the composition is
[`ui-input` → `ui-modal[arrangement="sheet"]` → `ui-calendar`](responsive-layout.md#a-touch-date-picker),
and this calendar is the same calendar on a desktop.

---

## 12. Text Input (`<ui-text-input>`)

A labeled text input with optional prefix/suffix icons, helper text, and validation-error styling.

```html
<ui-text-input label="Email" input_type="email" value="{email}" error="{email_error}"
               placeholder="you@example.com" helper="We never share your email."></ui-text-input>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | `""` | Label shown above the input. |
| `placeholder` | `str` | `""` | Placeholder text. |
| `value` | `str` | `""` | Bound value (two-way). |
| `input_type` | `'text' \| 'email' \| 'password' \| 'search' \| 'number'` | `'text'` | HTML input type. |
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
| `arrangement` | `'auto' \| 'dialog' \| 'sheet' \| 'fullscreen'` | `'auto'` | Where the panel sits. `auto` is a centred dialog that becomes a bottom sheet at the compact breakpoint. |
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
| `arrangement` | `'auto' \| 'menu' \| 'sheet'` | `'auto'` | Where the menu sits. `auto` is anchored to the pointer on a desktop and to the bottom edge — as an action sheet — at the compact breakpoint, where the edge is the part a thumb reaches. |

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

## 19. Tabs (`<ui-tabs>` / `<ui-tab>`)

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

## 20. Tree View (`<ui-tree-view>`)

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

## ThemeStore (`basis.plugins.theme`)

`ThemeStore` is a reactive `Store` of CSS design tokens, registered by default
under the name `"theme"` (so it's reachable as `$theme` in templates):

```python
from basis.plugins.theme import ThemeStore

theme = ThemeStore()          # registers the store as "theme"
theme.dark_mode = True
theme.accent_color = "light-dark(#6E5FD8, #9384F5)"
```

It exposes `dark_mode` plus design-token attributes — `bg_primary`, `bg_secondary`, `bg_tertiary`, `text_primary`, `text_secondary`, `text_muted`, `accent_color`, `accent_bg`, `accent_text`, `border_color`, `border_hover`, `scrollbar_thumb` — expressed with CSS `light-dark()` values so the UI suite adapts to both light and dark mode automatically.

Theming is provided by the official **`basis.plugins.theme`** plugin — the token schema (`ThemeDefinition`/`ThemeTokens`), `ThemeStore`, and `<ui-theme-provider>` (which injects the tokens as CSS variables on `:root` and stamps `data-theme` / `data-theme-mode` on the document root). The `ui` and `shell` plugins depend on it.

### The `$theme` control plane (P3)

`$theme` also tracks the **active theme** and persists user prefs, so a reload keeps the choice (no FOUC — the SSR/CSR first paint reads the `basis_theme` cookie):

```python
theme.active_theme = "basis"          # currently applied theme id
# dual-path methods (client: local apply + cookie flush; server: apply + cookie):
theme.set_theme("basis")        # resolve + apply a theme by id
theme.set_mode("dark")          # "light" | "dark"
theme.set_accent("#e63946")     # accent override layered on the theme
```

The **installed themes** live on the sibling **`$themes`** catalog store (a `kind`-filtered slice of the shared registry — see [Theme Manager](#22-theme-manager-ui-theme-picker)).

---

## 21. Plugin Manager (`<ui-plugin-manager>`)

A live plugin manager bound to the app's `$plugins` registry store. It lists every registered
plugin (state, prefix, action count, dependencies) and provides a per-plugin toggle that calls
the store's `disable(name)` / `enable(name)` server actions — so a plugin is actually
unmounted/remounted server-side (routes, mounts, models, actions) and the panel re-renders from
the authoritative `new_state`.

```python
from basis.plugins.ui.plugin_manager import PluginManager
```

Use it in a template as `<ui-plugin-manager></ui-plugin-manager>`. It reads `$plugins.items`
reactively (no component state of its own). Disabled plugins stay listed with `state: "disabled"`
so they can be re-enabled. The `$plugins` store is framework-provided (created at bootstrap,
hydrated into `#basis-initial-state`), so no wiring is needed.

---

## 22. Theme Manager (`<ui-theme-picker>`)

A live theme manager bound to the `$themes` catalog store. It lists every installed theme
(name, modes, version, state) and provides an **Apply** button that calls `$theme.set_theme(id)`, plus a
header button that flips the mode via `$theme.set_mode(...)`. The choice persists through the
`basis_theme` cookie.

```python
from basis.plugins.ui.theme_picker import ThemePicker
```

Use it in a template as `<ui-theme-picker></ui-theme-picker>`. It reads `$themes.items`
reactively (no component state of its own).

`<ui-theme-picker>` and `<ui-plugin-manager>` share a common base — [`RegistryManager`](https://github.com/bassio/basis) —
rendering reactive rows over a `$registry.items` projection (one row chrome, one action dispatch;
the faces differ only by a `kind` filter and their row action). Themes are `BasisPlugin` subclasses
with `kind="theme"`, so they never appear in the plugin manager — they are managed separately
under the `basis theme` CLI instead (see [CLI Tooling](../08_appendix/cli.md)).

---

## 23. Nav (`<ui-nav>`)

One navigation declaration, rearranged by CSS instead of re-declared per viewport. The
same element is an inline row in a desktop header and a strip pinned to the bottom edge
on a phone — one DOM, no `if` on the viewport, no second component.

```python
from basis.plugins.ui.nav import Nav

links = [
    {"id": "home", "label": "Home", "href": "/"},
    {"id": "notes", "label": "Notes", "href": "/notes", "icon": "🗒", "badge": "3"},
]
```

```html
<shell-header>
    <span class="brand">My App</span>
    <ui-nav items="{links}"></ui-nav>
</shell-header>
```

### Attributes

| Attribute | Description |
| --- | --- |
| `items` | `[{"id", "label", "icon", "href", "badge"}]`. `id` defaults to `href` and is only needed when the highlighted item must be pinned or the href is not unique. |
| `arrangement` | `auto` (default) — inline row that docks to the bottom edge at the compact breakpoint. `inline` — never docks. `bottom` — docks at every viewport. `rail` — a column of glyphs, for `shell-activity-bar`. `drawer` — full-width rows, for inside a `shell-sidebar`. |
| `active` | The `id` of the item to highlight. Leave it empty (the normal case) and the highlight is derived from `$router.current_path`. |

The links are plain `<a href>`, so the nav is crawlable and works with no client at all.
The active item is **derived, not declared**: the path is stamped during SSR and updated
on `popstate`, so the right item is already highlighted in the first paint and stays
right after a client-side navigation.

Sizing comes from the page scale, so the nav owns no viewport query of its own:
`min-height: var(--control-height, 2rem)` for a row, `var(--row-height, 2rem)` for a
drawer row, and the docked strip pads itself clear of the home indicator with
`var(--safe-area-bottom)`.

> **A docked bar covers content — but the frame reserves the space.** The bottom
> arrangement floats over the page, so the nav publishes the height it takes
> (`--shell-bottom-inset`) at the document root and [`shell-site` / `shell-app`](shell-components.md)
> reserve exactly that as padding. Nothing to declare: dock a nav and the page clears it.

---

## 24. List (`<ui-list>` / `<ui-list-item>`)

Rows that read as one list, and the row that fills it. Two components, because that is
also the seam a windowed renderer needs: rows are ordinary children, so a virtualised list
can mount and unmount them without any call site changing.

```html
<ui-list>
    <ui-list-item arrangement="header">Today</ui-list-item>
    <ui-list-item label="Groceries" href="/notes/1">
        <span slot="leading">🗒</span>
        <span slot="trailing">2m</span>
    </ui-list-item>
</ui-list>
```

### `<ui-list>` attributes

None. The list contributes what a row cannot know on its own: the column, and the
hairline above every row but the first — decided by the list, because a `for` loop may
nest the rows it renders.

### `<ui-list-item>` attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `label` | `str` | `""` | The row's text. |
| `href` | `str` | `""` | Turns the row into a link. The anchor **fills the row's box**, so the whole row is the target a finger hits, while the link's own text stays its accessible name. |
| `arrangement` | `'row' \| 'header'` | `'row'` | `header` is a section header: sticky to the top of whatever scrolls it, `--control-height` tall. |
| `selected` | `"" \| "true"` | `""` | Marks the current row. Any truthy spelling works, so a bound `{$store.active}` is fine. |

Slots: `leading`, `trailing`, and the default slot for anything the label does not cover.

**Rows are sized by the page scale, not by the viewport**: `--row-height` (2rem on a
desktop, 3rem — 48px — on a phone) with the padding inside it, and at compact the row
carries `--page-gutter` so a list inside a frame with `gutter="none"` is full-bleed with
its text still on the page's margin.

> **Two ways in, and why.** A loop whose element is a *component* hands it per-item data
> as **attributes** (that is the framework's contract — see
> [footgun #2](loop-scope.md)), so `label`/`href` are how a looped row
> gets its content: `<ui-list-item for="note" in="{notes}" key="id"
> label="{note['title']}" href="{note['url']}">`. Slots carry a *rich* row for content the
> label cannot express, and then the loop goes around a plain element:
> `<div for="note" in="{notes}"><ui-list-item>…slotted content…</ui-list-item></div>`.

A header sticks at `top: 0` of its scroller. A frame with sticky chrome of its own (a
`shell-header` above a page-level scroll) offsets it with `--list-sticky-top`.

---

## 25. Segmented (`<ui-segmented>`)

One choice out of a handful, laid out as adjacent segments. The items are data, so one
declaration renders every segment.

```python
views = [{"id": "list", "label": "List"}, {"id": "grid", "label": "Grid"}]
```

```html
<ui-segmented items="{views}" value="{$view}" label="View"
              onchange="{set_view}"></ui-segmented>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `items` | `list` | `[]` | `[{"id", "label", "icon", "disabled"}]`, or plain strings (the string is both id and label). |
| `value` | `str` | `""` | The selected item's id. The control writes back the id the user picks and dispatches a bubbling `change` whose `detail.value` is that id. |
| `label` | `str` | `""` | The caption above the control, which also names the group. |
| `disabled` | `"" \| "true"` | `""` | Disables the whole control; a disabled segment reports `aria-disabled`. |

Each segment is a toggle button reporting `aria-pressed`, which is the honest role for
segments built from data. At compact the control takes the full width and the segments
share it; a set that does not fit scrolls, snapped, rather than squeezing its labels.

---

## 26. Slider (`<ui-slider>`)

A single value picked out of a continuous range. The control is the native
`<input type="range">`, so a finger, a mouse and a keyboard already know how to drive it;
the family adds the theme's look, the filled rail, and a thumb that grows to
`--touch-target` on a coarse pointer.

```html
<ui-slider value="{$opacity}" min="0" max="100" step="5" label="Opacity"
           oninput="{set_opacity}"></ui-slider>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `value` | `str \| number` | `""` | The current value; clamped into `min`…`max`. The control writes back what it is dragged to and lets the `input`/`change` events bubble. |
| `min` / `max` / `step` | `str \| number` | `0` / `100` / `1` | The range and its granularity. |
| `label` | `str` | `""` | The caption, shown with the current value; it also names the control. |
| `disabled` | `"" \| "true"` | `""` | Disables the control. |

The rail's fill follows the value through `--slider-fill`, so it is a stylesheet's
business how much of the rail the value colours.

---

## 27. Stepper (`<ui-stepper>`)

A number nudged one increment at a time — the control for a value that is roughly right
already. Typing is deliberately out of scope: a number a user must enter exactly is a
[`ui-text-input`](#12-text-input-ui-text-input).

```html
<ui-stepper value="{$rows}" min="1" max="8" label="Rows"
            onchange="{set_rows}"></ui-stepper>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `value` | `str \| number` | `""` | The current value, held inside the bounds. |
| `min` / `max` | `str \| number` | `""` (unbounded) | The bounds. |
| `step` | `str \| number` | `1` | How far one press moves. |
| `label` | `str` | `""` | The row's caption, which also names the button group. |
| `disabled` | `"" \| "true"` | `""` | Disables both buttons. |

At a bound the nudge is a no-op and the button that produced it reports
`aria-disabled`, so the two targets never move under the user's finger. A change
dispatches a bubbling `change` whose `detail.value` is the new number.

---

## 28. Progress (`<ui-progress>`)

How far along a job of known length is — and, with no `value`, an indeterminate sweep
that says "working" without pretending to know how much is left.

```html
<ui-progress value="{$done}" total="{$count}" label="Uploading"></ui-progress>
<ui-progress label="Connecting"></ui-progress>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `value` | `str \| number` | `""` | How far along, on the `total` scale. Empty means indeterminate. |
| `total` | `str \| number` | `100` | The scale's end. (Not `max`: a bare `{max}` in a template resolves to the builtin, never to the prop.) |
| `label` | `str` | `""` | The caption, shown with the percentage; it also names the bar. |
| `variant` | `'primary' \| 'success' \| 'warning' \| 'danger'` | `'primary'` | The fill's colour. |
| `size` | `'sm' \| 'md' \| 'lg'` | `'md'` | The track's thickness. |

The fraction travels as `--progress-value`, so a theme can restyle the bar without
touching Python. An indeterminate bar announces no number at all (no `aria-valuenow`),
and the sweep stops — without losing its meaning — for a user who asked for less motion.

---

## 29. Skeleton (`<ui-skeleton>`)

The shape of content that is still on its way. A placeholder is only honest when it is
the *size* of the thing it stands in for, so the geometry is the API.

```html
<ui-skeleton variant="text" lines="3"></ui-skeleton>
<ui-skeleton variant="circle" height="2.5rem"></ui-skeleton>
<ui-skeleton variant="rect" height="8rem"></ui-skeleton>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `variant` | `'text' \| 'rect' \| 'circle'` | `'text'` | A paragraph, a block, or an avatar. |
| `lines` | `number` | `1` | How many bars a `text` skeleton has; a multi-line skeleton shortens its last line. |
| `width` / `height` | `str` | variant default | CSS lengths for the box. |

`ui-progress` and `ui-skeleton` are the two families that own **no viewport query at
all**: they are the first paint on a slow link, so they have to be right before the
viewport has been answered — and their geometry does not change with the width.

---

## 30. Fab (`<ui-fab>`)

The one action a screen is offering. Legitimate on a desktop, and the control a phone
needs most, because the thumb lives at the bottom edge.

```html
<ui-fab icon="＋" label="New note" onclick="{create_note}"></ui-fab>
```

### Attributes

| Attribute | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `icon` | `str` | `""` | The glyph (HTML string or emoji). |
| `label` | `str` | `""` | The accessible name — and the visible text of an extended FAB. |
| `extended` | `"" \| "true"` | `""` | Shows the label beside the icon, turning the circle into a pill. |
| `disabled` | `"" \| "true"` | `""` | Disables the button. |

The FAB is fixed to the viewport's inline end, one `--page-gutter` in from the corner,
and **clears whatever the page has pinned to the bottom edge**: a
[docked `ui-nav`](#23-nav-ui-nav) publishes the strip's height as `--shell-bottom-inset`
and the FAB reads it, so the two never collide without either component knowing about the
other. A click is a plain DOM click, so the owner binds `onclick` as it would on a button.

---

## Using UI Components in Custom Components

Because components map to HTML Custom Elements, you can use `basis.plugins.ui` tags directly inside your component HTML templates:

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

> [!TIP]
> The `basis.plugins.ui` components are designed to be **customized and extended** — via attributes, CSS variable theming, plain CSS overrides, and Python subclassing. See [Styling Components](styling-components.md) for look & feel, and [Extending & Customizing Components](extending-components.md) for Python-level changes.
