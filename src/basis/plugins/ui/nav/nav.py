"""The ``Nav`` — one navigation declaration, several arrangements.

Navigation is the thing a phone punishes hardest: the same list of destinations is an
inline row on a desktop, a strip pinned to the bottom edge on a phone, an icon rail in a
workbench, and a stacked list inside a drawer. Declaring that four times is how the four
declarations drift apart, so ``ui-nav`` declares it **once** and lets CSS rearrange it.

``items`` is data — ``[{"id", "label", "icon", "href", "badge"}]`` — which is what lets
one element render in four shapes without four templates. The links are plain ``<a
href>``: the nav is crawlable and works with no client at all. The active item is
*derived* from ``$router.current_path`` (page-set during SSR, updated on ``popstate``)
rather than declared, so it stays correct after a client-side navigation too.

``arrangement`` picks the shape; ``auto`` is an inline row that docks to the bottom edge
at the compact breakpoint. A docked bar floats over the content it covers, so it
publishes the space it takes (``--shell-bottom-inset``) for the frame to reserve.
"""
from basis.shared.styling import compact_block
from basis.shared.component import Component, extra_style, scoped
from basis.shared.reactive import computed

_BASE_CSS = """
:scope {
    display: contents;
}

.ui-nav {
    display: flex;
    align-items: center;
    gap: var(--nav-gap, 0.25rem);
    min-width: 0;
}

.ui-nav-item {
    display: inline-flex;
    align-items: center;
    gap: 0.4em;
    min-height: var(--control-height, 2rem);
    padding: 0 0.7rem;
    border-radius: var(--radius-sm, 0.375rem);
    color: var(--text-secondary, #a9afc0);
    font-size: 0.8rem;
    font-weight: 500;
    text-decoration: none;
    white-space: nowrap;
}

@media (hover: hover) {
    .ui-nav-item:hover {
        color: var(--text-primary, #e0e0e0);
        background: var(--hover-bg, rgba(255, 255, 255, 0.06));
    }
}

.ui-nav-item:active {
    background: var(--hover-bg, rgba(255, 255, 255, 0.1));
}

.ui-nav-item:focus-visible {
    outline: 2px solid var(--accent-color, #007acc);
    outline-offset: 2px;
}

.ui-nav-item-active,
.ui-nav-item-active:active {
    color: var(--text-primary, #e0e0e0);
    background: var(--hover-bg, rgba(255, 255, 255, 0.08));
}

.ui-nav-icon {
    line-height: 1;
}

.ui-nav-badge {
    padding: 0 0.35em;
    border-radius: 999px;
    background: var(--accent-color, #007acc);
    color: #ffffff;
    font-size: 0.7em;
    line-height: 1.6;
}

/* An icon rail names nothing: the glyph plus its title carries the meaning. */
.ui-nav[data-arrangement="rail"] {
    flex-direction: column;
    gap: var(--nav-gap, 0.25rem);
}

.ui-nav[data-arrangement="rail"] .ui-nav-item {
    width: 100%;
    justify-content: center;
    padding: 0;
}

.ui-nav[data-arrangement="rail"] .ui-nav-label {
    display: none;
}

/* A drawer list is a column of full-width rows, so the row height is the page's. */
.ui-nav[data-arrangement="drawer"] {
    flex-direction: column;
    align-items: stretch;
    gap: 0;
}

.ui-nav[data-arrangement="drawer"] .ui-nav-item {
    width: 100%;
    min-height: var(--row-height, 2rem);
    border-radius: 0;
    padding: 0 0.9rem;
}
"""

#: The space a docked strip occupies: the control height (which *is* the touch target at
#: compact) plus the home-indicator inset.
_STRIP_HEIGHT = "calc(var(--control-height, 2rem) + var(--safe-area-bottom, 0px))"


