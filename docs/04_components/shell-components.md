# The App Shell (`basis.plugins.shell`)

Basis ships an application-frame plugin: the chrome of a "workbench" app (title bar,
activity rail, sidebars, split panes, status bar) and of a document-flow site (header,
main, footer). Everything in it is a *skeleton with slots* — a part answers **how it
behaves and how it is sized**, and your app answers **what it looks like**.

The shell ships as an official in-tree plugin (`shell`, under `basis.plugins.shell`),
auto-registered by `app.bootstrap()` and served at `/basis/plugins/shell` so the client
VFS can import it. Import the parts you use (e.g.
`from basis.plugins.shell.title_bar import TitleBar`); every part is also subclassable,
which is how the `basis init` scaffold gives you app-owned chrome.

---

## 1. The two frame paradigms

| | Workbench (`shell-app` / a scaffolded `.app-container`) | Site (`shell-site`) |
| :--- | :--- | :--- |
| Mental model | Fixed viewport, inner scroll (editor / dashboard) | Document flow, the page scrolls (marketing site, docs) |
| Parts | `TitleBar` → `Workspace` → `StatusBar` | `Header` → `Main` → `Footer` |
| Height | `100dvh` with a `100vh` fallback | `min-height: 100dvh` |

`AppShell` (`<shell-app>`) and `SiteShell` (`<shell-site>`) are ready-made composers, but
they are *convenience only*: the parts work standalone, and the `basis init` scaffold
composes the raw parts directly so the frame is app-owned code you can edit. A frame is
just a column stack of parts:

```html
<div class="app-container">
    <shell-stack direction="column" size="1 1 auto">
        <shell-title-bar height="48px">
            <shell-sidebar-trigger target="#sidebarLeft"></shell-sidebar-trigger>
            <span class="app-title">My App</span>
        </shell-title-bar>
        <shell-stack direction="row" size="1 1 auto" layout="workbench">
            <shell-activity-bar width="56px">
                <span slot="top">◆</span>
            </shell-activity-bar>
            <shell-sidebar-left id="sidebarLeft" width="240px" collapsible="offcanvas">
                <div class="panel">Explorer</div>
            </shell-sidebar-left>
            <shell-splitter direction="horizontal"></shell-splitter>
            <shell-main-container>
                <span>Editor</span>
            </shell-main-container>
        </shell-stack>
        <shell-status-bar height="28px">
            <span class="status-item">Ready</span>
        </shell-status-bar>
    </shell-stack>
</div>
```

> **Hosts are `display: contents`.** Each part's custom-element host generates no box;
> the real flex item is the inner `.shell-*` element. Sizing therefore belongs to the
> part (`height`/`width`/`size` props), never to `style=` on the tag, and CSS that
> targets a part's box has to step through the host
> (`.shell-stack[data-layout="workbench"] > shell-activity-bar > .shell-activity-bar`).

---

## 2. Sizing as props

Every dimension is a reactive prop with a sensible default, so a frame can be tailored
from one place — the root component's class attributes:

```python
class AppContainer(Component):
    titlebar_height = "48px"
    activitybar_width = "56px"
    sidebar_left_width = "240px"
    statusbar_height = "28px"
```

A prop travels to the browser as a **CSS custom property**
(`style="--shell-titlebar-height: 48px"`) and the part's own rule consumes it
(`flex: 0 0 var(--shell-titlebar-height, 48px)`). That indirection is what lets a media
query restate the value at the compact breakpoint while the prop stays the single source
of truth — an inline `flex` would out-rank every stylesheet rule.

| Part | Size props | Notes |
| :--- | :--- | :--- |
| `TitleBar` | `height`, `mobile_height` | Compact top app bar height |
| `StatusBar` | `height`, `mobile_height`, `mobile` | `mobile="hidden"` (default) or `"slim"` |
| `ActivityBar` | `width`, `mobile_height` | Bottom navigation height at compact |
| `Sidebar` / `SidebarLeft` / `SidebarRight` | `width`, `icon_width`, `mobile_width` | `mobile_width` is the drawer width |
| `TabsBar` | `height` | |
| `Splitter` | `size`, `min_size` | `min_size` is the smallest pane it drags to |
| `Stack` | `size`, `gap`, `direction`, `align`, `justify` | The layout atom every part composes with |

---

## 3. Sidebar states: docked and drawer

A sidebar has two independent states, because a docked panel and a phone drawer are not
the same control:

| Prop | Attribute | Meaning |
| :--- | :--- | :--- |
| `collapsed` | `data-state="collapsed" \| "expanded"` | **Docked**: with `collapsible="icon"` it becomes a thin rail, with `"offcanvas"` it disappears. Ignored at the compact breakpoint. |
| `open` | `data-drawer="open" \| "closed"` | **Drawer**: read only at the compact breakpoint, where the sidebar leaves the flow and slides in over a backdrop. Defaults to closed. |

`ShellSidebarTrigger` (`<shell-sidebar-trigger target="#sidebarLeft">`) flips whichever
state fits the viewport (see §4). It writes to the target's **component instance**, not to
a DOM attribute, so the sidebar's own bindings re-render and several triggers pointing at
one sidebar always agree.

