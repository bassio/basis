# Extending & Customizing Components

If you've used React, Svelte, or Vue components, you already know most of Basis. A Basis component is a Python class that compiles to a **web component** — a real HTML custom element you can drop into markup, style with CSS, and configure with attributes. The difference is that everything (markup, logic, state, styles) is written once in Python and runs on both the server and the browser.

This guide explains the mental model and walks through the **code-side** ways to extend a component — attributes (props), Python subclassing, and building your own. For the **look-and-feel** side (theming, plain CSS overrides, host styling), see the companion guide [Styling Components](styling-components.md).

---

## The mental model: a Basis component is a web component

Basis deliberately builds on the web platform's native component model — **Custom Elements** — rather than inventing a parallel one. That means the component abstractions you already know map directly:

| If you know this… | …it works like this in Basis |
| :--- | :--- |
| React function / Svelte component | `class Counter(Component)` |
| JSX / `.svelte` template | A template — the class docstring, a `template()` method docstring, or a `.html` companion file |
| Props / attributes | Class attributes + HTML attributes on the tag (`<ui-button variant="danger">`) |
| State (`useState`, `let`) | Reactive class attributes; assign with plain Python: `self.count += 1` |
| Derived state (`useMemo`, `$:`) | `@computed` properties |
| CSS (CSS-in-JS, `<style>`) | A `style` attribute or `style()` method — plain, standard CSS |
| Using a component in markup | Its hyphenated tag: `<my-counter></my-counter>` |
| Children / slots | Standard `<slot>` projection |
| Event handlers | `onclick="{method}"` attributes, plus `@py_event` for rich event data |

So writing a Basis component looks like this:

```python
from basis.shared.component import Component, scoped

class Counter(Component):
    """
    <div class="counter-card">
        <strong>{count}</strong>
        <button onclick="{increment}">+1</button>
    </div>
    """
    count = 0

    @scoped
    def style(self):
        """
        .counter-card { display: flex; gap: 12px; align-items: center; }
        """
    def increment(self):
        self.count += 1
```

`Counter` automatically becomes the custom element `<counter>` (add a hyphen via `__tag__` when you want it in markup — see below). The template is standard HTML, the style is standard CSS, and the state is plain Python.

> [!TIP]
> **Why light DOM?** Basis renders component styles as ordinary `<style>` elements in the page (no shadow-DOM encapsulation by default). That's a deliberate design choice — it means the CSS cascade works the *normal* way, and overriding any component's look is just CSS. The full styling story lives in [Styling Components](styling-components.md).

---

## The customization ladder

There is no single "right" way to customize a component — you pick the technique that matches how much you want to change. The CSS-based techniques (rows 2–4) are covered in depth in [Styling Components](styling-components.md); this page focuses on the code-side rows.

