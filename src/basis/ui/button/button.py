from basis.shared.component import Component


class Button(Component):
    """
    A premium, accessible button component.

    Attributes:
        label     : Text displayed inside the button.
        variant   : Visual style — 'primary' | 'secondary' | 'ghost' | 'outline' | 'danger'
        size      : 'sm' | 'md' | 'lg'
        loading   : If truthy, shows a spinner and disables interaction.
        disabled  : If truthy, disables the button.
        icon      : Optional leading icon (HTML string / emoji).
        icon_right: Optional trailing icon (HTML string / emoji).
    """
    __tag__ = "ui-button"

    label      = ""
    variant    = "primary"   # primary | secondary | ghost | outline | danger
    size       = "md"        # sm | md | lg
    loading    = ""          # "" | "true"
    disabled   = ""          # "" | "true"
    icon       = ""
    icon_right = ""

    def style(self):
        """
        /* ── ui-button host ─────────────────────────────────── */
        ui-button {
            display: inline-flex;
        }

        /* ── Base button reset ──────────────────────────────── */
        .ui-btn {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            gap: 0.4em;
            font-family: inherit;
            font-weight: 500;
            letter-spacing: 0.01em;
            border: 1px solid transparent;
            border-radius: 0.5rem;
            cursor: pointer;
            white-space: nowrap;
            outline: none;
            position: relative;
            overflow: hidden;
            transition:
                background-color 0.18s ease,
                border-color     0.18s ease,
                color            0.18s ease,
                box-shadow       0.18s ease,
                transform        0.12s ease,
                opacity          0.18s ease;
            text-decoration: none;
            user-select: none;
        }

        /* ripple pseudo-element */
        .ui-btn::after {
            content: '';
            position: absolute;
            inset: 0;
            border-radius: inherit;
            background: rgba(255,255,255,0.12);
            opacity: 0;
            transition: opacity 0.2s;
        }
        .ui-btn:active::after {
            opacity: 1;
        }

        /* ── Sizes ──────────────────────────────────────────── */
        .ui-btn-sm { font-size: 0.775rem; padding: 0.3rem 0.75rem; }
        .ui-btn-md { font-size: 0.875rem; padding: 0.45rem 1rem;   }
        .ui-btn-lg { font-size: 1rem;     padding: 0.6rem 1.35rem; }

        /* ── Variants ───────────────────────────────────────── */
        /* Primary */
        .ui-btn-primary {
            background-color: var(--accent-color, #007acc);
            color: #ffffff;
            border-color: transparent;
            box-shadow: 0 1px 4px rgba(0, 122, 204, 0.25);
        }
        .ui-btn-primary:hover:not(:disabled) {
            background-color: color-mix(in srgb, var(--accent-color, #007acc) 85%, black);
            box-shadow: 0 4px 12px rgba(0, 122, 204, 0.35);
            transform: translateY(-1px);
        }
        .ui-btn-primary:active:not(:disabled) { transform: translateY(0); }

        /* Secondary */
        .ui-btn-secondary {
            background-color: var(--bg-tertiary, #e8e8e8);
            color: var(--text-primary, #2e2e2e);
            border-color: var(--border-color, #dcdcdc);
        }
        .ui-btn-secondary:hover:not(:disabled) {
            background-color: var(--hover-bg, #f5f5f5);
            border-color: var(--text-secondary, #7a7a7a);
            transform: translateY(-1px);
        }

        /* Ghost */
        .ui-btn-ghost {
            background-color: transparent;
            color: var(--text-secondary, #7a7a7a);
            border-color: transparent;
        }
        .ui-btn-ghost:hover:not(:disabled) {
            background-color: var(--hover-bg, rgba(0,0,0,0.06));
            color: var(--text-primary, #2e2e2e);
        }

        /* Outline */
        .ui-btn-outline {
            background-color: transparent;
            color: var(--accent-color, #007acc);
            border-color: var(--accent-color, #007acc);
        }
        .ui-btn-outline:hover:not(:disabled) {
            background-color: color-mix(in srgb, var(--accent-color, #007acc) 10%, transparent);
            transform: translateY(-1px);
        }

        /* Danger */
        .ui-btn-danger {
            background-color: #ef4444;
            color: #ffffff;
            border-color: transparent;
            box-shadow: 0 1px 4px rgba(239, 68, 68, 0.25);
        }
        .ui-btn-danger:hover:not(:disabled) {
            background-color: #dc2626;
            box-shadow: 0 4px 12px rgba(239, 68, 68, 0.35);
            transform: translateY(-1px);
        }

        /* ── Disabled & Loading states ──────────────────────── */
        .ui-btn:disabled,
        .ui-btn[disabled] {
            opacity: 0.45;
            cursor: not-allowed;
            transform: none !important;
            box-shadow: none !important;
        }

        .ui-btn-loading {
            cursor: not-allowed;
            pointer-events: none;
            opacity: 0.8;
        }

        /* ── Spinner ────────────────────────────────────────── */
        .ui-btn-spinner {
            width: 0.875em;
            height: 0.875em;
            border: 2px solid currentColor;
            border-top-color: transparent;
            border-radius: 50%;
            animation: ui-btn-spin 0.65s linear infinite;
            flex-shrink: 0;
        }

        @keyframes ui-btn-spin {
            to { transform: rotate(360deg); }
        }

        /* ── Icon ───────────────────────────────────────────── */
        .ui-btn-icon {
            display: inline-flex;
            align-items: center;
            flex-shrink: 0;
            font-size: 1em;
            line-height: 1;
        }
        """

    def template(self):
        """
        <button
            class="ui-btn ui-btn-{variant} ui-btn-{size} {loading and 'ui-btn-loading' or ''}"
            {disabled}>
            <span class="ui-btn-icon" if="{icon and not loading}">{icon}</span>
            <span class="ui-btn-spinner" if="{loading}"></span>
            <span class="ui-btn-label">{label}</span>
            <span class="ui-btn-icon" if="{icon_right and not loading}">{icon_right}</span>
        </button>
        """
