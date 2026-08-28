"""Shared registry-manager base — the row/action machinery behind the plugin
manager and the theme manager (ROADMAP-THEMING.md §6.5.4).

One component base renders reactive rows over a ``$<registry>.items`` projection
(the ``$plugins`` / ``$themes`` stores, which share one shape): row chrome, the
state badge, and the per-row action dispatch. The two faces differ only by the
registry name, the literal store reference in their template (reactivity needs
it), and :meth:`primary_action`.
"""

from basis.shared.component import Component


class RegistryManager(Component):
    """Reactive rows over a ``$<registry>.items`` projection.

    Subclass sets ``registry`` (``"plugins"`` / ``"themes"``) + a ``__tag__``,
    keeps a template that loops the literal ``$<registry>.items.items()`` (so
    reactivity is tracked), and implements :meth:`primary_action`.
    """

    registry = "plugins"

    def toggle(self, event):
        """The row's primary action — disable/enable for the plugin manager,
        apply for the theme manager.

        Reads ``data-name`` off the clicked row and dispatches to
        :meth:`primary_action`. Synchronous on purpose: ``event.currentTarget``
        is only valid *during* event dispatch — an async handler runs later (on
        the event loop) when ``currentTarget`` is already ``JsNull``. So read
        the target here and let ``primary_action`` schedule the store action.
        """
        target = getattr(event, "currentTarget", None)
        if target is None:
            return
        name = target.getAttribute("data-name")
        if not name:
            return
        store = self.S.get(self.registry)
        if store is None:
            return
        info = (getattr(store, "items", None) or {}).get(name)
        if info is None:
            return
        self.primary_action(name, info)

    def primary_action(self, name, info):
        """Subclass hook — what a row's primary button does (plugin toggle vs.
        theme apply). Subclasses schedule the store server action here."""
        raise NotImplementedError

    def button_label(self, info):
        """The primary button's label (overridable — the theme manager says
        "Apply")."""
        return "Disable" if info.get("state") == "enabled" else "Enable"

    def requires_text(self, info):
        reqs = info.get("requires") or []
        return ", ".join(reqs) if reqs else "none"

    def style(self):
        """
        ui-plugin-manager, ui-theme-picker {
            display: block;
        }

        .ui-registry-manager {
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-md, 0.5rem);
            background: var(--bg-secondary, #f8f9fa);
            padding: 0.75rem;
            font-family: inherit;
            font-size: 0.85rem;
        }

        .ui-registry-manager-head {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            margin-bottom: 0.5rem;
        }

        .ui-registry-manager-title {
            font-weight: 600;
            color: var(--text-primary, #212529);
        }

        .ui-registry-manager-count {
            background: var(--bg-tertiary, #e9ecef);
            border-radius: 999px;
            padding: 0.1rem 0.5rem;
            font-size: 0.75rem;
            color: var(--text-secondary, #495057);
        }

        .ui-registry-manager-mode {
            margin-left: auto;
            border: 1px solid var(--border-color, #dee2e6);
            background: var(--bg-primary, #ffffff);
            color: var(--text-primary, #212529);
            border-radius: var(--radius-sm, 0.25rem);
            padding: 0.2rem 0.6rem;
            font-size: 0.75rem;
            font-family: inherit;
            cursor: pointer;
        }

        .ui-registry-manager-list {
            display: flex;
            flex-direction: column;
            gap: 0.375rem;
        }

        .ui-registry-manager-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 0.75rem;
            background: var(--bg-primary, #ffffff);
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-sm, 0.25rem);
            padding: 0.5rem 0.625rem;
        }

        .ui-registry-manager-main {
            display: flex;
            align-items: center;
            gap: 0.5rem;
            min-width: 0;
        }

        .ui-registry-manager-name {
            font-weight: 600;
            color: var(--text-primary, #212529);
        }

        .ui-registry-manager-state {
            border-radius: 999px;
            padding: 0.05rem 0.5rem;
            font-size: 0.7rem;
            text-transform: uppercase;
            letter-spacing: 0.03em;
        }

        .ui-registry-manager-state.enabled {
            background: rgba(40, 167, 69, 0.15);
            color: #1e7e34;
        }

        .ui-registry-manager-state.disabled {
            background: rgba(220, 53, 69, 0.12);
            color: #b02a37;
        }

        .ui-registry-manager-meta {
            display: flex;
            flex-direction: column;
            gap: 0.1rem;
            font-size: 0.7rem;
            color: var(--text-secondary, #495057);
        }

        .ui-registry-manager-toggle {
            background: var(--accent-color, #007acc);
            color: #ffffff;
            border: none;
            border-radius: var(--radius-sm, 0.25rem);
            padding: 0.3rem 0.75rem;
            font-size: 0.78rem;
            font-family: inherit;
            cursor: pointer;
        }

        .ui-registry-manager-toggle:hover {
            filter: brightness(1.1);
        }
        """
