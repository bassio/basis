# Why Basis?

What started as simple HTML pages has become a sprawling ecosystem of build tools, transpilers, bundlers, state managers, and hydration frameworks. For Python developers specifically, this is particularly frustrating: the moment you want a single input box to update a header without a full page reload, you're suddenly managing a second codebase in a different language.

Basis was built to fix that.

---

## The frontend problem for Python developers

Most Python web frameworks excel at the backend: routing, database queries, business logic, auth. Where they fall short is reactivity. Once a page loads, it's static. Any interactivity after that requires you to either bolt on vanilla JavaScript or maintain a separate frontend project.

That usually means:

1. **Build overhead** — Even modest React or Vue apps need Vite or Webpack, a `package.json`, and a compilation step that runs constantly in the background. Configuring this pipeline and keeping it working is a non-trivial maintenance burden.

2. **Two separate state models** — Your Python server has one representation of your data; your JavaScript client has another. Every update requires serializing through an API, handling the response, and manually syncing both sides.

3. **Non-standard syntax** — JSX, `.tsx`, decorators, custom directives. These only work inside the framework's own compiler. They're not real HTML or real JavaScript; they're a DSL that ties you to the toolchain.

> [!NOTE]
> The *JavaScript fatigue* phenomenon — where developers spend more time fighting build configuration than writing product code — is well-documented and still very real in 2025.

---

## Where this came from

Basis came out of a concrete frustration: Python has some of the most productive backend tooling in the world — FastAPI, SQLModel, Pydantic, asyncio. Building a clean API is fast and pleasant. But the moment the frontend is involved, you need a completely separate mental model and toolchain.

The specific pain is simple: **why does updating a `<h1>` based on an input require all of this?**

Basis answers that by running the same Python component code on the server for the initial render, and then in the browser via PyScript for all subsequent updates — no JavaScript, no compilation, no API layer for UI state.

---

## What Basis is not

Basis is not trying to replace the JavaScript ecosystem or compete with React for complex SPAs with massive teams. It's designed for Python developers building data dashboards, internal tools, SaaS platforms, and admin panels — applications where the backend is already Python and the frontend complexity should be proportional to what's actually needed.