def _docked(selector: str) -> str:
    """The docked strip for *selector*: out of whatever flow it sits in, pinned to the
    bottom edge, and padded clear of the home indicator. The strip is one arrangement of
    the same list, so both callers share this body.
    """
    return f"""\
{selector} {{
    position: fixed;
    inset: auto 0 0 0;
    z-index: 30;
    justify-content: space-around;
    background: var(--bg-secondary, #26263a);
    border-top: 1px solid var(--border-color, #3a3a52);
    padding-bottom: var(--safe-area-bottom, env(safe-area-inset-bottom, 0px));
}}

{selector} .ui-nav-item {{
    /* Share the strip, but never squeeze below a tap target: a long list scrolls
       rather than becoming unreadable. */
    flex: 1 1 auto;
    min-width: 3.5rem;
    flex-direction: column;
    justify-content: center;
    gap: 0.1em;
    padding: 0 0.4rem;
}}
"""


#: A docked bar covers the content it floats over, and a custom property only inherits
#: *downwards* — so the nav publishes the space it takes at the page root, where the
#: frame can reserve it. Conditional, because a page without a docked nav reserves
#: nothing.
_INSET_BASE_CSS = (
    'html:has(.ui-nav[data-arrangement="bottom"]) {\n'
    f"    --shell-bottom-inset: {_STRIP_HEIGHT};\n"
    "}\n"
)

_INSET_COMPACT_CSS = (
    'html:has(.ui-nav[data-arrangement="auto"]) {\n'
    f"    --shell-bottom-inset: {_STRIP_HEIGHT};\n"
    "}\n"
)


class Nav(Component):
    """A navigation list that rearranges itself instead of being re-declared.

    ``items`` — ``[{"id", "label", "icon", "href", "badge"}]``; ``id`` defaults to
    ``href``. ``arrangement`` — ``auto`` (inline, docked at compact) | ``inline`` |
    ``bottom`` | ``rail`` | ``drawer``. ``active`` pins the highlighted item by id;
    leave it empty to derive the highlight from ``$router.current_path``.
    """

    __tag__ = "ui-nav"

    items = []
    arrangement = "auto"   # auto | inline | bottom | rail | drawer
    active = ""            # an item id; empty derives from the router

    @computed(dependencies=["items", "active", "$router.current_path"])
    def nav_items(self):
        router = self.S.get("router")
        path = getattr(router, "current_path", "") or ""
        pinned = self.active or ""

        resolved = []
        for index, raw in enumerate(self.items or []):
            item = raw if isinstance(raw, dict) else {"label": str(raw)}
            href = item.get("href", "") or ""
            item_id = item.get("id") or href or f"item-{index}"
            is_active = item_id == pinned if pinned else _matches(path, href)
            resolved.append(
                {
                    "id": item_id,
                    "label": item.get("label", ""),
                    "icon": item.get("icon", ""),
                    "href": href or "#",
                    "badge": item.get("badge", ""),
                    "active_class": "ui-nav-item-active" if is_active else "",
                    "aria_current": "page" if is_active else "false",
                }
            )
        return resolved

    @classmethod
    @scoped
    def style(cls):
        return (
            _BASE_CSS
            # `bottom` asks for the strip at every viewport; `auto` only where the header
            # has no room to keep a row.
            + _docked('.ui-nav[data-arrangement="bottom"]')
            + compact_block(_docked('.ui-nav[data-arrangement="auto"]'))
        )

    # The page root is the one element a scoped stylesheet cannot reach, and this block
    # styles nothing but that root: the nav publishes the space a docked strip takes where
    # the frame can inherit it. Additive, and deliberately unscoped.
    @classmethod
    @extra_style
    def root_inset(cls):
        return _INSET_BASE_CSS + compact_block(_INSET_COMPACT_CSS)

    def template(self):
        """
        <nav class="ui-nav" data-arrangement="{arrangement}">
            <a class="ui-nav-item {item['active_class']}"
               for="item" in="{nav_items}" key="id"
               href="{item['href']}"
               aria-current="{item['aria_current']}">
                <span class="ui-nav-icon" if="{item['icon']}">{item['icon']}</span>
                <span class="ui-nav-label">{item['label']}</span>
                <span class="ui-nav-badge" if="{item['badge']}">{item['badge']}</span>
            </a>
        </nav>
        """


def _matches(path: str, href: str) -> bool:
    """Whether *path* is *href* or lives inside it.

    ``/`` is a prefix of everything, so it only ever matches itself — otherwise the
    home item would stay highlighted on every page.
    """
    if not href:
        return False
    if href == "/":
        return path == "/"
    return path == href or path.startswith(href.rstrip("/") + "/")