```html
<shell-sidebar-trigger target="#sidebarLeft"></shell-sidebar-trigger>
<shell-sidebar-left id="sidebarLeft" width="240px" open="{$app_state.drawer_open}">
    ...
</shell-sidebar-left>
```

Both are ordinary props: a store can own them, and a template can bind them.

---

## 4. Responsive behaviour and the breakpoint contract

The server cannot know the viewport, so the compact arrangement is **CSS only** — the
markup a server sends is byte-identical at every width, which is what keeps SSR and
hydration honest. Two pieces make that work.

### 4.1 The tier, for behaviour

`$device.tier` is a reactive field derived from two declared media queries:

| Tier | Viewport | Typical client |
| :--- | :--- | :--- |
| `"compact"` | ≤ 767px | Phones (portrait and landscape) |
| `"medium"` | 768–1023px | Tablets |
| `"regular"` | ≥ 1024px | Desktop |

```html
<span if="{$device.tier == 'compact'}">Phone layout controls</span>
```

```python
@computed
def page_size(self) -> int:
    return 20 if self.device_compact else 100

@computed(dependencies=["$device.compact"])
def device_compact(self) -> bool:
    return bool(self.S["device"].compact)
```

The server serializes the neutral tier (`"regular"`), the browser answers the queries
after mount, and the DAG re-renders whatever read them. Use the tier for **behaviour**
(chunk a list, choose a control, decide which state a toggle flips) — for **layout**, use
CSS, because a structural difference keyed on the tier would only appear after the
browser answered.

The boundaries live in one place, `basis.shared.breakpoints`, and the same constants also
produce the `@media` text the shell's stylesheets use — so a layout rule and the tier
field can never disagree:

```python
from basis.shared.breakpoints import compact_block, compact_query

COMPACT_MAX_WIDTH  # 767
compact_query()    # "(max-width: 767px)"  — the query $device.compact declares
compact_block(css) # the same query as an @media prelude, for your own CSS
```

### 4.2 The arrangement, declaratively

Put `layout=` on the stack that holds your chrome. It says what that stack becomes at the
compact breakpoint:

| `layout=` | At compact width |
| :--- | :--- |
| `"none"` *(default)* | unchanged |
| `"column"` | this stack restacks on one axis |
| `"workbench"` | restacks **and** arranges the frame for a phone |

`layout="workbench"` is the phone frame: the main surface comes first and fills the
width, the activity rail becomes the **bottom navigation** beneath it (safe-area padded),
sidebars leave the flow and become **overlay drawers**, and drag splitters are dropped
(a 4px divider is not a touch affordance). Your markup does not change — the same parts,
rearranged.

What each part does at compact width:

| Part | Compact form |
| :--- | :--- |
| `TitleBar` | Compact top app bar (`mobile_height`, default `44px`) |
| `ActivityBar` | Bottom navigation (`mobile_height`, default `52px`), horizontal, safe-area padded |
| `Sidebar` | Overlay drawer from its own edge, with a backdrop that closes it on tap |
| `StatusBar` | Hidden (`mobile="hidden"`, the default) or slim (`mobile="slim"`) |
| `MainContainer` | The primary surface (first in the workbench band) |
| `Splitter` | Removed from the flow |
| `SiteShell` family | Document flow already stacks; the header/footer stay as authored |

Because it is all CSS, the arrangement applies the moment the page paints — no client
round-trip, no layout shift after hydration.

---

## 5. Layout primitives

- **`Stack`** (`<shell-stack>`) — the layout atom: a flex/grid container with `direction`,
  `size` (the `flex` shorthand), `gap`, `align`, `justify`, `wrap`, `overflow`, plus
  `layout` for the compact arrangement above.
- **`Splitter`** (`<shell-splitter>`) — a drag-to-resize divider placed *between two Stack
  children*. The divider owns the interaction: it samples its neighbours' sizes on
  `pointerdown` and mutates them during `pointermove` (Pointer Events + pointer capture,
  so there are no window listeners and no leaked proxies). Gate it with an `if=` binding
  when resizing is optional.
- **`TabsBar`** (`<shell-tabs-bar>`) — a fixed-height strip skeleton; put `ui-tabs` or
  your own tabs inside.

`ui-split-pane` predates these primitives and is on its way out in their favour.

---

## 6. Subclassing the chrome

The scaffold (`basis init`) generates thin subclasses that keep the shell tag and replace
it in the registry, so `<shell-title-bar>` renders *your* class:

```python
from basis.plugins.shell.title_bar import TitleBar

class MyTitleBar(TitleBar):
    height = "56px"

    def style(self):
        """
        .shell-title-bar { background: var(--accent-color); }
        """
```

Keep the part's `style()` rules composable: if you re-declare the sizing, keep it on the
custom property (`flex: 0 0 var(--shell-titlebar-height, 48px)`) rather than hard-coding a
length, or the compact rules will silently stop applying to your copy.

See [Styling Components](styling-components.md) for the token/`style` mechanics and
[Extending Components](extending-components.md) for subclassing in general.
