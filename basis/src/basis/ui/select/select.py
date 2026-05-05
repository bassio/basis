from basis.shared.component import Component


class Select(Component):
    """
    A custom, styleable <select> dropdown (non-searchable, native-based).

    Attributes:
        label    : Label shown above the select.
        options  : List of dicts — [{label, value}, ...]  OR list of strings.
        value    : Currently selected value.
        placeholder: Grayed-out prompt option (value="").
        disabled : "" | "true"
        size     : 'sm' | 'md' | 'lg'
        helper   : Hint text below.
        error    : Validation error message.
    """
    __tag__ = "ui-select"

    label       = ""
    options     = []
    value       = ""
    placeholder = "Select an option…"
    disabled    = ""
    size        = "md"
    helper      = ""
    error       = ""

    def on_change(self, event):
        self.value = event.target.value

    def style(self):
        """
        ui-select {
            display: flex;
            flex-direction: column;
        }

        /* ── Wrapper ─────────────────────────────────────────── */
        .ui-select-wrapper {
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
            width: 100%;
        }

        /* ── Label ──────────────────────────────────────────── */
        .ui-select-label {
            font-size: 0.8rem;
            font-weight: 500;
            color: var(--text-secondary, #7a7a7a);
            letter-spacing: 0.02em;
        }

        /* ── Inner (positions the chevron overlay) ──────────── */
        .ui-select-inner {
            position: relative;
            display: flex;
            align-items: center;
        }

        /* ── Native <select> ────────────────────────────────── */
        .ui-select-field {
            appearance: none;
            -webkit-appearance: none;
            width: 100%;
            border: 1px solid var(--border-color, #dcdcdc);
            border-radius: 0.5rem;
            background: var(--bg-primary, #fff);
            color: var(--text-primary, #2e2e2e);
            font-family: inherit;
            cursor: pointer;
            outline: none;
            transition:
                border-color 0.2s ease,
                box-shadow   0.2s ease;
            /* right padding reserves space for chevron */
            padding-right: 2.5rem !important;
        }

        /* Sizes */
        .ui-select-sm .ui-select-field { font-size: 0.78rem;  padding: 0.3rem 0.6rem; }
        .ui-select-md .ui-select-field { font-size: 0.875rem; padding: 0.45rem 0.75rem; }
        .ui-select-lg .ui-select-field { font-size: 1rem;     padding: 0.6rem 0.9rem; }

        .ui-select-field:focus {
            border-color: var(--accent-color, #007acc);
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-color, #007acc) 15%, transparent);
        }
        .ui-select-field:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* Error state */
        .ui-select-error .ui-select-field {
            border-color: #ef4444;
        }
        .ui-select-error .ui-select-field:focus {
            box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15);
        }

        /* ── Chevron icon (absolute overlay) ────────────────── */
        .ui-select-chevron {
            position: absolute;
            right: 0.75rem;
            pointer-events: none;
            color: var(--text-secondary, #7a7a7a);
            display: flex;
            align-items: center;
        }
        .ui-select-chevron svg {
            width: 1rem;
            height: 1rem;
        }

        /* ── Helper / error text ────────────────────────────── */
        .ui-select-helper {
            font-size: 0.76rem;
            color: var(--text-secondary, #7a7a7a);
            padding-left: 0.1rem;
        }
        .ui-select-error-msg {
            font-size: 0.76rem;
            color: #ef4444;
            padding-left: 0.1rem;
            display: flex;
            align-items: center;
            gap: 0.25rem;
        }
        """

    def template(self):
        """
        <div class="ui-select-wrapper ui-select-{size} {error and 'ui-select-error' or ''}">
            <label class="ui-select-label" if="{label}">{label}</label>
            <div class="ui-select-inner">
                <select
                    class="ui-select-field"
                    {disabled}
                    onchange="{on_change}">
                    <option value="" disabled="disabled" selected="{not value}">{placeholder}</option>
                    <option
                        for:each="{options}"
                        value="{item['value'] if isinstance(item, dict) else item}"
                        selected="{(item['value'] if isinstance(item, dict) else item) == value}">
                        {item['label'] if isinstance(item, dict) else item}
                    </option>
                </select>
                <!-- Custom chevron -->
                <span class="ui-select-chevron">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none"
                         stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                        <polyline points="6 9 12 15 18 9"></polyline>
                    </svg>
                </span>
            </div>
            <span class="ui-select-error-msg" if="{error}">⚠ {error}</span>
            <span class="ui-select-helper" if="{helper and not error}">{helper}</span>
        </div>
        """
