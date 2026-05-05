from basis.shared.component import Component


class TextInput(Component):
    """
    A premium text input with label, prefix icon, suffix icon, helper text and validation.

    Attributes:
        label       : Floating / above label text.
        placeholder : Placeholder string.
        value       : Bound value.
        type        : HTML input type — 'text' | 'email' | 'password' | 'search' | 'number' …
        prefix_icon : Optional leading icon HTML/emoji.
        suffix_icon : Optional trailing icon HTML/emoji.
        helper      : Helper / hint text shown below the input.
        error       : Error message — when non-empty the input is styled as invalid.
        disabled    : "" | "true"
        size        : 'sm' | 'md' | 'lg'
    """
    __tag__ = "ui-text-input"

    label       = ""
    placeholder = ""
    value       = ""
    type        = "text"
    prefix_icon = ""
    suffix_icon = ""
    helper      = ""
    error       = ""
    disabled    = ""
    size        = "md"   # sm | md | lg

    def on_input(self, event):
        self.value = event.target.value

    def style(self):
        """
        /* ── Host ───────────────────────────────────────────── */
        ui-text-input {
            display: flex;
            flex-direction: column;
        }

        /* ── Field wrapper ─────────────────────────────────── */
        .ui-input-wrapper {
            display: flex;
            flex-direction: column;
            gap: 0.3rem;
            width: 100%;
        }

        /* ── Label ──────────────────────────────────────────── */
        .ui-input-label {
            font-size: 0.8rem;
            font-weight: 500;
            color: var(--text-secondary, #7a7a7a);
            letter-spacing: 0.02em;
            transition: color 0.2s;
        }

        /* ── Inner row (icon + input + icon) ────────────────── */
        .ui-input-inner {
            position: relative;
            display: flex;
            align-items: center;
            border: 1px solid var(--border-color, #dcdcdc);
            border-radius: 0.5rem;
            background: var(--bg-primary, #ffffff);
            transition:
                border-color 0.2s ease,
                box-shadow   0.2s ease;
            overflow: hidden;
        }

        .ui-input-inner:focus-within {
            border-color: var(--accent-color, #007acc);
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-color, #007acc) 15%, transparent);
        }

        /* Error state */
        .ui-input-inner.ui-input-error {
            border-color: #ef4444;
        }
        .ui-input-inner.ui-input-error:focus-within {
            box-shadow: 0 0 0 3px rgba(239, 68, 68, 0.15);
        }

        /* ── Prefix / suffix icons ──────────────────────────── */
        .ui-input-prefix,
        .ui-input-suffix {
            display: inline-flex;
            align-items: center;
            padding: 0 0.6rem;
            color: var(--text-secondary, #7a7a7a);
            flex-shrink: 0;
            font-size: 0.95em;
            pointer-events: none;
            user-select: none;
        }

        /* ── The native <input> ─────────────────────────────── */
        .ui-input-field {
            flex: 1;
            min-width: 0;
            border: none;
            outline: none;
            background: transparent;
            color: var(--text-primary, #2e2e2e);
            font-family: inherit;
            font-size: inherit;
            line-height: 1.5;
        }

        /* Sizes — applied to the field; padding on inner handles the rest */
        .ui-input-sm .ui-input-field { font-size: 0.78rem; padding: 0.3rem 0.5rem; }
        .ui-input-md .ui-input-field { font-size: 0.875rem; padding: 0.45rem 0.65rem; }
        .ui-input-lg .ui-input-field { font-size: 1rem;    padding: 0.6rem 0.8rem; }

        /* Sizes — when there IS a prefix icon, remove left padding from field */
        .ui-input-has-prefix .ui-input-field { padding-left: 0; }
        .ui-input-has-suffix .ui-input-field { padding-right: 0; }

        .ui-input-field::placeholder {
            color: var(--text-secondary, #aaa);
            opacity: 0.65;
        }
        .ui-input-field:disabled {
            opacity: 0.5;
            cursor: not-allowed;
        }

        /* ── Helper / error text ────────────────────────────── */
        .ui-input-helper {
            font-size: 0.76rem;
            color: var(--text-secondary, #7a7a7a);
            padding-left: 0.1rem;
        }
        .ui-input-error-msg {
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
        <div class="ui-input-wrapper">
            <label class="ui-input-label" if="{label}">{label}</label>
            <div class="ui-input-inner ui-input-{size} {error and 'ui-input-error' or ''} {prefix_icon and 'ui-input-has-prefix' or ''} {suffix_icon and 'ui-input-has-suffix' or ''}">
                <span class="ui-input-prefix" if="{prefix_icon}">{prefix_icon}</span>
                <input
                    class="ui-input-field"
                    type="{type}"
                    placeholder="{placeholder}"
                    value="{value}"
                    {disabled}
                    oninput="{on_input}" />
                <span class="ui-input-suffix" if="{suffix_icon}">{suffix_icon}</span>
            </div>
            <span class="ui-input-error-msg" if="{error}">⚠ {error}</span>
            <span class="ui-input-helper" if="{helper and not error}">{helper}</span>
        </div>
        """
