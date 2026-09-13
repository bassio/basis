# Client browser harness (ROADMAP-MOBILE.md M5.3a)

Opt-in Playwright tests that drive the **real** client — Pyodide/PyScript in a
browser — the half of the product the server-side suite structurally cannot
cover. They assert the SSR tree hydrates cleanly and then updates the DOM on
interaction.

## Run

```bash
uv pip install playwright       # once
playwright install chromium     # once (downloads the browser)

pytest tests/browser --browser  # opt-in — skipped by default, like --bench
```

CI runs this via `.github/workflows/ci.yml` (a dedicated `browser` job).

## What's here

- `browser_app/` — a tiny but *real* Basis app (an SSR Page whose root is one
  reactive component). It is served by the fixture over the framework's offline
  vendored Pyodide, so a run is deterministic and needs no network.
- `conftest.py` — the `--browser` gate, the app-server fixture (uvicorn
  subprocess on a free port), and the Playwright fixtures.
- `test_hydration.py` — the assertions: SSR markup present → clean hydration
  report (`unhydrated_components == []`, `unmatched_bindings == []`, no
  fallback) → a click re-renders the DOM live.

## Why opt-in

A browser + Pyodide boot is slow and environment-dependent, so gating it keeps
`pytest` fast and deterministic while still making the browser path a
CI-enforced part of the suite.

## Mobile emulation (M5.3b)

`test_mobile.py` drives the same app through Playwright **device descriptors**
(`conftest.MOBILE_DEVICES`: `iphone` → *iPhone 13*, `android` → *Pixel 5* — both
set viewport, deviceScaleFactor and `has_touch`) and asserts:

- clean hydration + a **touch** update (`page.tap`) at each device viewport, with
  no horizontal overflow;
- **reduced-motion** is emulated (`reduced_motion="reduce"`) and hydration stays
  clean;
- the **offline toggle** (`context.set_offline(True)`) flips `navigator.onLine`
  while client-side reactivity keeps working with no network.

Both profiles run on the Chromium engine (the descriptor supplies the viewport /
UA / touch / DPR) — a true WebKit lane is M5.3c. The whole browser suite is
~2 min locally, since each test boots Pyodide once.

## Responsive shell (M1.4)

`test_shell.py` serves a second fixture route (`/shell`) whose root is the
scaffolded app frame (`browser_app/components/shell_frame.py`) and asserts the
compact arrangement at the `iphone` descriptor — the bottom navigation sits
below the surface, the sidebar is off-canvas until the title-bar trigger opens
it (tap the backdrop to close), splitters and the status bar are gone, there is
no horizontal overflow — plus that the frame is unchanged at 1280×720 and that
the drawer is closed on first paint. Every case also requires a clean hydration
report.

## Next (M5.3c)

A real-device smoke list and published boot-budget numbers (M3.4), plus a WebKit
lane.
