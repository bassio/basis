# The Braces Syntax

Dynamic values in Basis templates are expressed using braces interpolation: `{expression}`. At first glance this looks like Python's `str.format()` syntax, but behind it is an AST-based evaluation engine that tracks dependencies and updates only the affected DOM nodes when state changes.

---

## What you can write inside braces

Expressions are evaluated against the component instance's namespace. The following are all valid:

**Component state attributes:**
```html
<p>Greetings, {name}!</p>
```

**Computed properties:**
```html
<p>Total: {cart_total}</p>
```

**Simple Python expressions:**
```html
<p>Double: {count * 2}</p>
```

**Allowed built-ins:**
A curated set of Python built-ins is available inside braces:

- **Constants / literals**: `False`, `True`, `None`
- **Conversions**: `int`, `float`, `str`, `list`, `tuple`, `set`, `repr`, `format`
- **Numeric helpers**: `min`, `max`, `sum`, `pow`, `round`, `divmod`, `hex`, `oct`, `ord`
- **Collection utilities**: `len`, `enumerate`, `filter`, `iter`, `map`, `range`, `reversed`, `slice`, `sorted`, `zip`

```html
<p>Items in cart: {len(cart_items)}</p>
<p>Total price: {round(sum(prices), 2)}</p>
```

> [!NOTE]
> The list above is the exact set defined in `ALLOWED_BUILTINS` in `basis/shared/expr.py`. Notably, `bool`, `dict`, and `abs` are **not** included — use their equivalents (`bool(x)` can usually be written as a plain truthiness check; `abs` as `max(x, -x)`), or expose them as computed properties / component attributes.

### Restrictions at parse time

The AST sandbox rejects two categories of expression up front:

- **Imports** — no `import` statements or `__import__` calls are available inside braces.
- **Attribute writes** — expressions are evaluated read-only (`ast.Load` only); you cannot assign inside a binding.

Function and method **calls are not blocked outright**: an expression may call any allowed built-in, or a method accessible on the component instance (e.g. `{name.upper()}`). Because bindings should stay free of side effects, complex logic belongs in event handlers or `@computed` properties — but the sandbox does not enforce that at parse time.

---

## Special prefixes

Two prefix characters extend the braces syntax for cross-component communication.

### `$` — Global store reference

Prefixing with `$store_name` binds to a value from a registered `Store`. The binding updates whenever that store attribute changes, regardless of which component or action triggered the update.

```html
<p>Welcome back, {$user_session.username}!</p>
```

The store name (`user_session`) must match the string passed to the `Store` constructor.

### `#` — Component ID reference

Prefixing with `#component_id` subscribes to a value from another mounted component instance, identified by its HTML `id` attribute.

```html
<!-- Updates whenever the slider with id="my-slider" changes its 'value' -->
<p>Selected temperature: {#my-slider.value}°C</p>
```

> [!NOTE]
> The `#id` subscription is fulfilled when the target component is mounted and registered. If the target hasn't mounted yet, Basis queues the subscription and resolves it once the component appears.

---

## How evaluation works

Basis does not use `eval()`. Template expressions are processed through a sandboxed AST pipeline:

1. **Parse** — During blueprint initialization, the braces content is parsed into an AST.
2. **Dependency extraction** — `extract_dependencies()` walks the AST to find every variable name the expression reads (e.g. `count`, `$user_session.username`). These become the binding's declared dependencies.
3. **Restriction** — Any AST node representing an unsafe operation (imports, file I/O, arbitrary function calls, attribute writes) causes the parser to reject the expression.
4. **Evaluation** — When a dependency changes, `safe_eval()` re-evaluates only that expression in a sandboxed context and updates the target DOM node.

This means dependency tracking is static and explicit — Basis knows exactly which state variables each expression reads before any state changes.
