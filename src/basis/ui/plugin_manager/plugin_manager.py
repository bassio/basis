"""Live plugin manager panel bound to the ``$plugins`` registry store.

Lists every registered plugin with its state, prefix, action count and
dependencies, and provides a per-plugin toggle that calls the store's server
actions (``$plugins.disable(name)`` / ``$plugins.enable(name)``) so the plugin
is actually unmounted/remounted server-side (routes, mounts, models, actions)
and the panel re-renders from the authoritative ``new_state``.

The panel reads ``$plugins.items`` directly in the template, so it is reactive
from the start: toggling a plugin re-renders its row live, and the whole list
reflects the current registry.
"""

from basis.shared.component import Component
import asyncio


class PluginManager(Component):
    """
    A live plugin manager panel bound to the app's ``$plugins`` registry store.

    The component owns no state of its own — it projects the ``plugins``
    store's ``items`` dict (``{name: {state, prefix, actions, requires}}``)
    reactively, and its toggle calls the store's ``disable`` / ``enable``
    server actions. Disabled plugins stay listed (state ``disabled``) so they
    can be re-enabled.
    """
    __tag__ = "ui-plugin-manager"

    def toggle(self, event):
        """Disable or enable the plugin named by ``data-plugin-name`` on the row.

        Synchronous on purpose: ``event.currentTarget`` is only valid *during*
        event dispatch — an async handler runs later (on the event loop) when
        ``currentTarget`` is already ``JsNull``. So read the target here and
        schedule the store's server action on the loop.
        """
        target = getattr(event, "currentTarget", None)
        if target is None:
            return
        name = target.getAttribute("data-plugin-name")
        if not name:
            return
        store = self.S.get("plugins")
        if store is None:
            return
        info = (getattr(store, "items", None) or {}).get(name)
        if info is None:
            return
        if info.get("state") == "enabled":
            asyncio.ensure_future(store.disable(name))
        else:
            asyncio.ensure_future(store.enable(name))

    def button_label(self, info):
        return "Disable" if info.get("state") == "enabled" else "Enable"

    def requires_text(self, info):
        reqs = info.get("requires") or []
        return ", ".join(reqs) if reqs else "none"

    def template(self):
        """
        <div class="ui-plugin-manager">
            <div class="ui-plugin-manager-head">
                <span class="ui-plugin-manager-title">Plugins</span>
                <span class="ui-plugin-manager-count">{len($plugins.items)}</span>
            </div>
            <div class="ui-plugin-manager-list">
                <div class="ui-plugin-manager-row" for="entry" in="{$plugins.items.items()}">
                    <div class="ui-plugin-manager-main">
                        <span class="ui-plugin-manager-name">{entry[0]}</span>
                        <span class="ui-plugin-manager-state {entry[1]['state']}">{entry[1]['state']}</span>
                    </div>
                    <div class="ui-plugin-manager-meta">
                        <span>{len(entry[1]['actions'])} action(s)</span>
                        <span>requires: {requires_text(entry[1])}</span>
                    </div>
                    <button class="ui-plugin-manager-toggle" onclick="{toggle}" data-plugin-name="{entry[0]}">
                        {button_label(entry[1])}
                    </button>
                </div>
            </div>
        </div>
        """

    def style(self):
        """
        ui-plugin-manager {
            display: block;
        }

        .ui-plugin-manager {
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-md, 0.5rem);
            background: var(--bg-secondary, #f8f9fa);
            padding: 0.75rem;
            font-family: inherit;
            font-size: 0.85rem;
        }

        .ui-plugin-manager-head {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }

        .ui-plugin-manager-title {
            font-weight: 600;
            color: var(--text-primary, #212529);
        }

        .ui-plugin-manager-count {
            background: var(--bg-tertiary, #e9ecef);
            border-radius: 999px;
            padding: 0.1rem 0.5rem;
            font-size: 0.75rem;
            color: var(--text-secondary, #495057);
        }

        .ui-plugin-manager-list {
            display: flex;
            flex-direction: column;
            gap: 0.375rem;
        }

        .ui-plugin-manager-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            background: var(--bg-primary, #ffffff);
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-sm, 0.25rem);
            padding: 0.5rem 0.625rem;
        }

        .ui-plugin-manager-main {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            min-width: 0;
        }

        .ui-plugin-manager-name {
            font-weight: 600;
            color: var(--text-primary, #212529);
        }

        .ui-plugin-manager-state {
            border-radius: 999px;
            padding: 0.05rem 0.5rem;
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        .ui-plugin-manager-state.enabled {
            background: rgba(40, 167, 69, 0.15);
            color: #1e7e34;
        }

        .ui-plugin-manager-state.disabled {
            background: rgba(220, 53, 69, 0.12);
            color: #b02a37;
        }

        .ui-plugin-manager-meta {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            font-size: 0.7rem;
            color: var(--text-secondary, #495057);
        }

        .ui-plugin-manager-toggle {
            background: var(--accent-color, #007acc);
            color: #ffffff;
            border: none;
            border-radius: var(--radius-sm, 0.25rem);
            padding: 0.3rem 0.75rem;
            font-size: 0.78rem;
            font-family: inherit;
            cursor: pointer;
        }

        .ui-plugin-manager-toggle:hover {
            filter: brightness(1.1);
        }
        """
