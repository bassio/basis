# Static Pages — a Document the Client Does Not Boot

Most Basis pages are shells for an application: the server renders them, the client adopts
the served tree and every binding stays live. **`StaticPage`** is the same page without
that second half. The server renders the whole document — chrome, stores, the component
tree — and serves it as written: no PyScript, no serialized state, no hydration stamps, no
binding that updates after load.

*Static* means **no client**. It does not mean "no data".

---

## What a static page is

`StaticPage` is the base class; `Page` adds the client:

```python
from basis.shared.page import Page, StaticPage
```

| | `StaticPage` | `Page` |
| :--- | :--- | :--- |
| Chrome — doctype, title, viewport policy, `$head` loops, iOS metas, component styles, user stylesheets | yes | yes |
| Component tree rendered server-side | yes | yes |
| Stores collected, `apply_request` hooks run, `server_load` runs | yes | yes |
| PyScript / the client entrypoint | — | yes |
| `#basis-initial-state`, hydration ids, `render_mode` | — | yes |

Everything a template binds (`{title}`, `{$store.field}`, `{item['css']}`, `{method()}`)
is evaluated **once, on the server**, while the page renders. A static page is therefore a
document an author could have written by hand — except that the framework assembles it,
so it keeps the app's theme, its `$head` links and its store-derived values.

---

## What a static page gives up

The client half of the mental model does not apply, and it fails quietly rather than
loudly:

- **Bindings render once.** A store field read in the template is a value, not a
  subscription: changing it later changes nothing.
- **Actions never run.** An `onclick` / event attribute is inert markup — the browser has
  nothing to call into.
- **Client-only stores stay neutral.** `$device`, `$network` and `$pwa`'s measurements
  keep the values the server serialized would have had; nothing probes the browser.
- **No HMR, no service worker registration, no client-side routing.**

If the page needs any of those, it is a `Page`.

---

## Serving one

`app.include_page` and `@app.serve` accept both kinds:

```python
from basis.shared.component import Basis, Component
from basis.shared.page import StaticPage

app = Basis()

class TermsBody(Component):
    def template(self):
        """
        <main class="terms">
            <h1>Terms of Service</h1>
            <p>Rendered once, on the server.</p>
        </main>
        """

@app.serve("/terms")
class TermsPage(StaticPage):
    title = "Terms"
    root_component = TermsBody
```

Two things are refused rather than ignored, because both would be a promise the page
cannot keep:

- **`render_mode`.** `"ssr"` and `"csr"` choose how a *client* boots. Passing either to a
  static page raises; drop the argument (or subclass `Page`).
- **`@app.page`.** That decorator is the client-boot sugar: it annotates a root component
  with the recipe the client driver replays. A static page has no driver, so the
  decoration raises and points at `app.include_page(path, page_cls=...)`.

`root_component` may be `None` for a page that is pure chrome, and `stores` works exactly
as it does for a `Page` — a name list, or empty for every auto-discovered store. A static
page is a good place to declare a **strict subset**: only the stores it actually reads are
instantiated, and the page hands no state to a browser.

### Head content

A static page's `<head>` is chrome, so the `$head` channels work as they do anywhere else —
see [Head meta, links, styles and scripts](../04_components/page-component.md#head-meta-links-styles-and-scripts).
`$head.metas` / `links` / `styles` / `scripts` are the four head channels, and a plugin's
`apply_request` hook contributes to them per request. Markup that is the same for every
request belongs in the component's template instead, where it costs no state.

---

## When to prefer one

Reach for a `StaticPage` when the document has to hold up **without** a runtime:

- an **offline fallback** — the page a navigation lands on when neither the network nor a
  cached copy exists (the mobile plugin's `/offline` is a static page for exactly this
  reason: it stands in for a boot, so it cannot depend on one);
- **terms / privacy / 404 / error** pages, where a document is the whole feature;
- content that is generated per request but never interactive.

For everything else — every page with a binding the user can move — use `Page`, and let
the client adopt the served tree.
