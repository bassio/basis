from basis.shared.component import Component, IS_CLIENT
from basis.shared.reactive import computed

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None

class CommandPalette(Component):
    """
    A global floating fuzzy-search command bar activated via keyboard shortcuts.
    
    Attributes:
        open:        "true" | "" (controls display state)
        placeholder: Text prompt for the search field
        query:       Bound text search filter
        commands:    List of command dicts: [{"id", "label", "shortcut", "category", "action"}]
        active_index: Highlighting index
    """
    __tag__ = "ui-command-palette"

    open = ""
    placeholder = "Type a command or search..."
    query = ""
    commands = []
    active_index = 0

    def __init__(self):
        super().__init__()
        self.commands = []
        self.query = ""
        self.active_index = 0
        self.open = ""
        
        if IS_CLIENT and window:
            self._keydown_proxy = ffi.create_proxy(self.global_keydown)
            window.addEventListener("keydown", self._keydown_proxy)

    @computed(dependencies=["query", "commands"])
    def filtered_commands(self):
        q = str(self.query).lower().strip()
        cmds = self.commands or []
        if not q:
            return cmds
        
        results = []
        for cmd in cmds:
            label = str(cmd.get("label", "")).lower()
            category = str(cmd.get("category", "")).lower()
            if q in label or q in category:
                results.append(cmd)
        return results

    def global_keydown(self, event):
        key = event.key
        meta = event.metaKey or event.ctrlKey
        
        if meta and (key.lower() == "k" or key.lower() == "p"):
            event.preventDefault()
            self.open = "true" if not self.open else ""
            self.query = ""
            self.active_index = 0
            
            if self.open and IS_CLIENT:
                def focus_input(*a):
                    inp = self.__element__.querySelector(".ui-palette-input")
                    if inp:
                        inp.focus()
                window.setTimeout(ffi.create_proxy(focus_input), 50)
                
        elif key == "Escape" and self.open:
            event.preventDefault()
            self.open = ""

    def on_input(self, event):
        self.query = event.target.value
        self.active_index = 0

    def on_input_keydown(self, event):
        key = event.key
        fc = self.filtered_commands()
        
        if key == "ArrowDown":
            event.preventDefault()
            if fc:
                self.active_index = (self.active_index + 1) % len(fc)
        elif key == "ArrowUp":
            event.preventDefault()
            if fc:
                self.active_index = (self.active_index - 1) % len(fc)
        elif key == "Enter":
            event.preventDefault()
            if fc and 0 <= self.active_index < len(fc):
                self.execute_command(fc[self.active_index])

    def execute_command(self, cmd):
        self.open = ""
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "select",
                ffi.to_js({"detail": {"command": cmd}, "bubbles": True})
            ))

    def select_item_click(self, event):
        target = event.target
        cmd_id = None
        curr = target
        while curr:
            if hasattr(curr, "getAttribute") and curr.getAttribute("data-id"):
                cmd_id = curr.getAttribute("data-id")
                break
            curr = curr.parentNode
        
        if cmd_id:
            fc = self.filtered_commands()
            for c in fc:
                if str(c.get("id", c.get("label"))) == cmd_id:
                    self.execute_command(c)
                    break

    def on_overlay_click(self, event):
        if event.target == event.currentTarget:
            self.open = ""

    def stop_propagation(self, event):
        event.stopPropagation()

    def style(self):
        """
        ui-command-palette {
            display: contents;
        }

        .ui-palette-overlay {
            position: fixed;
            inset: 0;
            background: rgba(0, 0, 0, 0.4);
            display: flex;
            justify-content: center;
            padding-top: 15vh;
            z-index: 2000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.18s ease;
        }

        .ui-palette-overlay.ui-palette-open {
            opacity: 1;
            pointer-events: auto;
        }

        .ui-palette-dialog {
            border: 1px solid var(--border-color, #dee2e6);
            border-radius: var(--radius-lg, 0.75rem);
            box-shadow: var(--shadow-md, 0 10px 25px -5px rgba(0,0,0,0.15));
            width: 100%;
            max-width: 550px;
            display: flex;
            flex-direction: column;
            max-height: 380px;
            overflow: hidden;
            transform: translateY(-8px) scale(0.98);
            transition: transform 0.18s cubic-bezier(0.16, 1, 0.3, 1);
        }

        .ui-palette-overlay.ui-palette-open .ui-palette-dialog {
            transform: translateY(0) scale(1);
        }

        .ui-palette-header {
            display: flex;
            align-items: center;
            padding: 0.85rem 1.1rem;
            border-bottom: 1px solid var(--border-color, #dee2e6);
            gap: 0.75rem;
        }

        .ui-palette-search-icon {
            font-size: 1.1rem;
            color: var(--text-secondary, #6b7280);
            flex-shrink: 0;
        }

        .ui-palette-input {
            flex: 1;
            border: none;
            outline: none;
            background: transparent;
            color: var(--text-primary, #212529);
            font-size: 0.95rem;
            font-family: inherit;
        }

        .ui-palette-input::placeholder {
            color: var(--text-secondary, #9ca3af);
        }

        .ui-palette-esc-badge {
            font-size: 0.68rem;
            font-weight: 600;
            background: var(--bg-tertiary, #e5e7eb);
            color: var(--text-secondary, #6b7280);
            padding: 0.15rem 0.4rem;
            border-radius: var(--radius-sm, 0.25rem);
            border: 1px solid var(--border-color, #d1d5db);
        }

        .ui-palette-results {
            flex: 1;
            overflow-y: auto;
            padding: 0.5rem;
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }

        .ui-palette-no-results {
            padding: 2rem 1rem;
            text-align: center;
            font-size: 0.875rem;
            color: var(--text-secondary, #6b7280);
        }

        .ui-palette-item {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.6rem 0.85rem;
            border-radius: var(--radius-md, 0.375rem);
            cursor: pointer;
            transition: background 0.1s, color 0.1s;
        }

        .ui-palette-item.ui-palette-active {
            background: var(--accent-color, #007acc);
            color: #ffffff;
        }

        .ui-palette-item.ui-palette-active .ui-palette-item-category,
        .ui-palette-item.ui-palette-active .ui-palette-item-shortcut {
            color: rgba(255, 255, 255, 0.8);
            border-color: rgba(255, 255, 255, 0.3);
        }

        .ui-palette-item-left {
            display: flex;
            align-items: center;
            gap: 0.6rem;
            min-width: 0;
        }

        .ui-palette-item-category {
            font-size: 0.7rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-secondary, #868b94);
            background: var(--hover-bg, rgba(0,0,0,0.05));
            padding: 0.1rem 0.35rem;
            border-radius: 0.25rem;
            flex-shrink: 0;
        }

        .ui-palette-item-label {
            font-size: 0.875rem;
            font-weight: 500;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }

        .ui-palette-item-shortcut {
            font-size: 0.725rem;
            font-family: monospace;
            color: var(--text-secondary, #6b7280);
            border: 1px solid var(--border-color, #d1d5db);
            padding: 0.1rem 0.35rem;
            border-radius: 0.25rem;
        }
        """

    def template(self):
        """
        <div class="ui-palette-overlay {open and 'ui-palette-open' or ''}" onclick="{on_overlay_click}">
            <div class="ui-palette-dialog" onclick="{stop_propagation}">
                <div class="ui-palette-header">
                    <span class="ui-palette-search-icon">🔍</span>
                    <input 
                        class="ui-palette-input" 
                        type="text" 
                        placeholder="{placeholder}" 
                        value="{query}" 
                        oninput="{on_input}"
                        onkeydown="{on_input_keydown}" />
                    <span class="ui-palette-esc-badge">ESC</span>
                </div>
                <div class="ui-palette-results">
                    <div class="ui-palette-no-results" if="{not filtered_commands()}">
                        No results found for "{query}"
                    </div>
                    <div 
                        class="ui-palette-item {index == active_index and 'ui-palette-active' or ''}" 
                        for="cmd" in="{filtered_commands()}" 
                        key="id"
                        onclick="{select_item_click}"
                        data-id="{cmd.get('id', cmd.get('label'))}">
                        <div class="ui-palette-item-left">
                            <span class="ui-palette-item-category" if="{cmd.get('category')}">{cmd.get('category')}</span>
                            <span class="ui-palette-item-label">{cmd.get('label')}</span>
                        </div>
                        <kbd class="ui-palette-item-shortcut" if="{cmd.get('shortcut')}">{cmd.get('shortcut')}</kbd>
                    </div>
                </div>
            </div>
        </div>
        """
