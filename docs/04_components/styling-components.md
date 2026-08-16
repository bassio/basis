# Styling Components

This is the **look-and-feel** guide. Basis components are real web components that render in **light DOM** by default, which means you style them with the same CSS you already know — no build step, no CSS-in-JS, no shadow-DOM restrictions. Every built-in `basis.ui` component is designed to be re-skinned, and most customization is a few lines of CSS.

> [!TIP]
> Here you'll find the *styling* techniques: [design tokens](#1-design-tokens-theming-with-css-variables), [plain CSS overrides](#2-override-with-plain-css), [host styling](#3-style-the-host-element-inline), and [encapsulation](#4-encapsulation-with-scoped). To change a component's *structure or behavior* instead — new props, new template, new logic — see [Extending & Customizing Components](extending-components.md).

---

## The styling model: why CSS just works

When a component is mounted — on the server for SSR *and* in the browser for hydration — its styles are injected as a plain `<style data-component-class="Button">` element into the page, right next to your own styles. There is no shadow root wrapping the component (unless you opt in, see [Shadow DOM](#5-shadow-dom-advanced)).

That one design decision drives everything in this guide:

- **The CSS cascade works normally.** Your stylesheet can override any component rule with standard specificity and source order — exactly as if the component markup were written by hand.
- **CSS variables inherit.** Components read design tokens with fallbacks, so you can re-theme entire trees by overriding a handful of `--custom-properties`.
- **The output is inspectable.** Component markup and styles are ordinary, debuggable HTML and CSS.

The mental picture: *styling a Basis component is styling an HTML subtree.* You write CSS, and it works.

> [!NOTE]
> **Host vs. inner content.** Every component is a custom element — its **host** is the tag itself (`<ui-button>`), and its visible box is often an **inner** element (the `<button class="ui-btn">` inside it). The techniques below call this out where it matters, because it's the one thing that surprises people coming from plain HTML.

---

## 1. Design tokens: theming with CSS variables

The `basis.ui` suite is built on **CSS custom properties (design tokens)** with sensible fallbacks:

```css
/* basis/ui/button/button.py */
.ui-btn-primary {
    background-color: var(--accent-color, #007acc);
    border-radius: var(--radius-md, 0.5rem);
}
/* basis/ui/card/card.py */
ui-card {
    background: var(--bg-secondary, #1e2431);
    border: 1px solid var(--border-color, #2d3245);
    box-shadow: var(--shadow-sm, 0 1px 3px rgba(0,0,0,0.1));
}
```

Because the components use variables rather than hard-coded values, overriding a token re-skins **every** component that reads it — no code changes.

### Global theming

Override tokens on `:root` to re-skin the whole app:

```css
:root {
    --accent-color: #e63946;    /* primary buttons, active states, links… */
    --radius-md: 0.75rem;       /* every corner that uses the token */
    --font-sans: "Inter", sans-serif;
}
```

### Per-subtree theming

Override on a container, and every component inside it inherits:

```css
.admin-dashboard {
    --accent-color: #457b9d;
    --bg-secondary: #f1f5f9;
}
```

### Per-instance theming

Set a variable inline on the tag — the standard Custom Element idiom:

```html
<ui-button label="Deploy" style="--accent-color: #2a9d8f;"></ui-button>
<ui-card style="--bg-secondary: #fff;"></ui-card>
```

> [!NOTE]
> Inline custom properties cascade through the light DOM into the component's subtree, which is why `style="--token: value"` reliably re-themes a component even when its visible box is an inner element.

### Reactive theming with `ThemeStore`

For **runtime** theming — light/dark mode, a user-selected accent color — use the reactive [`ThemeStore`](ui-components.md#themestore-basisuitheme). It holds the same tokens as reactive state, and a `<ui-theme-provider>` injects them as CSS variables:

```python
from basis.ui.theme import ThemeStore, ThemeProvider

theme = ThemeStore()            # registered as "theme" → reachable as $theme
theme.dark_mode = True          # flips every light-dark() token
theme.accent_color = "light-dark(#6E5FD8, #9384F5)"

# Include <ui-theme-provider> once in your app template to apply tokens.
```

Changing a token at runtime re-renders just the DOM that depends on it — the same reactivity engine as component state.

> [!TIP]
> The full token set — `bg_*`, `text_*`, `accent_*`, `border_*`, `radius_*`, `shadow_*`, `font_*` — is documented in the [Built-in UI Suite](ui-components.md#themestore-basisuitheme).

---

## 2. Override with plain CSS

Since component styles live in the page's light DOM, **the cascade is on your side**. Write your own stylesheet and override any component rule:

```css
/* your own app.css */
.ui-btn {                       /* the inner button element */
    text-transform: uppercase;
}
ui-button {                     /* the host element */
    gap: 6px;
}
.ui-btn-primary {
    box-shadow: none;           /* drop the glow on primary buttons */
}
```

Because a component's `<style>` is injected early and your stylesheet comes later in the document, **equal-specificity** rules in your CSS win by source order.

### Where to put your CSS

- A `<style>` block inside a component template (rendered with that component).
- A `.css` companion file for a multi-file component (see [Defining Components](defining-components.md)).
- The page shell — subclass `Page` and add a `<link rel="stylesheet">` or `<style>` to the `<head>` (see [The Page Component](page-component.md)).
- Any plain `.css` file you serve alongside your app.

### Specificity & order: why an override might not "stick"

The usual cascade rules apply, so if a rule isn't winning:

1. **Specificity** — a more specific component rule (e.g. `.ui-btn-primary:hover`) beats a plain `.ui-btn` override. Match or exceed the specificity, or target the same class.
2. **Source order** — equal-specificity rules resolve by document order; make sure your stylesheet loads after the component's `<style>`.
3. **`!important`** — the escape hatch when a component rule is locked behind many selectors. Use sparingly; prefer overriding a token instead.

> [!TIP]
> When in doubt, restyle via a [design token](#1-design-tokens-theming-with-css-variables) rather than fighting a specific selector — tokens are the components' intended customization surface.

---

## 3. Style the host element (inline)

The standard HTML `style` attribute works on a component tag, styling the **host** — the tag itself:

```html
<ui-card style="width: 320px; margin: 0 auto;"></ui-card>
```

This is the idiomatic way to size, position, or space a component from the outside, exactly as you would a `<div>` or any built-in element.

Two things worth knowing:

1. **Host vs. inner content.** If the component's visible box *is* the host (e.g. `ui-card` styles `ui-card { background: var(--bg-secondary) }`), inline styles apply directly. If the visible box is an inner element (e.g. the `<button>` inside `ui-button`), an inline `background-color` colors the wrapper, **not** the inner button. For inner content, use [plain CSS overrides](#2-override-with-plain-css) or a [CSS variable](#1-design-tokens-theming-with-css-variables) — which is why the reliable inline idiom is `style="--token: value"` rather than `style="background-color: ..."`.
2. **Inline variables inherit.** Because `--custom-properties` cascade, `style="--accent-color: red"` reliably re-themes a component instance even when the visible box is nested.

---

## 4. Encapsulation with `@scoped`

By default a component's styles participate in the global cascade. If you'd rather a component's styles **not** leak outside its own subtree, mark its `style()` method with the `@scoped` decorator:

```python
from basis.shared.component import Component, scoped

class Sidebar(Component):
    @scoped
    def style(self):
        """
        .nav-item { padding: 8px; }
        """
```

Basis wraps the rules in a CSS `@scope` block, limiting them to the component's subtree:

```css
@scope (sidebar) {
    .nav-item { padding: 8px; }
}
```

> [!NOTE]
> `@scope` is a newer CSS feature, so check browser support if you target older browsers. For maximum compatibility you can scope manually with a descendant selector instead. And even with `@scoped`, rules that reference design tokens (`var(--accent-color, …)`) still inherit from the page, so global theming keeps working.

Use `@scoped` when you author a component that should be self-contained; leave it off (the default) when you *want* consumers to be able to override it with plain CSS.

---

## 5. Shadow DOM (advanced)

Basis components render in **light DOM by default** — that's what makes all of the above work. For true style isolation you can opt into the native Shadow DOM by setting `__shadow__ = True` on the component class:

```python
class IsolatedCard(Component):
    __tag__ = "isolated-card"
    __shadow__ = True   # render template into a shadow root
```

Before reaching for this, know the trade-off:

- **Shadow roots break the cascade.** The theming techniques in this guide — `:root` overrides, per-subtree tokens, and your stylesheet — do **not** cross into a shadow root. A shadow-DOM component must carry its own `<style>` inside its template and re-import any tokens it needs.
- It's an **advanced escape hatch**, not the recommended default. The light-DOM model is what makes Basis components trivially skinnable by consumers.

If you need isolation but still want theming to work, prefer `@scoped` (section [4](#4-encapsulation-with-scoped)) — it limits selector reach without breaking the variable cascade.

---

## FAQ

**Why doesn't `style="background-color: red"` change my button's look?**

Because `style` targets the host `<ui-button>`, while the visible button is the inner `.ui-btn`. Set a token instead — `style="--accent-color: red"` — or override `.ui-btn` in your own stylesheet. See [Style the host](#3-style-the-host-element-inline).

**Can I add a global stylesheet to my app?**

Yes. Subclass `Page` and add a `<link>` or `<style>` to the `<head>` (see [The Page Component](page-component.md)), or put your CSS in a `.css` companion file / `<style>` block inside a component template.

**Do the `basis.ui` components have hard-coded colors?**

No — they read design tokens with fallbacks (`var(--accent-color, #007acc)`), so every color, radius, shadow, and font is overridable. See [Design tokens](#1-design-tokens-theming-with-css-variables).

**How do I make a component fully self-contained?**

Use the `@scoped` decorator for selector-level isolation, or `__shadow__ = True` for full Shadow DOM isolation (accepting that global theming no longer applies). See [Encapsulation](#4-encapsulation-with-scoped) and [Shadow DOM](#5-shadow-dom-advanced).

---

## Where to go next

- **[Extending & Customizing Components](extending-components.md)** — when CSS isn't enough: new props, new templates, and Python subclassing.
- **[Built-in UI Suite](ui-components.md)** — the component catalogue and the full `ThemeStore` token reference.
- **[Defining Components](defining-components.md)** — authoring your own components (single-file & multi-file, reactive state).
- **[The Page Component](page-component.md)** — customizing the HTML shell and adding global stylesheets.
