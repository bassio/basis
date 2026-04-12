"""
basis/server/ssr.py
-------------------
Server-Side Rendering helpers for Basis + FastAPI.

Usage example in a route:
    from basis.server.ssr import render_page
    from fastapi.responses import HTMLResponse

    @app.get("/")
    async def home(request: Request):
        from myapp.components.home import HomeComponent
        html = render_page(
            HomeComponent,
            title="My App",
            stores={"theme": theme_store},
            entry_module="/myapp/components/main.py",
        )
        return HTMLResponse(html)
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from basis.server.components.server_component import ServerComponent
    from basis.shared.store import Store


def _serialize_store(store) -> dict:
    """
    Extract serialisable state from a Store instance.
    Skips private/dunder attributes and non-serialisable callables.
    """
    state = {}
    for k, v in store.__dict__.items():
        if k.startswith('_'):
            continue
        if callable(v):
            continue
        try:
            json.dumps(v)     # quick serialisability check
            state[k] = v
        except (TypeError, ValueError):
            pass
    return state


def render_page(
    component_cls,
    *,
    title: str = "Basis App",
    stores: dict | None = None,
    entry_module: str = "/main.py",
    pyscript_src: str = "/pyscript",
    pyscript_json_url: str = "/pyscript.json",
    extra_head: str = "",
    **kwargs,
) -> str:
    """
    Render a full HTML page with:

    - Fully server-resolved component HTML (via ServerComponent.render())
    - PyScript offline bootstrap
    - <script id="basis-initial-state"> JSON block for Store hydration
    - <py-config> pointing at pyscript.json

    Parameters
    ----------
    component_cls:
        A ServerComponent subclass to render.
    title:
        Page <title>.
    stores:
        Dict mapping store name → Store instance whose state should be embedded
        as the initial-state JSON block.  WebSocketStore on the client reads this
        automatically on startup.
    entry_module:
        URL path of the PyScript entry point (the .py file that calls mount_app
        or the new hydrate path).
    pyscript_src:
        URL for the offline PyScript core.js bundle.
    pyscript_json_url:
        URL for pyscript.json (the file-map used by PyScript to fetch Python modules).
    extra_head:
        Any additional raw HTML to inject inside <head>.
    **kwargs:
        Keyword arguments forwarded to ``component_cls.render(**kwargs)``.
    """
    # 1. Render the component tree to an HTML fragment
    component_html = component_cls.render(**kwargs)

    # 2. Serialise store state
    initial_state: dict[str, dict] = {}
    if stores:
        for store_name, store_instance in stores.items():
            initial_state[store_name] = _serialize_store(store_instance)

    initial_state_json = json.dumps(initial_state, indent=2)

    # 3. Assemble the full page
    page = f"""
<!DOCTYPE html>
<html>
    <head>
        <meta charset="UTF-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1.0" />
        <title>{title}</title>

        <!-- PyScript offline bundle -->
        <link rel="stylesheet" href="{pyscript_src}/core.css">
        <script type="module" src="{pyscript_src}/core.js"></script>
        
        <script src="./basis/components/component.js"></script>

        <!-- Basis SSR: initial store state for client hydration -->
        <script id="basis-initial-state" type="application/json">
            {initial_state_json}
        </script>
        {extra_head}
    </head>
    <body>
        <!-- SSR root: pre-rendered by ServerComponent.render() -->
        <div id="basis-ssr-root">
            {component_html}
        </div>

        <!-- PyScript entry point: mounts/hydrates the application -->
        <script type="py" src="{entry_module}" config="{pyscript_json_url}"></script>
    </body>
</html>
"""

    return page

