from basis.shared.component import Component, IS_CLIENT, py_event

if IS_CLIENT:
    from pyscript import window, ffi
else:
    window = ffi = None


class TreeView(Component):
    """
    A recursive file/folder explorer tree view component.
    
    Attributes:
        data:          Nested data list, e.g. [{"label": "src", "path": "/src", "children": [...]}]
        selected_path: Currently selected node path/key.
    """
    __tag__ = "ui-tree-view"

    data = [{"label": "src", "path": "/src", "children": []},{"label": "src", "path": "/src", "children": []},]
    selected_path = ""

    @py_event
    def handle_node_select(self, event):
        path = event.detail.get("path") if event.detail else ""
        self.selected_path = path
        
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "change",
                ffi.to_js({"detail": {"path": path}, "bubbles": True})
            ))

    def style(self):
        """
        ui-tree-view {
            display: block;
            width: 100%;
            user-select: none;
        }
        .ui-tree-view {
            display: flex;
            flex-direction: column;
            gap: 2px;
            font-family: inherit;
        }
        """

    def template(self):
        """
        <div class="ui-tree-view" onnodeselect="{handle_node_select}">
            <ui-tree-node 
                for="n" in="{data}" 
                key="path"
                label="{n}"
                path="{n}"
                children="{n}"
                selected_path="{selected_path}">
            </ui-tree-node>
        </div>
        """


class TreeNode(Component):
    """
    A recursive child node of a TreeView.
    """
    __tag__ = "ui-tree-node"

    label = ""
    path = ""
    children = []
    selected_path = ""
    open = False

    def toggle_open(self, event):
        # Prevent row selection from executing when clicking the chevron
        event.stopPropagation()
        self.open = not self.open

    def select_node(self, event):
        event.stopPropagation()
        if IS_CLIENT and self.__element__:
            self.__element__.dispatchEvent(window.CustomEvent.new(
                "nodeselect",
                ffi.to_js({"detail": {"path": self.path}, "bubbles": True})
            ))

    def style(self):
        """
        ui-tree-node {
            display: block;
            width: 100%;
        }

        .ui-tree-node-row {
            display: flex;
            align-items: center;
            padding: 0.35rem 0.5rem;
            cursor: pointer;
            border-radius: var(--radius-sm, 0.25rem);
            color: var(--text-primary, #212529);
            font-size: 0.875rem;
            transition: background 0.12s, color 0.12s;
            gap: 0.45rem;
        }

        .ui-tree-node-row:hover {
            background-color: var(--hover-bg, rgba(0, 0, 0, 0.05));
        }

        .ui-tree-node-row.ui-tree-node-selected {
            background-color: var(--accent-color, #007acc);
            color: #ffffff;
        }

        .ui-tree-node-chevron {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1rem;
            height: 1rem;
            color: var(--text-secondary, #6c757d);
            transition: transform 0.15s ease;
            flex-shrink: 0;
        }

        .ui-tree-node-row.ui-tree-node-selected .ui-tree-node-chevron {
            color: rgba(255, 255, 255, 0.8);
        }

        .ui-tree-node-chevron.ui-tree-node-open {
            transform: rotate(90deg);
        }

        .ui-tree-node-chevron-empty {
            width: 1rem;
            height: 1rem;
            flex-shrink: 0;
        }

        .ui-tree-node-icon {
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 1rem;
            height: 1rem;
            color: var(--text-secondary, #6c757d);
            flex-shrink: 0;
        }

        .ui-tree-node-row.ui-tree-node-selected .ui-tree-node-icon {
            color: rgba(255, 255, 255, 0.9);
        }

        .ui-tree-node-label {
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            font-weight: 500;
        }

        .ui-tree-node-children {
            display: flex;
            flex-direction: column;
            gap: 2px;
            padding-left: 1rem;
            border-left: 1px solid var(--border-color, #dee2e6);
            margin-left: 0.5rem;
            margin-top: 2px;
        }
        """

    def template(self):
        """
        <div class="ui-tree-node-wrapper">
            <div class="ui-tree-node-row {selected_path == path and 'ui-tree-node-selected' or ''}" onclick="{select_node}">
                <span 
                    class="ui-tree-node-chevron {open and 'ui-tree-node-open' or ''}" 
                    if="{children}" 
                    onclick="{toggle_open}">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" width="12" height="12">
                        <polyline points="9 18 15 12 9 6"></polyline>
                    </svg>
                </span>
                <span class="ui-tree-node-chevron-empty" if="{not children}"></span>
                
                <span class="ui-tree-node-icon">
                    <svg if="{children}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                    </svg>
                    <svg if="{not children}" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2" width="14" height="14">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                </span>
                
                <span class="ui-tree-node-label">{label}</span>
            </div>
            
            <div class="ui-tree-node-children" if="{children and open}">
                <ui-tree-node 
                    for="child" in="{children}" 
                    key="path"
                    label="{child.get('label', '')}"
                    path="{child.get('path', '')}"
                    children="{child.get('children', [])}"
                    selected_path="{selected_path}">
                </ui-tree-node>
            </div>
        </div>
        """
