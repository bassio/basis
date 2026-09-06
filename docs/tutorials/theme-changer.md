# Tutorial: The Theme Changer

A mini-app that flips the entire site between light and dark — not by
swapping CSS files, but by changing one value on a **global store**. Try it
live on the site's Showcase page (under **Mini-Apps → Theme Changer**).

By the end you'll understand stores, the `$store` DSL, and how design tokens
make theming a data problem instead of a CSS problem.

---

## The whole app

```python
from basis.shared.component import Component


class ThemeChanger(Component):
    def set_dark(self, event):
        self.S.get("theme").dark_mode = True

    def set_light(self, event):
        self.S.get("theme").dark_mode = False

    def template(self):
        """
        <button onclick="{set_dark}">Dark</button>
        <button onclick="{set_light}">Light</button>
        """
```

That's it — two buttons, one store, and the whole site re-themes.

---

## 1. `$theme` is a global store

A **store** is state that lives *outside* any one component — shared, global,
and reactive. Basis ships a `ThemeStore` registered as `$theme` (the `$` is the
DSL for "the store named...").

Components reach it two ways:

- in a template, with the `$` DSL: `{$theme.dark_mode}`,
- in Python, with the `S` shorthand: `self.S.get("theme")`.

The Theme Changer uses the second form to write:

```python
self.S.get("theme").dark_mode = True
```

Because stores are reactive (they participate in the same DAG), assigning
`dark_mode` notifies every component that reads `$theme.*` — including the
`<ui-theme-provider>`.

> [!TIP]
> Your app's own stores work the same way. Define one in a `stores/` module
> (module-scope instances are auto-discovered) and any component can read and
> write it with `$store.attr`. See [State Stores & Store Providers](../05_reactivity/stores.md).

## 2. `<ui-theme-provider>` turns state into CSS

The `<ui-theme-provider>` component subscribes to `$theme` and emits CSS custom
properties on `:root` — `--bg-primary`, `--text-primary`, `--accent-color`,
and the rest of the token set:

```css
:root {
    color-scheme: dark;
    --bg-primary: light-dark(#F9F9F6, #1C1C1A);
    --text-primary: light-dark(#232822, #EAEAE4);
    ...
}
```

Every component styles itself with these variables, so when the provider
re-emits them, **everything re-themes at once** — no per-component work.

## 3. Design tokens, not CSS files

The tokens use CSS `light-dark()` with `color-scheme`, which is what makes
dark mode a single store flip: each token carries both a light and a dark
value, and the scheme decides which side wins. Theming becomes a **data**
problem (which theme is active, what are its tokens) rather than a pile of
override stylesheets.

Read more about tokens, custom themes, and per-app overrides in
[Styling Components](../04_components/styling-components.md) and the theme
plugin's schema.

---

## What you learned

- **Stores** are global, reactive state — `$theme` in templates, `self.S` in
  Python.
- Writing a store field notifies every subscriber through the DAG.
- `<ui-theme-provider>` + **design tokens** make theming a data problem.

## Where to go next

- Stores in depth: [State Stores & Store Providers](../05_reactivity/stores.md)
- Tokens and custom themes: [Styling Components](../04_components/styling-components.md)
- Back to the hub: [Mini-Tutorials](index.md)