| # | Technique | What it's for | Effort |
| :-: | :--- | :--- | :--- |
| 1 | [Configure with attributes](#1-configure-with-attributes-props) | Use a component's built-in options (`variant`, `size`, …) | None — just markup |
| 2 | [Theme with CSS variables](styling-components.md#1-design-tokens-theming-with-css-variables) | Re-skin colors, radii, spacing across many components | A few lines of CSS |
| 3 | [Override with plain CSS](styling-components.md#2-override-with-plain-css) | Fine-tune any component's look from your own stylesheet | Normal CSS |
| 4 | [Style the host with the `style` attribute](styling-components.md#3-style-the-host-element-inline) | Size/position a component tag, or set CSS variables inline | Inline attribute |
| 5 | [Extend with Python subclassing](#3-extend-in-python-subclassing) | Change behavior, template, or styles; add props | A small Python class |
| 6 | [Build your own component](#4-build-your-own-component) | Full control from scratch | Full component authoring |

---

## 1. Configure with attributes (props)

Every class-level attribute on a component is a **prop** — settable from HTML. The `basis.ui` suite exposes its options this way, so the most common "customization" needs no code at all:

```html
<ui-button label="Save" variant="danger" size="lg"></ui-button>
<ui-badge label="Beta" variant="warning"></ui-badge>
<ui-toggle label="Dark Mode" checked="true"></ui-toggle>
<ui-card style="--accent-color: #e63946;">
    <p>Content</p>
</ui-card>
```

Attributes on a component tag become its reactive state: changing an attribute value (or binding it to a parent's state) updates the component's Python prop, which re-renders just the affected DOM. Pass reactive values with the same braces syntax used everywhere in Basis:

```html
<!-- inside a parent template -->
<ui-button label="{save_label}" variant="{current_variant}"></ui-button>
```

Each component's available attributes are documented in the [Built-in UI Suite](ui-components.md). If a prop you need doesn't exist yet, see [Extend in Python](#3-extend-in-python-subclassing) to add one.

---

## 2. Style & theme (CSS)

Attributes change what a component *does*; CSS changes how it *looks*. Because Basis components render in light DOM with standard cascade rules, most look-and-feel customization never touches Python at all:

- **Design tokens** — re-skin colors, radii, and fonts via CSS variables (`--accent-color`, `--radius-md`, …), globally, per subtree, or per instance.
- **Plain CSS overrides** — component styles are ordinary `<style>` elements, so your own stylesheet can override anything with the normal cascade.
- **Host styling** — size/position a component tag with the inline `style` attribute, or set design tokens inline.

All of it — including `@scoped` encapsulation and the reactive `ThemeStore` — is covered in the companion guide:

> **[→ Styling Components](styling-components.md)**

Come back here when you need to change a component's *code* rather than its CSS.

---

## 3. Extend in Python (subclassing)

When attributes and CSS aren't enough, subclass the component. Python inheritance gives you full control over template, styles, state, and behavior — and it's the same mechanism the framework uses for composition.

### 3a. Override the style

The simplest extension: keep a component's behavior and structure, change its look:

```python
from basis.shared.component import Component, scoped
from basis.ui.button import Button

class GhostButton(Button):
    __tag__ = "ghost-button"

    @scoped
    def style(self):
        """
        ghost-button .ui-btn {
            background: transparent;
            border: 1px solid var(--accent-color, #007acc);
            color: var(--accent-color, #007acc);
        }
        """
```

The subclass inherits `Button`'s template, props, and methods, and only replaces the styles. Because it declares a new `__tag__`, it becomes its own custom element, usable alongside the original:

```html
<ghost-button label="More"></ghost-button>
<ui-button label="Save" variant="primary"></ui-button>
```

> [!NOTE]
> **Tags are lowercase and hyphenated.** Custom elements must contain a hyphen. If a subclass keeps its parent's tag (by not setting `__tag__`), it *replaces* the parent in the component registry — every `<ui-button>` then resolves to your subclass. That's a useful "this app's button is now *my* button" pattern, but if you want a sibling variant, always give the subclass its own `__tag__`.

### 3b. Override the template

To change structure (not just styling), override `template()` — or the class docstring — exactly like you would when defining a component:

```python
class CompactCard(Card):
    __tag__ = "compact-card"

    def template(self):
        """
        <div class="compact-card">
            <div class="compact-title"><slot name="title">Untitled</slot></div>
            <slot></slot>
        </div>
        """
```

Props and methods inherited from `Card` keep working; the braces syntax binds them into the new template.

### 3c. Add reactive props and methods

Adding a class attribute to a subclass creates a brand-new reactive prop; adding methods creates new behavior. Both are fully usable from HTML:

```python
class BadgeWithIcon(Badge):
    __tag__ = "badge-icon"

    icon = "★"                       # new prop, settable from HTML

    def template(self):
        """
        <span class="badge-icon"><span class="b-icon">{icon}</span> {label}</span>
        """
```

```html
<badge-icon label="Featured" variant="primary" icon="🔥"></badge-icon>
```

Because props are reactive, a parent can bind them too:

```html
<badge-icon label="{product.status}" icon="{product.emoji}"></badge-icon>
```

### 3d. Quick one-off variants with `from_template`

For ad-hoc variants you don't want to name, `Component.from_template(template, **props)` builds an anonymous subclass on the fly:

```python
HeroButton = Button.from_template(
    """
    <button class="ui-btn ui-btn-hero">{label}</button>
    """,
    variant="primary",
)
```

This is handy for small tweaks inside a component's `__init__` or for loop-generated markup.

---

## 4. Build your own component

Everything above composes with full component authoring — reactive state, `@computed` properties, multi-file layouts (`.py` + `.html` + `.css`), `<slot>` content projection, and `onclick`/`@py_event` handlers. See:

- **[Styling Components](styling-components.md)** — theming and restyling any component's look with CSS.
- **[Defining Components](defining-components.md)** — single-file & multi-file layouts, reactive state, computed properties.
- **[Parent & Child Components](child-components.md)** — composition, passing attributes down the tree, and `<slot>` projection.
- **[Forms & Validation](forms-and-validation.md)** — two-way model binding in custom forms.
- **[The Built-in UI Suite](ui-components.md)** — the components you can extend or imitate.

---

## Summary — choosing an approach

| You want to… | Do this |
| :--- | :--- |
| Use a component with different options | Set attributes (`variant`, `size`, …) |
| Re-skin everything (colors, radii, fonts) | Override CSS variables on `:root` or via `ThemeStore` — see [Styling Components](styling-components.md) |
| Change one area of the app | Override CSS variables on a container — see [Styling Components](styling-components.md) |
| Tweak one component instance | Inline `style="--token: value"` or plain CSS overrides — see [Styling Components](styling-components.md) |
| Change the look of a component everywhere | Plain CSS override, or subclass + new `__tag__` |
| Change structure / add props / add logic | Subclass in Python |
| Full control from scratch | Author a new `Component` |

*See also: [Styling Components](styling-components.md) · [Defining Components](defining-components.md) · [Parent & Child Components](child-components.md) · [Built-in UI Suite](ui-components.md) · [The Page Component](page-component.md).*
