"""
basis/server/responses.py
-------------------------
FastAPI response types for serving Basis pages.

``PageResponse`` is an ``HTMLResponse`` subclass built from a ``Page`` recipe via
:func:`basis.server.render.render_page` (which resolves ``render_mode`` and picks
the SSR or CSR pipeline). It backs ``@app.serve``, ``app.include_page`` and
``@app.page``, and is available for hand-rolled FastAPI endpoints:

    from basis.server.responses import PageResponse

    @app.get("/")
    async def home(request: Request):
        return await PageResponse.from_page(HomePage, request)
"""

from __future__ import annotations

from fastapi.responses import HTMLResponse


class PageResponse(HTMLResponse):
    """An ``HTMLResponse`` built from a :class:`~basis.shared.page.Page` recipe.

    Use the async factory ``from_page`` — SSR rendering is async (it runs
    ``server_load``); the constructor stays ``HTMLResponse``-compatible for
    callers that pre-render the HTML themselves.
    """

    @classmethod
    async def from_page(
        cls,
        page_cls,
        request=None,
        *,
        render_mode: str | None = None,
        global_stores: list | None = None,
        status_code: int = 200,
        headers=None,
    ):
        """Render ``page_cls`` via :func:`basis.server.render.render_page` and
        return a :class:`PageResponse`.

        ``render_mode`` selects the serving mode (see ``render_page``): ``"ssr"``
        (default) renders the page and its root component server-side; ``"csr"``
        sends the client-rendered shell plus the serialized initial state and
        lets the unified client entrypoint mount the page.
        """
        from basis.server.render import render_page

        from basis.shared.context import base_url_var

        token = None
        if request is not None:
            token = base_url_var.set(str(request.base_url))
        try:
            html = await render_page(
                request, page_cls, render_mode=render_mode, global_stores=global_stores
            )
        finally:
            if token is not None:
                base_url_var.reset(token)

        return cls(html, status_code=status_code, headers=headers)
