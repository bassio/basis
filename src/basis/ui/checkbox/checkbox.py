from basis.shared.component import Component


class Checkbox(Component):
    """
    A custom-styled, accessible checkbox.

    Attributes:
        label    : Text label placed to the right of the checkbox.
        checked  : "" | "true"
        disabled : "" | "true"
        name     : HTML name attribute.
        value    : HTML value attribute.
        size     : 'sm' | 'md' | 'lg'
    """
    __tag__ = "ui-checkbox"

    label    = ""
    checked  = ""
    disabled = ""
    name     = ""
    value    = ""
    size     = "md"

    def on_change(self, event):
        self.checked = "true" if event.target.checked else ""

    def style(self):
        """
        ui-checkbox {
            display: inline-flex;
        }

        /* ── Wrapper ─────────────────────────────────────────── */
        .ui-checkbox-label {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            cursor: pointer;
            user-select: none;
            font-size: 0.875rem;
            color: var(--text-primary, #2e2e2e);
        }
        .ui-checkbox-label.ui-checkbox-disabled {
            opacity: 0.45;
            cursor: not-allowed;
        }

        /* ── Hide native checkbox ───────────────────────────── */
        .ui-checkbox-native {
            position: absolute;
            width: 1px;
            height: 1px;
            padding: 0;
            margin: -1px;
            overflow: hidden;
            clip: rect(0,0,0,0);
            white-space: nowrap;
            border: 0;
        }

        /* ── Custom box ─────────────────────────────────────── */
        .ui-checkbox-box {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            border-radius: 0.3rem;
            border: 1.5px solid var(--border-color, #d1d5db);
            background: var(--bg-primary, #fff);
            flex-shrink: 0;
            transition:
                background-color 0.15s ease,
                border-color     0.15s ease,
                box-shadow       0.15s ease;
        }

        /* Sizes */
        .ui-checkbox-sm .ui-checkbox-box { width: 1rem;    height: 1rem;    border-radius: 0.25rem; }
        .ui-checkbox-md .ui-checkbox-box { width: 1.125rem; height: 1.125rem; }
        .ui-checkbox-lg .ui-checkbox-box { width: 1.35rem; height: 1.35rem; border-radius: 0.35rem; }

        /* Hover */
        .ui-checkbox-label:hover .ui-checkbox-box {
            border-color: var(--accent-color, #007acc);
        }

        /* Focus-visible ring via native focus propagation */
        .ui-checkbox-native:focus-visible + .ui-checkbox-box {
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-color, #007acc) 18%, transparent);
        }

        /* Checked state */
        .ui-checkbox-native:checked + .ui-checkbox-box {
            background-color: var(--accent-color, #007acc);
            border-color:     var(--accent-color, #007acc);
        }

        /* ── Checkmark SVG ──────────────────────────────────── */
        .ui-checkbox-check {
            display: none;
            width: 0.65em;
            height: 0.65em;
            stroke: #fff;
            stroke-width: 2.5;
            stroke-linecap: round;
            stroke-linejoin: round;
            fill: none;
        }
        .ui-checkbox-native:checked + .ui-checkbox-box .ui-checkbox-check {
            display: block;
            animation: ui-checkbox-pop 0.15s cubic-bezier(0.4, 0, 0.2, 1);
        }

        @keyframes ui-checkbox-pop {
            0%   { transform: scale(0.5); opacity: 0; }
            60%  { transform: scale(1.1); }
            100% { transform: scale(1);   opacity: 1; }
        }

        /* Label text */
        .ui-checkbox-text { line-height: 1.4; }
        """

    def template(self):
        """
        <label class="ui-checkbox-label ui-checkbox-{size} {disabled and 'ui-checkbox-disabled' or ''}">
            <input
                class="ui-checkbox-native"
                type="checkbox"
                name="{name}"
                value="{value}"
                {checked}
                {disabled}
                onchange="{on_change}" />
            <span class="ui-checkbox-box">
                <!-- Checkmark icon -->
                <svg class="ui-checkbox-check" viewBox="0 0 12 12" xmlns="http://www.w3.org/2000/svg">
                    <polyline points="1.5,6 4.5,9.5 10.5,2.5"></polyline>
                </svg>
            </span>
            <span class="ui-checkbox-text" if="{label}">{label}</span>
        </label>
        """


class RadioGroup(Component):
    """
    A styled radio button group.

    Attributes:
        options  : List of dicts — [{label, value}, ...]
        value    : Currently selected value (reactive).
        name     : Shared HTML name for all radios in this group.
        disabled : "" | "true"
        layout   : 'vertical' | 'horizontal'
    """
    __tag__ = "ui-radio-group"

    options  = []
    value    = ""
    name     = "radio-group"
    disabled = ""
    layout   = "vertical"   # vertical | horizontal

    def on_change(self, event):
        self.value = event.target.value

    def style(self):
        """
        ui-radio-group {
            display: flex;
        }

        /* ── Layout ─────────────────────────────────────────── */
        .ui-radio-group {
            display: flex;
            gap: 0.6rem;
        }
        .ui-radio-group-vertical   { flex-direction: column; }
        .ui-radio-group-horizontal { flex-direction: row; flex-wrap: wrap; }

        /* ── Each option ────────────────────────────────────── */
        .ui-radio-label {
            display: inline-flex;
            align-items: center;
            gap: 0.55rem;
            cursor: pointer;
            font-size: 0.875rem;
            color: var(--text-primary, #2e2e2e);
            user-select: none;
        }
        .ui-radio-label.ui-radio-disabled {
            opacity: 0.45;
            cursor: not-allowed;
        }

        /* ── Hide native ────────────────────────────────────── */
        .ui-radio-native {
            position: absolute;
            width: 1px; height: 1px;
            padding: 0; margin: -1px;
            overflow: hidden; clip: rect(0,0,0,0);
            white-space: nowrap; border: 0;
        }

        /* ── Custom circle ──────────────────────────────────── */
        .ui-radio-circle {
            width: 1.1rem;
            height: 1.1rem;
            border-radius: 50%;
            border: 1.5px solid var(--border-color, #d1d5db);
            background: var(--bg-primary, #fff);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
            transition:
                border-color     0.15s ease,
                background-color 0.15s ease;
        }
        .ui-radio-label:hover .ui-radio-circle {
            border-color: var(--accent-color, #007acc);
        }
        .ui-radio-native:checked + .ui-radio-circle {
            border-color: var(--accent-color, #007acc);
            background:   var(--accent-color, #007acc);
        }

        /* ── Inner dot ──────────────────────────────────────── */
        .ui-radio-dot {
            width: 0.42rem;
            height: 0.42rem;
            border-radius: 50%;
            background: #fff;
            opacity: 0;
            transform: scale(0);
            transition:
                opacity   0.15s ease,
                transform 0.15s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .ui-radio-native:checked + .ui-radio-circle .ui-radio-dot {
            opacity: 1;
            transform: scale(1);
        }

        /* Focus ring */
        .ui-radio-native:focus-visible + .ui-radio-circle {
            box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent-color, #007acc) 18%, transparent);
        }
        """

    def template(self):
        """
        <div class="ui-radio-group ui-radio-group-{layout}" onchange="{on_change}">
            <label class="ui-radio-label {disabled and 'ui-radio-disabled' or ''}"
                   for:each="{options}" key="{item['value']}">
                <input
                    class="ui-radio-native"
                    type="radio"
                    name="{name}"
                    value="{item['value']}"
                    {disabled} />
                <span class="ui-radio-circle">
                    <span class="ui-radio-dot"></span>
                </span>
                <span>{item['label']}</span>
            </label>
        </div>
        """
