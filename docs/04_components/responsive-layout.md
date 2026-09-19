# Responsive Layout

A Basis app is written **once** and is correct on a phone, a tablet and a desktop. There is
no mobile build, no second component tree, and no `ui-mobile-*` family: a phone is an
**arrangement** of the same components, resolved in CSS.

This page is the contract. It says what the four axes are, what each family becomes at
compact, and where an app is allowed to add a rule of its own.

---

## 1. One tree, four axes

Everything a component does differently by viewport falls into exactly one of these:

| Axis | Mechanism | Answers |
| :--- | :--- | :--- |
| **Scale** | the page's `:root` variables (`--control-height`, `--row-height`, `--page-gutter`) | "how big is a control / a row / a margin on this device?" |
| **Structure** | `arrangement` (a prop → `data-arrangement`) + `compact_block(...)` | "where does this box sit, and how is it laid out?" |
| **Behaviour** | `$device.tier` in **Python** | "which callback should run?" — never what the markup looks like |
| **Capability** | `@media (hover: hover)` / `(pointer: coarse)`, `--touch-target`, `reduced_motion_block()` | "what can this input do?" |

They compose. A 1280px touchscreen laptop keeps its dense controls (the *window* is not a
phone) while its coarse pointer still gets finger-sized targets (the *input* is a finger). A
400px window on that same laptop gets both.

The rule that keeps it honest:

> **Markup is identical at every viewport.** Nothing structural branches on the viewport,
> because the server has no viewport. A template that reads `$device` renders one tree on
> the server and another in the browser, and hydration can only report that as a mismatch.

---

## 2. The scale scope

The page declares the phone's sizes once, on `:root`, inside a compact block; every
component inherits them with **the desktop value as the fallback**:

```css
@media (max-width: 767px) {
    :root {
        --control-height: var(--touch-target, 44px);
        --row-height: 3rem;
        --page-gutter: 1rem;
    }
}
```

| Variable | Desktop | Compact | Who reads it |
| :--- | :--- | :--- | :--- |
| `--control-height` | `2rem` | the touch target | `ui-nav`, `ui-tab`, `ui-btn-md`, `ui-segmented`, `ui-stepper`, `ui-slider` |
| `--row-height` | `2rem` | `3rem` | `ui-nav` (drawer), `ui-list-item`, `ui-toggle[arrangement="row"]` |
| `--page-gutter` | `1.5rem` | `1rem` | the shell regions, `ui-list-item` |

Read them with `var(--control-height, 2rem)`. Two consequences worth knowing:

- **The fallback *is* the desktop size.** A component whose natural size is already smaller
  than the scale must not adopt it — a floor above what a component already is reflows every
  desktop app. `ui-btn-sm` deliberately stays denser than the scale and states its own
  height.
- **A component can be phone-sized without owning a query** — and it must read these, or a
  phone silently gets the desktop geometry.

```python
class ListItem(Component):
    @classmethod
    @scoped
    def style(cls):
        return _BASE_CSS + compact_block(_COMPACT_CSS)      # only where geometry changes
```

---

## 3. What each family becomes at compact

| Family | Desktop | Compact |
| :--- | :--- | :--- |
| `ui-nav` | an inline row in the header | a bar pinned to the bottom edge, safe-area padded, publishing `--shell-bottom-inset` |
| `ui-modal` | a centred dialog | a sheet flush with the bottom edge |
| `ui-context-menu` | anchored to the pointer | a bottom-anchored action sheet |
| `ui-command-palette` | a centred dialog | full screen |
| `ui-toast-container` | a corner stack | a full-width strip above the bottom edge |
| `ui-list` / `ui-list-item` | dense rows | `--row-height` rows (48px), the page gutter inside the row |
| `ui-segmented` | content-sized segments | full width, equal shares, `scroll-snap` when they overflow |
| `ui-slider` | a themed range input | a 44px thumb, a `--control-height` rail |
| `ui-stepper` | ± buttons at `--control-height` | 44px buttons |
| `ui-toggle[arrangement="row"]` | label left, switch right | `--row-height` tall |
| `ui-progress`, `ui-skeleton` | — | *unchanged*: they are the first paint on a slow link, so they must be right before the viewport has been answered |
| `shell-site` | header / main / footer in a row | a condensed sticky header, a stacked footer, the page gutter on main |
| `shell-app` | a workbench of rails, sidebars and panes | a phone frame: the rail docks as the bottom bar, the sidebars become drawers |

`arrangement="auto"` is the default and means exactly this table: the desktop idiom until
the compact breakpoint, the phone idiom after it. **An explicit value is honoured at every
viewport** — that is the escape hatch. `<ui-nav arrangement="bottom">` docks on a desktop
too, and `<ui-modal arrangement="sheet">` is a sheet everywhere.

---

## 4. What the author writes

```html
<shell-site>
    <shell-header sticky="true">
        <span class="brand">My App</span>
        <ui-nav items="{nav_items}"></ui-nav>       <!-- inline row → bottom bar -->
    </shell-header>
    <shell-main>
        <ui-list> … </ui-list>                       <!-- rows size themselves -->
    </shell-main>
    <ui-fab icon="＋" label="New note"></ui-fab>     <!-- clears the docked bar -->
</shell-site>
```

