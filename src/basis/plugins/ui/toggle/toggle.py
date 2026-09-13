from basis.shared.component import Component


class Toggle(Component):
    """A controlled boolean switch.

    ``value`` is the component's state (one of ``first`` / ``second``) and is
    parent-driven: bind it (e.g. ``value="{$store.flag}"``) so external changes
    move the switch, and handle the bubbling ``change`` event to write state
    back (or persist it, e.g. through a store action on the owner).  The
    control never writes outside its own ``value``: the owner persists.
    """

    __tag__ = "ui-toggle"
    first = ""
    second = ""
    value = ""
    checked = False

    def __init_bindings__(self):
        super().__init_bindings__()
        # Reflect the bound value onto the checkbox on first mount.
        self._sync_checked()

    def __setattr__(self, name, value):
        super().__setattr__(name, value)
        # Keep the checkbox in sync whenever the parent re-binds ``value``
        # (e.g. the titlebar button flips theme.dark_mode → the toggle updates).
        if name == "value":
            self._sync_checked()

    def _sync_checked(self):
        """Set checkbox.checked from the bound ``value`` (checked == second).

        Guarded so it is a no-op on the server (no client DOM) and before the
        element exists during initialization.
        """
        element = getattr(self, "__element__", None)
        query = getattr(element, "querySelector", None)
        if query is None:
            return
        try:
            checkbox = query(".toggle-checkbox")
        except Exception:
            checkbox = None
        if checkbox is None:
            return
        if isinstance(self.value, bool):
            checked = self.value
        else:
            checked = self.value not in ("", None) and str(self.value) == str(self.second)
        checkbox.checked = bool(checked)

    def on_change(self, event):
        # Keep the control's own declared state (``value``) in sync with the
        # DOM (mirrors Checkbox.on_change).  Writing state back to a store /
        # parent is the owner's job — e.g. a persisting store action in the
        # handler bound to the bubbling change event.
        checkbox = self.__element__.querySelector('.toggle-checkbox')
        is_checked = bool(getattr(checkbox, "checked", False)) if checkbox else False
        self.value = self.second if is_checked else self.first

    def style(self):
        """
        ui-toggle {
            display: inline-flex;
        }
        .switch-container {
            display: inline-flex;
            align-items: center;
            cursor: pointer;
        }
        .toggle-checkbox {
            display: none;
        }
        .switch {
            position: relative;
            display: inline-flex;
            height: 24px;
            width: 44px;
            align-items: center;
            border-radius: 9999px;
            background-color: var(--bg-tertiary, #e4e4e7);
            transition: background-color 0.2s;
            border: 2px solid transparent;
        }
        .switch-container:hover .switch {
            background-color: #d4d4d8;
        }
        .toggle-checkbox:checked + .switch {
            background-color: var(--accent-color, #007acc);
        }
        .toggle-checkbox:checked + .switch:hover {
            background-color: var(--accent-color, #005a9e);
        }
        .thumb {
            pointer-events: none;
            display: inline-block;
            height: 20px;
            width: 20px;
            transform: translateX(0);
            border-radius: 9999px;
            background-color: #ffffff;
            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.2);
            transition: transform 0.2s cubic-bezier(0.4, 0.0, 0.2, 1);
        }
        .toggle-checkbox:checked + .switch .thumb {
            transform: translateX(20px);
        }
        """

    def template(self):
        """
        <label class="switch-container">
            <input type="checkbox" class="toggle-checkbox" onchange="{on_change}" value="{value}" />
            <span class="switch">
                <span class="thumb"></span>
            </span>
        </label>
        """
