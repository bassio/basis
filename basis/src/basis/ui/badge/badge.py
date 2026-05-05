from basis.shared.component import Component


class Badge(Component):
    """
    A compact, versatile Badge / Tag component for categorization.

    Attributes:
        label      : The text content.
        variant    : 'default' | 'primary' | 'success' | 'warning' | 'danger' | 'outline'
        size       : 'sm' | 'md' | 'lg'
        removable  : "" | "true" — shows an × button.
        dot        : "" | "true" — shows a colored status dot.
    """
    __tag__ = "ui-badge"

    label     = ""
    variant   = "default"  # default | primary | success | warning | danger | outline
    size      = "md"       # sm | md | lg
    removable = ""         # "" | "true"
    dot       = ""         # "" | "true"

    def on_remove(self, event):
        """Override in usage to handle removal. Default: hide the badge."""
        el = self.__element__
        if el:
            el.style.display = "none"

    def style(self):
        """
        /* ── Host ───────────────────────────────────────────── */
        ui-badge {
            display: inline-flex;
        }

        /* ── Base badge ─────────────────────────────────────── */
        .ui-badge {
            display: inline-flex;
            align-items: center;
            gap: 0.3em;
            border-radius: 9999px;
            font-weight: 500;
            letter-spacing: 0.02em;
            white-space: nowrap;
            border: 1px solid transparent;
            line-height: 1;
            transition:
                background-color 0.15s ease,
                border-color     0.15s ease,
                opacity          0.15s ease;
        }

        /* ── Sizes ──────────────────────────────────────────── */
        .ui-badge-sm { font-size: 0.68rem;  padding: 0.18rem 0.55rem; }
        .ui-badge-md { font-size: 0.75rem;  padding: 0.25rem 0.7rem;  }
        .ui-badge-lg { font-size: 0.875rem; padding: 0.35rem 0.9rem;  }

        /* ── Variants ───────────────────────────────────────── */
        .ui-badge-default {
            background-color: var(--bg-tertiary, #e8e8e8);
            color: var(--text-secondary, #7a7a7a);
            border-color: var(--border-color, #dcdcdc);
        }
        .ui-badge-primary {
            background-color: color-mix(in srgb, var(--accent-color, #007acc) 15%, transparent);
            color: var(--accent-color, #007acc);
            border-color: color-mix(in srgb, var(--accent-color, #007acc) 35%, transparent);
        }
        .ui-badge-success {
            background-color: rgba(34, 197, 94, 0.12);
            color: #16a34a;
            border-color: rgba(34, 197, 94, 0.3);
        }
        .ui-badge-warning {
            background-color: rgba(245, 158, 11, 0.12);
            color: #d97706;
            border-color: rgba(245, 158, 11, 0.3);
        }
        .ui-badge-danger {
            background-color: rgba(239, 68, 68, 0.12);
            color: #dc2626;
            border-color: rgba(239, 68, 68, 0.3);
        }
        .ui-badge-outline {
            background-color: transparent;
            color: var(--text-primary, #2e2e2e);
            border-color: var(--border-color, #dcdcdc);
        }

        /* ── Status dot ─────────────────────────────────────── */
        .ui-badge-dot {
            width: 0.5em;
            height: 0.5em;
            border-radius: 50%;
            background: currentColor;
            flex-shrink: 0;
        }

        /* ── Remove button ──────────────────────────────────── */
        .ui-badge-remove {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-left: 0.15em;
            width: 1em;
            height: 1em;
            border-radius: 50%;
            border: none;
            background: transparent;
            color: currentColor;
            cursor: pointer;
            opacity: 0.6;
            padding: 0;
            font-size: 0.9em;
            line-height: 1;
            transition: opacity 0.15s, background-color 0.15s;
        }
        .ui-badge-remove:hover {
            opacity: 1;
            background-color: rgba(0,0,0,0.12);
        }
        """

    def template(self):
        """
        <span class="ui-badge ui-badge-{variant} ui-badge-{size}">
            <span class="ui-badge-dot" if="{dot}"></span>
            <span class="ui-badge-label">{label}</span>
            <button
                class="ui-badge-remove"
                type="button"
                aria-label="Remove {label}"
                if="{removable}"
                onclick="{on_remove}">×</button>
        </span>
        """