| Author writes | Framework does |
| :--- | :--- |
| `<ui-nav items="…">` | inline bar → pinned bottom bar with labels and safe-area padding |
| `<ui-modal title="…">…</ui-modal>` | centred dialog → bottom sheet |
| `<ui-list>` with `<ui-list-item label="…">` | dense rows → 44px+ rows with the page gutter |
| `<shell-site>` | condensed sticky header, stacked footer, gutter on main |
| `<ui-input>` / `<ui-segmented>` / `<ui-slider>` / … | finger-sized controls from the scale, zero media queries in the app |

---

## 5. Where an app adds its own rules

An app is still allowed to be responsive — it just may not invent a second breakpoint, and
it may not write geometry into markup.

- **Use the framework's queries.** Import the helpers rather than typing a width:

    ```python
    from basis.shared.breakpoints import compact_media, compact_block

    # a page/component stylesheet
    return _BASE_CSS + compact_block(_COMPACT_CSS)
    ```

    `compact_media()` / `compact_query()` are the same string `$device.tier` answers, so CSS
    and Python cannot drift. A hand-written `@media (max-width: 860px)` is the failure mode
    this prevents: it silently disagrees with `$device` and with every component.

- **Never write layout into a template.** `style="width: 240px"` cannot be reached by a media
  query. Emit a custom property instead (`style="{panel_vars}"`) and let the stylesheet
  decide what to do with it — a rule can then restate it at compact.

- **Full-bleed comes from the frame, not from a negative margin.** A list that cancels the
  page gutter with `margin-inline: calc(var(--page-gutter) * -1)` overflows horizontally when
  its parent is *not* padded, which is how a phone ends up with a page that scrolls sideways.
  Let the frame own the gutter (`gutter="none"`) and let the row own its padding
  (`ui-list-item` does).

- **A box that answered its own width.** If a component's layout should follow the *box* it
  was given rather than the window (a list inside a narrow sidebar, on a wide screen), the
  caller declares a container and the component asks it:

    ```css
    .shell-sidebar { container-type: inline-size; container-name: pane; }
    ```
    ```python
    from basis.shared.breakpoints import container_block
    return container_block("pane", _NARROW_CSS)
    ```

    `container-type: inline-size` is free on a box whose width is definite and fatal on a
    content-sized one (it collapses to zero), which is why the framework names no containers
    of its own and each caller opts in where it knows the width. See
    [Styling Components](styling-components.md) §8.

- **Behaviour may branch on the tier; markup may not.** `$device.tier` is `"regular"` on the
  server and corrected after mount, so Python can only *enhance* what the phone already shows:

    ```python
    def on_item_click(self, event):
        if self.S.get("device").tier == "compact":
            self.close_drawer()
    ```

---

## 6. The contract, as a test

`tests/test_mobile_arrangement.py` walks every component in `basis.plugins.ui` and
`basis.plugins.shell` and fails the build when:

1. a template writes a layout property into an inline `style` (a `*_vars` computed emitting
   custom properties is the sanctioned shape);
2. a width query in a component stylesheet is not the shared constant — capability queries
   (`hover`, `pointer`, `prefers-reduced-motion`) are the exception, because they answer a
   device capability rather than a viewport;
3. a template reads `$device`;
4. a `mobile_*` dimension prop is declared but no compact block consumes it.

It is the same posture as the hover audit in [Touch & Pointer](touch-and-pointer.md): a
mechanical guard beats a review habit.

---

## 7. Recipes

### A list that is full-bleed on a phone

```html
<shell-main gutter="none">
    <ui-list>
        <ui-list-item arrangement="header">Today</ui-list-item>
        <ui-list-item for="note" in="{notes}" key="id"
                       label="{note['title']}" href="{note['url']}"></ui-list-item>
    </ui-list>
</shell-main>
```

The frame stops padding, the rows pad themselves with `--page-gutter`, and the whole row is
the tap target because the row's own link stretches over its box.

### A touch date picker

There is no `ui-date-picker`, on purpose: a calendar is a calendar, and a phone picks a date
by opening *one* sheet with one inside it.

```python
class DueDate(Component):
    open = ""
    due = ""

    def open_picker(self, event):
        self.open = "true"

    def on_picked(self, event):
        # ui-calendar dispatches a bubbling `change` with detail.selected_date.
        self.due = event.detail.selected_date
        self.open = ""
```

```html
<div class="due">
    <ui-input label="Due" value="{due}" readonly="true"
              onclick="{open_picker}"></ui-input>
    <ui-modal title="Pick a date" open="{open}" onchange="{on_picked}">
        <ui-calendar selected_date="{due}"></ui-calendar>
    </ui-modal>
</div>
```

On a desktop the same declaration is a centred dialog, on a phone it is a sheet — and the
calendar drops its own 380px frame at compact so the month grid gets the whole width.

---

*See also [Built-in UI Suite](ui-components.md), [Shell Components](shell-components.md),
[Touch & Pointer](touch-and-pointer.md), and
[Styling Components](styling-components.md).*
