# Touch &amp; Pointer

Basis assumes **one catalogue for every input device**. The same `<ui-button>`,
tab strip or context menu serves a mouse, a finger and a keyboard; what changes is
how it is *presented*, and that is CSS's job, not a second component tree's.

The rule this page documents is short:

> **Hover is decoration. It may add emphasis — it may never be the only way to see
> or reach something.**

It is a rule with teeth: `tests/test_touch_pointer.py` walks every component in the
`ui` and `shell` plugins and fails the build if a component breaks it. This page
explains what that test checks, and how to write component CSS that passes.

---

## 1. Why hover is not a capability

On a phone, `:hover` is not "the mouse is over this". Engines synthesise it on tap
and — unlike a mouse — **never un-synthesise it**. Two failures follow:

- **Sticky state.** A tap starts a hover style that stays until you tap somewhere
  else. The control looks permanently pressed/selected.
- **Unreachable affordances.** Anything *revealed* by hover (a scrollbar, a close
  glyph, a tooltip) either never appears or appears only by accident.

So the framework treats hover like any other capability — it gets a media query,
and the query lives in one place.

---

## 2. The queries

`basis.shared.styling` holds the input-capability queries next to the viewport ones
(`compact_query()` and friends), so a component imports one module to write either:

| Constant | Query | Use it for |
| :--- | :--- | :--- |
| `HOVER_QUERY` | `(hover: hover)` | Anything that is a *hover* style: colour, lift, shadow |
| `NO_HOVER_QUERY` | `(hover: none)` | Degrading a mode that assumed a pointer (e.g. a hover-only scrollbar) |
| `COARSE_QUERY` | `(pointer: coarse)` | **Sizing**: the primary input is a finger |
| `TOUCH_TARGET` | `44px` | The fallback value of the `--touch-target` token |
| `REDUCED_MOTION_QUERY` | `(prefers-reduced-motion: reduce)` | **Motion**: a user who asked for less movement |

`pointer`, not `hover`, answers the sizing question. A touchscreen laptop whose
primary pointer is a mouse reports `pointer: fine` and keeps its dense controls,
while its touchscreen still gets touch *events*; a phone is `coarse` throughout.

Motion is a capability like any other: endless or sweeping animation is the case
`reduced_motion_block(css)` exists for, and a family that animates stops moving under it
without losing what it means — an indeterminate
[`ui-progress`](ui-components.md#28-progress-ui-progress) still says "working" when it is
still, and a [`ui-skeleton`](ui-components.md#29-skeleton-ui-skeleton) is still the shape of
the content that has not arrived. The viewport and input queries answer *what the device
is*; this one answers *what the user asked for*, so a component reads it directly rather
than through a `$device` branch in a template.

The same `HOVER_QUERY` is what `$device.hover` declares, so a component can style
with CSS and behave in Python from one source:

```python
class DeviceStore(Store):
    hover = media(HOVER_QUERY, default=True)   # desktop-safe neutral
```

```html
<ui-button label="Share" if="{$device.hover}"></ui-button>
<Toggle label="Quick actions" if="{not $device.hover}"></Toggle>
```

The server ships the neutral (`True`), so SSR and the client's first paint agree;
the browser answers after mount and only the affected nodes re-render.

---

## 3. Writing a hover rule

Put the rule in an explicit guard. There is no helper and no rewrite pass — the
guard is visible in the source, greppable, and obvious to the next reader:

```css
@media (hover: hover) {
    .ui-btn-primary:hover:not(:disabled) {
        background-color: color-mix(in srgb, var(--accent-color) 85%, black);
        transform: translateY(-1px);
    }
}
```

Then give the **touch path** the same *intent* with `:active` — a finger gets
feedback on press, not on hover:

```css
.ui-btn-primary:active:not(:disabled) { transform: translateY(0); }
```

Guard as a group when a component has several hover rules (wrapping the whole
block is clearer than five one-rule guards), and keep non-hover states *outside*
the guard — `[data-dragging="true"]`, `:checked`, `:focus-visible` all apply on
touch.

> [!TIP]
> A hover rule that *reveals* something needs more than a guard: it needs a
> non-hover default. `ScrollArea` is the worked example — `visibility="hover"`
> makes the thumb transparent until hover, so under `(hover: none)` the same
> selector restores a visible thumb instead of leaving a scrollbar nobody can
> summon.

---

## 4. Touch targets and the `--touch-target` token

The token is part of the theme (`touch_target`, kind `size`, default `44px` — the
Apple HIG / WCAG 2.5.5 floor). Components apply it under a coarse pointer:

```css
@media (pointer: coarse) {
    .ui-tab-container { min-height: var(--touch-target, 44px); }
}
```

Two things to respect when adding one:

- **Keep the glyph, grow the hit area.** A 16px close glyph inside a 32px tab is
  the right *visual* at every size, so the target is expanded with a transparent
  pseudo-element rather than by inflating the glyph:
  ```css
  .tab-close { position: relative; }

  @media (pointer: coarse) {
      .tab-close::after {
          content: '';
          position: absolute;
          inset: calc((var(--touch-target, 44px) - 16px) / -2);
      }
  }
  ```
  (`elementFromPoint` sees the pseudo-element as the glyph, which is how the
  browser lane tests it.)
- **Only dense chrome opts in.** Real form controls (`input`, `select`,
  `textarea`) get one global coarse rule in the page's base CSS; everything else
  sizes itself, because a blanket `min-height` would stretch deliberately compact
  layouts. An app that wants denser chrome on a tablet lowers the token:
  ```python
  class AppTheme(ThemeStore):
      def __init__(self):
          super().__init__()
          self.touch_target = "36px"
  ```

---

## 5. Keyboard focus is part of the same rule

A control that suppresses the UA ring (`outline: none`) must draw one of its own,
or keyboard users lose the focus indicator that touch users never had:

```css
.ui-btn:focus-visible {
    outline: 2px solid var(--accent-color, #007acc);
    outline-offset: 2px;
}
```

Two idioms are in play, and both satisfy the contract check:

- **`:focus-visible` on the control itself** — buttons, tabs, menu rows, icon
  buttons, accordions.
- **`:focus-within` / sibling propagation** — when the focusable element is
  visually hidden (a checkbox's native input, an input whose wrapper carries the
  border). The ring belongs on the visible box:
  ```css
  .ui-tab-input:focus-visible + .ui-tab-container { outline: 2px solid var(--accent-color); }
  .ui-input-inner:focus-within { box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-color) 15%, transparent); }
  ```

---

## 6. Per-family notes

Most families only needed the guard. These changed behaviour:

| Family | On a coarse pointer |
| :--- | :--- |
| `Button` | `sm`/`md` reach the target height; every variant gained an `:active` press state; `:focus-visible` ring |
| `Tab` / `Tabs` | the row is target-height, the close glyph keeps 16px with a 44px hit area, and it stays visible without hover; the hidden radio carries the focus ring |
| `ScrollArea` | `visibility="hover"` degrades to an always-visible thumb under `(hover: none)` |
| `ContextMenu` | rows are target-height with `:active`; **the trigger is yours to provide** — see below |
| `Toggle` | the native input is visually hidden instead of `display: none`, so the switch is back in the tab order and can show a ring |
| `Icon` | `interactive` is a *class* (not a boolean-in-an-attribute), with `:active`, a coarse hit area, and the modifier classes joined in one computed |
| `Calendar`, `TreeView`, `Badge`, `Toast`, `Modal`, `FileUpload`, `Sidebar`, registry/theme managers | guarded hover, press state, focus ring, target size |

### The context menu has no touch trigger of its own

`<ui-context-menu>` is a positioned overlay: something must call `show(x, y)`.
The desktop convention is a right-click binding in app code:

```html
<div oncontextmenu="{open_menu}">…</div>
```

A phone has no right-click, so the app must offer a real affordance — a
`⋮` button, a long-press, or a swipe action. The long-press *recognizer* arrives
with the gesture vocabulary (M2.2); until then the honest pattern is a visible
button:

```html
<ui-icon content="⋮" interactive="True" onclick="{open_menu_from_button}"></ui-icon>
```

The pointer position stops deciding where the menu is on a phone: with the default
`arrangement="auto"` it becomes a full-width action sheet on the bottom edge, so the
coordinates the trigger passes are simply ignored. One call site serves a right-click and
a `⋮` button alike.

`<ui-command-palette>` has the same shape: it opens on `Cmd/Ctrl+K`, so a phone
needs an app-supplied control that flips `open`.

---

## 7. The contract, as a test

`tests/test_touch_pointer.py` imports every component in `basis.plugins.ui` and
`basis.plugins.shell`, reads each one's CSS, and asserts:

1. **No unguarded `:hover`** — every hover rule is inside `@media (hover: hover)`.
2. **Capability queries are the shared constants** — no component invents
   `(hover: none)`-style literals.
3. **A suppressed outline is replaced** — `outline: none` implies
   `:focus-visible` or `:focus-within` in the same component.
4. **Coarse-pointer sizing is token-driven** — every `(pointer: coarse)` block
   uses `var(--touch-target, …)`, and the token exists in the theme schema
   (`TOKEN_SLOTS["touch_target"] == "size"`).

Behaviour is verified in a real engine by `tests/browser/test_touch.py`, which
drives an iPhone 13 descriptor (`hover: none`, `pointer: coarse`) and asserts that
a tap does not latch hover paint, that controls are finger-sized, that the tab
close hit area grew while its glyph did not, and that `Tab` still paints a focus
ring.

---

## 8. Adding a family

1. Import the class and write the styles as usual.
2. Wrap every `:hover` rule in `@media (hover: hover) { … }`.
3. Add `:active` for the press, and `:focus-visible` wherever you suppressed the
   UA ring.
4. Add a `@media (pointer: coarse)` block for anything a finger has to hit, using
   `var(--touch-target, 44px)`.
5. Run `pytest tests/test_touch_pointer.py` — it will tell you which of the five
   clauses you missed.

---

*See also [Responsive Layout](responsive-layout.md) — the viewport counterpart of this
page: how a component rearranges itself, and why a capability query is not a breakpoint.*
